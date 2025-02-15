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
    parser = argparse.ArgumentParser(description='Organizza file PDF.')
    parser.add_argument('--input_dir', required=True, help='Directory contenente i PDF da organizzare')
    parser.add_argument('--output_dir', required=True, help='Directory dove salvare i PDF organizzati')
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
            logging.error(f"Errore nella ricerca Crossref: {str(e)}")
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
            logging.error(f"Errore nella ricerca Semantic Scholar: {str(e)}")
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
            logging.error(f"Errore nella ricerca Google Books: {str(e)}")
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

    def extract_text_sample(self, pdf_path: str, max_pages: int = 3) -> str:
        try:
            with open(pdf_path, 'rb') as file:
                pdf = PdfReader(file)
                text = []
                for i in range(min(len(pdf.pages), max_pages)):
                    text.append(pdf.pages[i].extract_text())
                return ' '.join(text)
        except Exception as e:
            self.logger.error(f"Errore nell'estrazione del testo da {pdf_path}: {str(e)}")
            return ""

    async def search_online(self, text_sample: str) -> Optional[Publication]:
        for service in [self.metadata_fetcher.search_crossref,
                       self.metadata_fetcher.search_semantic_scholar,
                       self.metadata_fetcher.search_google_books]:
            result = await service(text_sample)
            if result:
                return result
        return None

    def extract_metadata_from_filename(self, filename: str) -> Optional[Publication]:
        self.logger.info(f"Tentativo di estrazione metadati da filename: {filename}")

        patterns = [
            (r'\(([^)]+)\)\s*([^-]+)-\s*([^-]+)-([^\(]+)\((\d{4})\)',
             lambda m: {'title': m.group(3), 'author': m.group(2), 'year': m.group(5)}),
            (r'([^-]+)-\s*([^-]+)-([^\(]+)\((\d{4})\)',
             lambda m: {'title': m.group(2), 'author': m.group(1), 'year': m.group(4)}),
            (r'([^-]+)-\s*([^\(]+)\((\d{4})\)',
             lambda m: {'title': m.group(2), 'author': m.group(1), 'year': m.group(3)}),
            (r'([^-]+)\.\s*-\s*([^\[]+)\s*\[ocr\]\s*\[(\d{4})\]',
             lambda m: {'title': m.group(2), 'author': m.group(1), 'year': m.group(3)}),
            (r'(.+)_traduz_([^_]+)',
             lambda m: {'title': m.group(1), 'author': m.group(2), 'year': ''}),
        ]

        basename = os.path.basename(filename)

        for pattern, extractor in patterns:
            match = re.search(pattern, basename, re.IGNORECASE)
            if match:
                try:
                    data = extractor(match)
                    for key in data:
                        if isinstance(data[key], str):
                            data[key] = data[key].strip()

                    if not data.get('year'):
                        year_match = re.search(r'\((\d{4})\)', basename)
                        if year_match:
                            data['year'] = year_match.group(1)
                        else:
                            data['year'] = 'Unknown'

                    pub = Publication(
                        title=data['title'],
                        authors=[data['author']],
                        year=data['year'],
                        doi=None,
                        isbn=None,
                        publisher=None,
                        abstract=None
                    )
                    self.logger.info(f"Metadati estratti dal filename: {pub}")
                    return pub
                except Exception as e:
                    self.logger.error(f"Errore nell'estrazione dei metadati: {str(e)}")
                    continue
        return None

    def extract_metadata_from_pdf(self, pdf_path: str) -> Optional[Publication]:
        try:
            with open(pdf_path, 'rb') as file:
                pdf = PdfReader(file)
                info = pdf.metadata

                if info is None:
                    return None

                title = info.get('/Title', '')
                if not title:
                    title = os.path.basename(pdf_path).rsplit('.', 1)[0]

                author = info.get('/Author', 'Unknown')
                year = ''

                date_fields = ['/CreationDate', '/ModDate']
                for field in date_fields:
                    if info.get(field):
                        match = re.search(r'D:(\d{4})', info[field])
                        if match:
                            year = match.group(1)
                            break

                if not year:
                    year_match = re.search(r'\((\d{4})\)', os.path.basename(pdf_path))
                    if year_match:
                        year = year_match.group(1)
                    else:
                        year = "Unknown"

                return Publication(
                    title=title,
                    authors=[author] if author else [],
                    year=year
                )

        except Exception as e:
            self.logger.error(f"Errore nell'estrazione dei metadati da {pdf_path}: {str(e)}")
            return None

    def create_filename(self, metadata: Publication) -> str:
        title = metadata.title.strip()[:100].lower()
        author = (metadata.authors[0] if metadata.authors else 'Unknown').lower()
        filename = f"{metadata.year}-{author}-{title}"
        filename = re.sub(r'[^a-z0-9-]', '-', filename)
        filename = re.sub(r'-+', '-', filename)
        filename = filename.strip('-')
        filename = f"{filename}.pdf"

        self.logger.info(f"Nome file creato: {filename}")
        return filename

    def organize_pdf(self, pdf_path: str) -> Tuple[bool, Optional[Publication], Optional[str]]:
        """
        Organizza un singolo PDF e restituisce (successo, metadati, nuovo_percorso)
        """
        self.logger.info(f"Iniziando elaborazione di: {pdf_path}")
        if not os.path.exists(pdf_path):
            self.logger.error(f"File non trovato: {pdf_path}")
            return False, None, None

        # Estrazione metadati
        metadata = self.extract_metadata_from_filename(pdf_path)
        if not metadata:
            metadata = self.extract_metadata_from_pdf(pdf_path)
        if not metadata:
            text_sample = self.extract_text_sample(pdf_path)
            try:
                metadata = asyncio.run(self.search_online(text_sample))
            except Exception as e:
                self.logger.error(f"Errore nella ricerca online: {str(e)}")
                metadata = None

        if not metadata:
            self.logger.warning(f"Impossibile trovare metadati per {pdf_path}")
            return False, None, None

        # Organizzazione file
        new_filename = self.create_filename(metadata)
        year_dir = os.path.join(self.output_dir, metadata.year)
        os.makedirs(year_dir, exist_ok=True)
        new_path = os.path.join(year_dir, new_filename)

        try:
            shutil.copy2(pdf_path, new_path)
            self.logger.info(f"File organizzato con successo: {new_filename}")
            return True, metadata, new_path
        except Exception as e:
            self.logger.error(f"Errore nello spostamento del file {pdf_path}: {str(e)}")
            return False, None, None

    def process_directory(self) -> Tuple[int, int, list[Tuple[str, Publication, str]]]:
        """
        Elabora tutti i PDF nella directory
        """
        successful = 0
        failed = 0
        processed_files = []

        os.makedirs(self.output_dir, exist_ok=True)
        pdf_files = [f for f in os.listdir(self.input_dir) if f.lower().endswith('.pdf')]

        for pdf_file in pdf_files:
            success, metadata, new_path = self.organize_pdf(
                os.path.join(self.input_dir, pdf_file))
            if success and metadata and new_path:
                successful += 1
                processed_files.append((pdf_file, metadata, new_path))
            else:
                failed += 1

        self.logger.info(f"Elaborazione completata. Successo: {successful}, Falliti: {failed}")
        return successful, failed, processed_files

def main():
    args = parse_arguments()

    if not os.path.exists(args.input_dir):
        print(f"Directory di input non trovata: {args.input_dir}")
        return

    print(f"Directory di input: {args.input_dir}")
    print(f"Directory di output: {args.output_dir}")

    pdf_files = []
    for root, _, files in os.walk(args.input_dir):
        for f in files:
            if f.lower().endswith('.pdf'):
                pdf_files.append(os.path.join(root, f))

    print(f"PDF trovati nella directory: {len(pdf_files)}")
    if pdf_files:
        print("File PDF trovati:")
        for pdf in pdf_files:
            print(f"- {pdf}")

    organizer = BasePdfOrganizer(args.input_dir, args.output_dir)
    successful, failed, processed = organizer.process_directory()

    print(f"\nRiepilogo:")
    print(f"File elaborati con successo: {successful}")
    print(f"File non elaborati: {failed}")
    print("\nControlla il file pdf_organizer.log per i dettagli")

if __name__ == "__main__":
    main()
