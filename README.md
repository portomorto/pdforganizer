# PDF Organizer

A set of Python scripts to organize PDF files and manage their metadata.

## Features

- Organizes PDFs into year-based directories
- Extracts and normalizes filenames
- Generates YAML metadata files for each PDF
- Updates PDF metadata using YAML files
- Handles multiple authors and complex filenames
- Supports metadata extraction from online sources (CrossRef, Semantic Scholar, Google Books)

## Requirements

```bash
pip install PyPDF2 pyyaml requests
```

## Project Structure

```
.
├── log/              # Log files directory
├── mess/             # Input directory for unorganized PDFs
├── organized_pdfs/   # Output directory for organized PDFs
└── src/              # Source code
    ├── pdforg_base.py           # Main PDF organization script
    ├── yaml_generator.py        # YAML metadata generator
    └── pdf_metadata_updater.py  # PDF metadata updater
```

## Usage

### 1. Organize PDFs

The first step is to organize your PDFs. Use `pdforg_base.py` with your input and output directories:

```bash
python3 src/pdforg_base.py --input_dir /path/to/mess --output_dir /path/to/organized_pdfs
```

This will:
- Scan the input directory for PDF files
- Extract metadata from filenames and file contents
- Create a year-based directory structure
- Copy and rename PDFs according to a standardized format
- Generate logs in the `log` directory

### 2. Generate YAML Metadata

After organizing the PDFs, generate YAML metadata files:

```bash
python3 src/yaml_generator.py
```

This will:
- Process all PDFs in the organized_pdfs directory
- Create corresponding YAML files with metadata
- Attempt to fetch additional metadata from online sources
- Generate timestamped logs in the `log` directory

### 3. Update PDF Metadata (Optional)

To update the PDF files with the metadata from YAML files:

```bash
python3 src/pdf_metadata_updater.py
```

## Logging

All scripts generate logs in the `log` directory:
- `pdf_organizer.log`: Main organization process logs
- `yaml_generator_YYYYMMDD_HHMMSS.log`: YAML generation logs
- `pdf_metadata_updater_YYYYMMDD_HHMMSS.log`: Metadata update logs

## Metadata Sources

The scripts attempt to extract metadata in the following order:
1. PDF filename
2. PDF internal metadata
3. Online sources:
   - CrossRef
   - Semantic Scholar
   - Google Books

## Error Handling

- Failed operations are logged but don't stop the process
- Temporary files are cleaned up automatically
- Original files are preserved (copy instead of move)
- Detailed error messages in log files

## Example

Starting with a messy directory:

```
mess/
    (2009) Author - Title.pdf
    Another_Paper_2015.pdf
    ...
```

After organization:

```
organized_pdfs/
    2009/
        2009-author-title.pdf
        2009-author-title.yaml
    2015/
        2015-another-paper.pdf
        2015-another-paper.yaml
    ...
```

## Notes

- Ensure you have write permissions in the output directory
- Keep original files until you verify the organization
- Check log files for any issues or warnings
- Large PDF collections may take time to process
- Internet connection required for online metadata lookup

## Support

For issues or questions:
1. Check the log files for error messages
2. Verify file permissions and paths
3. Ensure all dependencies are installed
4. Make sure you have internet access for online lookups
