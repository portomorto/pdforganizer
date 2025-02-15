# pdforg_base.py
import os
import re
import shutil
import logging
import requests
import time
import asyncio
import dataclasses
import argparse
from PyPDF2 import PdfReader
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

def parse_arguments():
    parser = argparse.ArgumentParser(description='Organize PDF files.')
    parser.add_argument('--input_dir', required=True, help='Directory containing PDFs to organize')
    parser.add_argument('--output_dir', required=True, help='Directory where to save organized PDFs')
    return parser.parse_args()

@dataclass
class Publication:
    title: str
    authors: list[str]
    year: str
    doi: Optional[str] = None
    isbn: Optional[str] = None
    publisher: Optional[str] = None
    abstract: Optional[str] = None

class MetadataFetcher:
    def __init__(self):
        self.headers = {
            'User-Agent': 'PdfOrganizer/1.0 (mailto:your@email.com)',
        }
        self.last_request_time = 0
        self.min_request_interval = 1

    def _rate_limit(self):
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        if time_since_last_request < self.min_request_interval:
            time.sleep(self.min_request_interval - time_since_last_request)
        self.last_request_time = time.time()

    async def search_crossref(self, query: str) -> Optional[Publication]:
        self._rate_limit()
        try:
            url = f"https://api.crossref.org/works"
            params = {
                'query': query,
                'rows': 1,
                'select': 'DOI,title,author,published-print,publisher'
            }
            response = requests.get(url, params=params, headers=self.headers)
            if response.status_code == 200:
                data = response.json()
                if data['message']['items']:
                    item = data['message']['items'][0]
                    return Publication(
                        title=item['title'][0],
                        authors=[author.get('given', '') + ' ' + author.get('family', '')
                                for author in item.get('author', [])],
                        year=str(item.get('published-print', {}).get('date-parts', [['']])[0][0]),
                        doi=item.get('DOI'),
                        publisher=item.get('publisher')
                    )
        except Exception as e:
            logging.error(f"Error in Crossref search: {str(e)}")
        return None

    async def search_semantic_scholar(self, query: str) -> Optional[Publication]:
        self._rate_limit()
        try:
            url = "https://api.semanticscholar.org/graph/v1/paper/search"
            params = {
                'query': query,
                'limit': 1,
                'fields': 'title,authors,year,abstract'
            }
            response = requests.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                if data['data']:
                    paper = data['data'][0]
                    return Publication(
                        title=paper['title'],
                        authors=[author['name'] for author in paper.get('authors', [])],
                        year=str(paper.get('year', '')),
                        abstract=paper.get('abstract')
                    )
        except Exception as e:
            logging.error(f"Error in Semantic Scholar search: {str(e)}")
        return None

    async def search_google_books(self, query: str) -> Optional[Publication]:
        self._rate_limit()
        try:
            url = "https://www.googleapis.com/books/v1/volumes"
            params = {'q': query, 'maxResults': 1}
            response = requests.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                if data.get('items'):
                    book = data['items'][0]['volumeInfo']
                    return Publication(
                        title=book.get('title', ''),
                        authors=book.get('authors', []),
                        year=book.get('publishedDate', '')[:4],
                        isbn=book.get('industryIdentifiers', [{}])[0].get('identifier'),
                        publisher=book.get('publisher')
                    )
        except Exception as e:
            logging.error(f"Error in Google Books search: {str(e)}")
        return None

class BasePdfOrganizer:
    def __init__(self, input_dir: str, output_dir: str):
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.metadata_fetcher = MetadataFetcher()
        self.setup_logging()

    def setup_logging(self):
        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'log')
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, 'pdf_organizer.log')

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_path),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def process_directory(self) -> Tuple[int, int, list[Tuple[str, Publication, str]]]:
        """
        Process all PDFs in the directory
        Returns:
            Tuple containing:
            - Number of successfully processed files
            - Number of failed files
            - List of tuples (original_filename, metadata, new_path) for successful files
        """
        successful = 0
        failed = 0
        processed_files = []

        # Create output directory if it doesn't exist
        os.makedirs(self.output_dir, exist_ok=True)

        # Get all PDF files from input directory
        pdf_files = []
        for root, _, files in os.walk(self.input_dir):
            for f in files:
                if not f.lower().endswith('.pdf'):
                    continue
                if f.startswith('._'):  # Ignora file nascosti macOS
                    continue
                if f.startswith('.'):   # Ignora altri file nascosti
                    continue
                pdf_files.append(os.path.join(root, f))

        pdf_files.sort()  # Ordina i file per avere un ordine prevedibile

        # Process each PDF file
        processed_paths = set()  # Tiene traccia dei file già processati
        for pdf_path in pdf_files:
            # Controlla se è una variante di un file già processato
            base_name = os.path.splitext(os.path.basename(pdf_path))[0]
            base_name = re.sub(r'-\d+$', '', base_name)  # Rimuove suffissi tipo "-1", "-2"

            if base_name in processed_paths:
                self.logger.info(f"Skipping duplicate variant: {pdf_path}")
                continue

            success, metadata, new_path = self.organize_pdf(pdf_path)
            if success and metadata and new_path:
                successful += 1
                processed_files.append((pdf_path, metadata, new_path))
                processed_paths.add(base_name)
            else:
                failed += 1

        self.logger.info(f"Processing completed. Success: {successful}, Failed: {failed}")
        return successful, failed, processed_files

    def extract_text_sample(self, pdf_path: str, max_pages: int = 3) -> str:
        """
        Estrae il testo dal PDF con focus particolare sulla copertina
        """
        try:
            with open(pdf_path, 'rb') as file:
                pdf = PdfReader(file)
                text = []

                # Estrai testo dalla copertina e prime pagine
                for i in range(min(len(pdf.pages), max_pages)):
                    page_text = pdf.pages[i].extract_text()
                    text.append(page_text)

                # Estrai anche il testo dalla copertina in modo specifico
                if len(pdf.pages) > 0:
                    cover = pdf.pages[0].extract_text()
                    # Cerca pattern tipici delle copertine
                    cover_patterns = [
                        r'(?i)authors?[:]\s*(.*)',
                        r'(?i)published[:]\s*(\d{4})',
                        r'(?i)©\s*(\d{4})',
                        r'(?i)volume\s*\d+.*\d{4}',
                        r'(?i)by\s+([^,\n]+)',  # Cattura autori dopo "by"
                        r'(?i)(.*?)\s*-\s*(\d{4})',  # Pattern comune nei titoli accademici
                        r'(?i)([^-]+)\s+-\s+(.+?)\s+\((\d{4})\)',  # Pattern per libri/articoli
                        r'(?i)^\s*([^,\n]+),\s*([^,\n]+)',  # Autore in formato "Cognome, Nome"
                        r'(?i)proceedings\s+of\s+the\s+(.+?)\s+(\d{4})',  # Proceedings
                        r'(?i)technical\s+report\s+(.+?)\s+(\d{4})',  # Report tecnici
                    ]

                    for pattern in cover_patterns:
                        if re.search(pattern, cover):
                            text.insert(0, cover)  # Dai priorità al testo della copertina
                            break

                # Aggiungi il nome del file come ultima risorsa
                text.append(os.path.basename(pdf_path))

                return ' '.join(text)
        except Exception as e:
            self.logger.error(f"Error extracting text from {pdf_path}: {str(e)}")
            return ""

    async def search_metadata(self, text_sample: str) -> Optional[Publication]:
        """
        Cerca i metadati su multiple API in parallelo e valuta i risultati
        """
        apis = [
            self.metadata_fetcher.search_crossref,
            self.metadata_fetcher.search_semantic_scholar,
            self.metadata_fetcher.search_google_books
        ]

        tasks = [api(text_sample) for api in apis]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        best_metadata = None
        best_score = 0.0

        for result in results:
            if isinstance(result, Publication):
                score = self.evaluate_metadata_quality(result)
                if score > best_score:
                    best_score = score
                    best_metadata = result

        return best_metadata

    def evaluate_metadata_quality(self, metadata: Publication) -> float:
        """
        Valuta la qualità dei metadati estratti
        """
        score = 0.0

        if metadata.title and len(metadata.title) > 5:
            score += 0.3

        if metadata.authors:
            if any(',' in author for author in metadata.authors):
                score += 0.3
            else:
                score += 0.2

        if metadata.year and metadata.year.isdigit() and 1900 <= int(metadata.year) <= 2024:
            score += 0.2

        if metadata.doi:
            score += 0.1
        if metadata.publisher:
            score += 0.1

        return score

    def extract_metadata_from_pdf(self, pdf_path: str) -> Optional[Publication]:
        """
        Estrae metadati dal PDF usando varie strategie
        """
        try:
            with open(pdf_path, 'rb') as file:
                pdf = PdfReader(file)
                info = pdf.metadata

                # Estrattore titolo
                title = info.get('/Title', '') if info else ''
                if not title or len(title) < 3:
                    basename = os.path.basename(pdf_path)
                    title = os.path.splitext(basename)[0]
                    # Pulisci il titolo da pattern comuni
                    title = re.sub(r'\(\d{4}\)', '', title)  # Rimuovi anno tra parentesi
                    title = re.sub(r'^\d+[-_]', '', title)   # Rimuovi numeri iniziali
                    title = title.strip()

                # Estrattore autore
                author = info.get('/Author', '') if info else ''
                if not author or author.lower() == 'unknown':
                    # Cerca l'autore nel titolo del file
                    author_patterns = [
                        r'by\s+([^,\n]+)',
                        r'([^-]+)\s*-\s*',
                        r'^([^,]+),\s*([^,]+)'
                    ]
                    for pattern in author_patterns:
                        match = re.search(pattern, title)
                        if match:
                            author = match.group(1)
                            break

                # Estrattore anno
                year = ''
                # Prima cerca nei metadati PDF
                date_fields = ['/CreationDate', '/ModDate'] if info else []
                for field in date_fields:
                    if info.get(field):
                        match = re.search(r'D:(\d{4})', info[field])
                        if match:
                            year = match.group(1)
                            break

                # Se non trovato, cerca nel nome file e titolo
                if not year:
                    year_patterns = [
                        r'\((\d{4})\)',
                        r'[\\_-](\d{4})[\\_-]',
                        r'\b(19|20)\d{2}\b'
                    ]
                    for pattern in year_patterns:
                        match = re.search(pattern, title)
                        if match:
                            year = match.group(1)
                            break
                        match = re.search(pattern, pdf_path)
                        if match:
                            year = match.group(1)
                            break

                if not year:
                    year = "Unknown"

                return Publication(
                    title=title,
                    authors=[author] if author else [],
                    year=year
                )

        except Exception as e:
            self.logger.error(f"Error extracting metadata from {pdf_path}: {str(e)}")
            return None

    def parse_author_name(self, author: str) -> str:
        """
        Migliora la gestione dei nomi autore
        """
        if not author:
            return 'unknown'

        # Rimuovi caratteri speciali
        author = author.lower().strip()
        author = re.sub(r'[^\w\s,.-]', '', author)

        # Se il nome contiene più autori (separati da virgola o 'and')
        if ',' in author:
            author = author.split(',')[0]
        if ' and ' in author:
            author = author.split(' and ')[0]
        if ';' in author:
            author = author.split(';')[0]

        # Se c'è un titolo accademico, rimuovilo
        academic_titles = ['dr', 'dr.', 'prof', 'prof.', 'phd', 'phd.', 'dott', 'dott.']
        for title in academic_titles:
            if author.startswith(title):
                author = author[len(title):].strip()

        # Gestisci il formato "Cognome, Nome"
        if ',' in author:
            parts = author.split(',')
            if len(parts) == 2:
                author = f"{parts[0].strip()}-{parts[1].strip()}"
        else:
            # Gestisci il formato "Nome Cognome"
            parts = author.split()
            if len(parts) > 1:
                author = f"{parts[-1]}-{'-'.join(parts[:-1])}"

        # Pulisci il risultato finale
        author = re.sub(r'[^a-z0-9-]', '-', author)
        author = re.sub(r'-+', '-', author)
        return author.strip('-')

    def clean_title(self, title: str) -> str:
        """
        Migliora la pulizia del titolo mantenendo leggibilità
        """
        if not title:
            return 'unknown'

        # Rimuovi caratteri speciali mantenendo spazi
        title = title.lower().strip()
        title = re.sub(r'[^\w\s-]', ' ', title)

        # Se il titolo è solo numeri, formattalo meglio
        if re.match(r'^\d+$', title.replace(' ', '')):
            # Aggiungi spazi ogni 4 numeri per leggibilità
            title = re.sub(r'(\d{4})', r'\1 ', title).strip()
            return f"doc-{title}"  # Prefisso per documenti numerici

        # Rimuovi stopwords solo se il titolo è abbastanza lungo
        if len(title.split()) > 4:
            stopwords = ['proceedings', 'conference', 'journal', 'international',
                        'workshop', 'symposium', 'volume', 'vol', 'part']
            title_words = [w for w in title.split() if w not in stopwords]
            title = ' '.join(title_words)

        # Rimuovi ripetizioni esatte di parole
        words = title.split()
        unique_words = []
        for word in words:
            if not unique_words or word != unique_words[-1]:
                unique_words.append(word)
        title = ' '.join(unique_words)

        # Tronca mantenendo parole significative
        words = title.split()
        if len(words) > 8:
            # Mantieni prime 4 e ultime 4 parole significative
            title = ' '.join(words[:4] + ['...'] + words[-4:])

        # Converti in formato URL-friendly preservando parole
        title = re.sub(r'[^a-z0-9\s-]', '', title)
        title = re.sub(r'\s+', '-', title.strip())
        title = re.sub(r'-+', '-', title)

        return title.strip('-')

    def create_filename(self, metadata: Publication) -> str:
        """
        Creates filename in the format: YEAR-LASTNAME-FIRSTNAME-TITLE.pdf
        """
        # Clean and truncate title
        title = self.clean_title(metadata.title)

        # Handle author name
        if metadata.authors and metadata.authors[0]:
            author = self.parse_author_name(metadata.authors[0])
        else:
            author = 'unknown'

        # Ensure year is valid
        year = metadata.year if metadata.year and metadata.year.isdigit() else 'Unknown'

        filename = f"{year}-{author}-{title}"
        filename = re.sub(r'-+', '-', filename)
        filename = filename.strip('-')
        return f"{filename}.pdf"

    def create_author_directory(self, metadata: Publication) -> str:
        """
        Creates and returns the path for author directory
        """
        if metadata.authors and metadata.authors[0]:
            author = self.parse_author_name(metadata.authors[0])
        else:
            author = 'unknown'

        author_path = os.path.join(self.output_dir, author)
        os.makedirs(author_path, exist_ok=True)
        return author_path

    def organize_pdf(self, pdf_path: str) -> Tuple[bool, Optional[Publication], Optional[str]]:
        """
        Organizza un singolo PDF estraendo metadati e riorganizzandolo
        """
        self.logger.info(f"Starting processing of: {pdf_path}")
        if not os.path.exists(pdf_path):
            self.logger.error(f"File not found: {pdf_path}")
            return False, None, None

        # 1. Estrai metadati dal PDF locale
        metadata = self.extract_metadata_from_pdf(pdf_path)

        # 2. Se necessario, cerca online
        if not metadata or self.evaluate_metadata_quality(metadata) < 0.5:
            text_sample = self.extract_text_sample(pdf_path)
            try:
                online_metadata = asyncio.run(self.search_metadata(text_sample))
                if online_metadata and (not metadata or
                    self.evaluate_metadata_quality(online_metadata) > self.evaluate_metadata_quality(metadata)):
                    metadata = online_metadata
            except Exception as e:
                self.logger.error(f"Error in online search: {str(e)}")

        if not metadata:
            self.logger.warning(f"Unable to find metadata for {pdf_path}")
            return False, None, None

        try:
            # Crea directory autore e nuovo filename
            author_dir = self.create_author_directory(metadata)
            new_filename = self.create_filename(metadata)
            new_path = os.path.join(author_dir, new_filename)

            # Copia il file
            shutil.copy2(pdf_path, new_path)
            self.logger.info(f"File organized successfully: {new_path}")
            return True, metadata, new_path

        except Exception as e:
            self.logger.error(f"Error moving file {pdf_path}: {str(e)}")
            return False, None, None


def main():
    args = parse_arguments()

    if not os.path.exists(args.input_dir):
        print(f"Input directory not found: {args.input_dir}")
        return

    print(f"Input directory: {args.input_dir}")
    print(f"Output directory: {args.output_dir}")

    pdf_files = []
    for root, _, files in os.walk(args.input_dir):
        for f in files:
            if f.lower().endswith('.pdf'):
                pdf_files.append(os.path.join(root, f))

    print(f"PDF files found in directory: {len(pdf_files)}")
    if pdf_files:
        print("PDF files found:")
        for pdf in pdf_files:
            print(f"- {pdf}")

    organizer = BasePdfOrganizer(args.input_dir, args.output_dir)
    successful, failed, processed = organizer.process_directory()

    print(f"\nSummary:")
    print(f"Successfully processed files: {successful}")
    print(f"Failed files: {failed}")
    print("\nCheck the pdf_organizer.log file for details")

if __name__ == "__main__":
    main()
