# pdforg_base.py
import os
import re
import shutil
import logging
import requests
import time
import asyncio
from typing import Optional, List, Tuple
from dataclasses import dataclass, field
import hashlib
from pdfminer.high_level import extract_text
from pdfminer.pdfparser import PDFParser
from pdfminer.pdfdocument import PDFDocument
import argparse

@dataclass
class Publication:
    title: str
    authors: List[str]
    year: str
    doi: Optional[str] = None
    isbn: Optional[str] = None
    publisher: Optional[str] = None
    abstract: Optional[str] = None
    content_hash: Optional[str] = None

class EnhancedMetadataExtractor:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._setup_patterns()

    def _setup_patterns(self):
        """Configura i pattern di ricerca per i metadati"""
        self.doi_patterns = [
            r'\b(10\.\d{4,}/[-._;()/:\w]+)\b',
            r'DOI:\s*(10\.\d{4,}/[-._;()/:\w]+)'
        ]

        self.author_patterns = [
            r'(?i)authors?[:]\s*(.*?)(?=\n|$)',
            r'(?i)by\s+([^,\n]+(?:,\s*[^,\n]+)*)',
            r'(?i)^\s*([^,\n]+),\s*([^,\n]+)'
        ]

        self.year_patterns = [
            r'(?i)©\s*(\d{4})',
            r'(?i)published[:]\s*(\d{4})',
            r'\((\d{4})\)',
            r'[\\_-](\d{4})[\\_-]'
        ]

    def extract_metadata(self, pdf_path: str) -> Publication:
        """Estrae i metadati da un PDF usando multiple strategie"""
        try:
            # Estrai il testo usando pdfminer
            text = self._extract_text(pdf_path)

            # Estrai i metadati PDF nativi
            pdf_metadata = self._extract_pdf_metadata(pdf_path)

            # Estrai gli autori
            authors = self._extract_authors(text, pdf_metadata)

            # Estrai il titolo
            title = self._extract_title(text, pdf_metadata, pdf_path)

            # Estrai l'anno
            year = self._extract_year(text, pdf_metadata)

            # Estrai DOI
            doi = self._extract_doi(text)

            # Calcola hash del contenuto
            content_hash = self._calculate_content_hash(pdf_path)

            return Publication(
                title=title,
                authors=authors,
                year=year,
                doi=doi,
                publisher=pdf_metadata.get('/Publisher', None),
                content_hash=content_hash
            )

        except Exception as e:
            self.logger.error(f"Errore nell'estrazione dei metadati da {pdf_path}: {str(e)}")
            return Publication(title="Unknown", authors=[], year="Unknown")

    def _extract_text(self, pdf_path: str, max_pages: int = 5) -> str:
        """Estrae il testo dalle prime pagine del PDF"""
        try:
            text = extract_text(pdf_path, maxpages=max_pages)
            return re.sub(r'\s+', ' ', text).strip()
        except Exception as e:
            self.logger.error(f"Errore nell'estrazione del testo: {str(e)}")
            return ""

    def _extract_pdf_metadata(self, pdf_path: str) -> dict:
        """Estrae i metadati nativi del PDF"""
        try:
            with open(pdf_path, 'rb') as file:
                parser = PDFParser(file)
                doc = PDFDocument(parser)
                return doc.info[0] if doc.info else {}
        except Exception as e:
            self.logger.error(f"Errore nell'estrazione dei metadati PDF: {str(e)}")
            return {}

    def _extract_authors(self, text: str, pdf_metadata: dict) -> List[str]:
        """Estrae gli autori da varie fonti"""
        authors = []

        # Prima prova dai metadati PDF
        if '/Author' in pdf_metadata:
            authors = [a.strip() for a in pdf_metadata['/Author'].split(';')]
            if authors and authors[0]:
                return authors

        # Poi cerca nel testo
        for pattern in self.author_patterns:
            match = re.search(pattern, text)
            if match:
                authors = [a.strip() for a in match.group(1).split(';')]
                if authors and authors[0]:
                    return authors

        return ["unknown"]

    def _extract_title(self, text: str, pdf_metadata: dict, pdf_path: str) -> str:
        """Estrae il titolo da varie fonti"""
        # Prima prova dai metadati PDF
        title = pdf_metadata.get('/Title', '').strip()
        if title and len(title) > 3:
            return title

        # Se non trovato, usa il nome del file
        basename = os.path.basename(pdf_path)
        title = os.path.splitext(basename)[0]

        # Pulisci il titolo
        title = re.sub(r'\(\d{4}\)', '', title)  # Rimuovi anno tra parentesi
        title = re.sub(r'^\d+[-_]', '', title)   # Rimuovi numeri iniziali
        return title.strip()

    def _extract_year(self, text: str, metadata: dict) -> str:
        """Estrae l'anno da varie fonti"""
        # Prima cerca nei metadati PDF
        if metadata.get('/CreationDate'):
            match = re.search(r'D:(\d{4})', metadata['/CreationDate'])
            if match:
                return match.group(1)

        # Poi cerca nel testo
        for pattern in self.year_patterns:
            match = re.search(pattern, text)
            if match:
                year = match.group(1)
                if 1900 <= int(year) <= 2024:
                    return year

        return "Unknown"

    def _extract_doi(self, text: str) -> Optional[str]:
        """Estrae il DOI dal testo"""
        for pattern in self.doi_patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return None

    def _calculate_content_hash(self, pdf_path: str) -> str:
        """Calcola un hash del contenuto del PDF"""
        try:
            with open(pdf_path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception as e:
            self.logger.error(f"Errore nel calcolo dell'hash: {str(e)}")
            return ""

class BasePdfOrganizer:
    def __init__(self, input_dir: str, output_dir: str):
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.metadata_extractor = EnhancedMetadataExtractor()
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
        successful = 0
        failed = 0
        processed_files = []

        os.makedirs(self.output_dir, exist_ok=True)

        pdf_files = []
        for root, _, files in os.walk(self.input_dir):
            for f in files:
                if not f.lower().endswith('.pdf'):
                    continue
                if f.startswith('._') or f.startswith('.'):
                    continue
                pdf_files.append(os.path.join(root, f))

        pdf_files.sort()

        processed_paths = set()
        for pdf_path in pdf_files:
            base_name = os.path.splitext(os.path.basename(pdf_path))[0]
            base_name = re.sub(r'-\d+$', '', base_name)

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

    def organize_pdf(self, pdf_path: str) -> Tuple[bool, Optional[Publication], Optional[str]]:
        self.logger.info(f"Processing file: {pdf_path}")

        try:
            # Estrai metadati
            metadata = self.metadata_extractor.extract_metadata(pdf_path)

            # Crea la struttura delle cartelle
            year_dir = os.path.join(self.output_dir, metadata.year)
            os.makedirs(year_dir, exist_ok=True)

            # Crea il nuovo nome file
            clean_title = self._clean_filename(metadata.title)
            author_part = self._clean_filename(metadata.authors[0] if metadata.authors else "unknown")
            new_filename = f"{metadata.year}_{author_part}_{clean_title}.pdf"
            new_path = os.path.join(year_dir, new_filename)

            # Copia il file
            shutil.copy2(pdf_path, new_path)
            self.logger.info(f"File organized: {new_path}")

            return True, metadata, new_path

        except Exception as e:
            self.logger.error(f"Error organizing {pdf_path}: {str(e)}")
            return False, None, None

    def _clean_filename(self, text: str) -> str:
        """Pulisce il testo per uso come nome file"""
        text = text.lower().strip()
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'[-\s]+', '-', text)
        return text[:100]  # Limita la lunghezza

def main():
    parser = argparse.ArgumentParser(description='Organize PDF files.')
    parser.add_argument('--input_dir', required=True, help='Directory containing PDFs to organize')
    parser.add_argument('--output_dir', required=True, help='Directory where to save organized PDFs')
    args = parser.parse_args()

    if not os.path.exists(args.input_dir):
        print(f"Input directory not found: {args.input_dir}")
        return

    organizer = BasePdfOrganizer(args.input_dir, args.output_dir)
    successful, failed, processed = organizer.process_directory()

    print(f"\nSummary:")
    print(f"Successfully processed files: {successful}")
    print(f"Failed files: {failed}")
    print("\nCheck the pdf_organizer.log file for details")

if __name__ == "__main__":
    main()
