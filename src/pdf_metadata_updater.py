# pdf_metadata_updater.py
import os
import yaml
import logging
from datetime import datetime
from PyPDF2 import PdfReader, PdfWriter
from typing import Optional, Dict

class PdfMetadataUpdater:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.setup_logging()

    def setup_logging(self):
        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'log')
        os.makedirs(log_dir, exist_ok=True)
        log_filename = f"pdf_metadata_updater_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
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

    def read_yaml_metadata(self, yaml_path: str) -> Optional[Dict]:
        """Legge i metadati dal file YAML"""
        try:
            with open(yaml_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            self.logger.error(f"Errore nella lettura del file YAML {yaml_path}: {str(e)}")
            return None

    def update_pdf_metadata(self, pdf_path: str, metadata: Dict) -> bool:
        """Aggiorna i metadati del PDF"""
        try:
            # Leggi il PDF esistente
            reader = PdfReader(pdf_path)
            writer = PdfWriter()

            # Copia tutte le pagine
            for page in reader.pages:
                writer.add_page(page)

            # Prepara i metadati nel formato corretto per PyPDF2
            pdf_metadata = {
                '/Title': metadata.get('title', ''),
                '/Author': '; '.join(metadata.get('authors', [])),
                '/Subject': metadata.get('abstract', ''),
                '/Keywords': f"doi:{metadata.get('doi', '')} isbn:{metadata.get('isbn', '')}",
                '/Producer': metadata.get('publisher', ''),
                '/CreationDate': f"D:{metadata.get('year', '')}0101000000",
            }

            # Rimuovi le chiavi con valori vuoti
            pdf_metadata = {k: v for k, v in pdf_metadata.items() if v}

            # Aggiungi i metadati
            writer.add_metadata(pdf_metadata)

            # Crea un file temporaneo
            temp_path = pdf_path + '.temp'

            # Scrivi il nuovo PDF
            with open(temp_path, 'wb') as f:
                writer.write(f)

            # Sostituisci il file originale
            os.replace(temp_path, pdf_path)

            self.logger.info(f"Metadati aggiornati con successo per: {pdf_path}")
            return True

        except Exception as e:
            self.logger.error(f"Errore nell'aggiornamento dei metadati per {pdf_path}: {str(e)}")
            # Rimuovi il file temporaneo se esiste
            if os.path.exists(pdf_path + '.temp'):
                os.remove(pdf_path + '.temp')
            return False

    def process_directory(self) -> tuple[int, int]:
        """
        Processa ricorsivamente la directory e aggiorna i metadati dei PDF
        """
        successful = 0
        failed = 0

        for root, _, files in os.walk(self.base_dir):
            for file in files:
                if file.lower().endswith('.yaml'):
                    yaml_path = os.path.join(root, file)
                    pdf_path = yaml_path[:-5] + '.pdf'  # Sostituisci .yaml con .pdf

                    if not os.path.exists(pdf_path):
                        self.logger.warning(f"PDF non trovato per {yaml_path}")
                        continue

                    metadata = self.read_yaml_metadata(yaml_path)
                    if metadata and self.update_pdf_metadata(pdf_path, metadata):
                        successful += 1
                    else:
                        failed += 1

        return successful, failed

def main():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    organized_dir = os.path.join(current_dir, "organized_pdfs")

    if not os.path.exists(organized_dir):
        print(f"Directory {organized_dir} non trovata!")
        return

    print(f"Aggiornamento metadati PDF nella directory: {organized_dir}")
    updater = PdfMetadataUpdater(organized_dir)
    successful, failed = updater.process_directory()

    print(f"\nRiepilogo:")
    print(f"PDF aggiornati con successo: {successful}")
    print(f"PDF non aggiornati: {failed}")
    print("\nControlla il file di log per i dettagli")

if __name__ == "__main__":
    main()
