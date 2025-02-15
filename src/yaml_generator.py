# yaml_generator.py
import os
import yaml
import logging
import asyncio
from datetime import datetime
from pdforg_base import BasePdfOrganizer, Publication, MetadataFetcher, PdfReader

class YAMLGenerator:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.metadata_fetcher = MetadataFetcher()
        self.setup_logging()

    def setup_logging(self):
        """Configura il logging"""
        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'log')
        os.makedirs(log_dir, exist_ok=True)
        log_filename = f"yaml_generator_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        log_path = os.path.join(log_dir, log_filename)

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
        """Estrae un campione di testo dal PDF per la ricerca"""
        try:
            with open(pdf_path, 'rb') as file:
                pdf = PdfReader(file)
                text = []
                for i in range(min(len(pdf.pages), max_pages)):
                    try:
                        page_text = pdf.pages[i].extract_text()
                        if page_text and len(page_text.strip()) > 0:
                            text.append(page_text)
                    except Exception as page_error:
                        self.logger.warning(f"Errore nell'estrazione del testo dalla pagina {i}: {str(page_error)}")
                        continue
                return ' '.join(text) if text else ""
        except Exception as e:
            self.logger.error(f"Errore nell'estrazione del testo da {pdf_path}: {str(e)}")
            return ""

    async def get_metadata(self, pdf_path: str) -> Publication:
        """
        Cerca di ottenere i metadati nel modo più completo possibile
        """
        # Prima prova a estrarre i metadati dal PDF
        try:
            with open(pdf_path, 'rb') as file:
                pdf = PdfReader(file)
                info = pdf.metadata
                if info:
                    title = info.get('/Title', '')
                    author = info.get('/Author', '')
                    if title and author:
                        return Publication(
                            title=title,
                            authors=[author] if author else [],
                            year=os.path.basename(os.path.dirname(pdf_path))  # l'anno dalla directory
                        )
        except Exception as e:
            self.logger.error(f"Errore nella lettura dei metadati PDF: {str(e)}")

        # Se non trova metadati nel PDF, prova la ricerca online
        text_sample = self.extract_text_sample(pdf_path)
        try:
            # Prova ogni servizio di ricerca
            for service in [
                self.metadata_fetcher.search_crossref,
                self.metadata_fetcher.search_semantic_scholar,
                self.metadata_fetcher.search_google_books
            ]:
                result = await service(text_sample)
                if result:
                    return result
        except Exception as e:
            self.logger.error(f"Errore nella ricerca online: {str(e)}")

        # Come fallback, usa i metadati dal nome file
        filename = os.path.basename(pdf_path)
        year = os.path.basename(os.path.dirname(pdf_path))
        title = filename[len(year)+1:-4]  # rimuove anno- all'inizio e .pdf alla fine

        # Estrai l'autore se presente
        parts = title.split('-')
        if len(parts) > 1:
            author = parts[0]
            title = '-'.join(parts[1:])
        else:
            author = "Unknown"

        return Publication(
            title=title.replace('-', ' ').strip(),
            authors=[author.replace('-', ' ').strip()],
            year=year
        )

    async def generate_yaml(self, pdf_path: str) -> bool:
        """Genera il file YAML per un singolo PDF"""
        try:
            metadata = await self.get_metadata(pdf_path)
            if metadata:
                yaml_path = pdf_path.rsplit('.', 1)[0] + '.yaml'
                with open(yaml_path, 'w', encoding='utf-8') as f:
                    yaml.dump(
                        {
                            'title': metadata.title,
                            'authors': metadata.authors,
                            'year': metadata.year,
                            'doi': metadata.doi,
                            'isbn': metadata.isbn,
                            'publisher': metadata.publisher,
                            'abstract': metadata.abstract
                        },
                        f,
                        allow_unicode=True,
                        sort_keys=False,
                        default_flow_style=False
                    )
                self.logger.info(f"Generato YAML per: {pdf_path}")
                return True
        except Exception as e:
            self.logger.error(f"Errore nella generazione YAML per {pdf_path}: {str(e)}")
        return False

    async def process_directory(self) -> tuple[int, int]:
        """
        Processa ricorsivamente la directory organized_pdfs e genera file YAML
        """
        successful = 0
        failed = 0

        for root, _, files in os.walk(self.base_dir):
            for file in files:
                if file.lower().endswith('.pdf'):
                    pdf_path = os.path.join(root, file)
                    if await self.generate_yaml(pdf_path):
                        successful += 1
                    else:
                        failed += 1

        return successful, failed

async def main():
    # Cerca la directory organized_pdfs nella directory corrente
    current_dir = os.path.dirname(os.path.abspath(__file__))
    organized_dir = os.path.join(current_dir, "../organized_pdfs")

    if not os.path.exists(organized_dir):
        print(f"Directory {organized_dir} non trovata!")
        return

    print(f"Elaborazione della directory: {organized_dir}")
    generator = YAMLGenerator(organized_dir)
    successful, failed = await generator.process_directory()

    print(f"\nRiepilogo:")
    print(f"File YAML generati con successo: {successful}")
    print(f"File YAML non generati: {failed}")
    print("\nControlla il file di log per i dettagli")

if __name__ == "__main__":
    asyncio.run(main())
