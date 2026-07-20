# Datatrove Extraction Process

This process extracts clean text content from WARC (Web ARChive) files using a 5-stage pipeline with datatrove, Trafilatura, quality filtering, and MinHash-based deduplication. It processes WARC archives created by the crawling process and outputs deduplicated structured JSONL files with extracted text.

## Overview

The extraction pipeline consists of 5 stages:

**Stage 1: Initial Processing and Filtering**
1. Reads WARC files from the `input/segment-2026-01/` directory (organized by website folders)
2. Extracts text content using Trafilatura (precision-focused)
3. Applies multiple quality filters in sequence:
   - ArabicNormalizationFilter - Normalizes Arabic text
   - GopherRepetitionFilter - Filters repetitive content (configured for Moroccan Arabic)
   - GopherQualityFilter - Quality filtering based on Gopher criteria
   - C4QualityFilter - Quality filtering based on C4 dataset criteria
   - FineWebQualityFilter - Currently commented out (optional)
4. Outputs filtered JSONL files to `output/base_processing/output/segment-2026-01/`

**Stage 2: MinHash Signature Computation**
- Computes MinHash signatures for all documents to enable deduplication
- Uses SHA1 hashing with 64-bit precision, 14 buckets, 8 hashes per bucket, and 5-grams
- Outputs signatures to `output/minhash/segment-2026-01/signatures/`

**Stage 3: Bucket Creation**
- Creates buckets from MinHash signatures for efficient duplicate detection
- Outputs buckets to `output/minhash/segment-2026-01/buckets/`

**Stage 4: Duplicate Clustering**
- Clusters duplicate documents based on MinHash similarity
- Outputs duplicate IDs to `output/minhash/segment-2026-01/remove_ids/`

**Stage 5: Deduplication and Final Output**
- Filters out duplicate documents using the cluster information
- Counts tokens using Arabic GPT-2 tokenizer (before and after deduplication)
- Outputs final deduplicated JSONL files to `output/minhash/segment-2026-01/final_data/`

## Prerequisites

- Python 3.11 or higher
- All dependencies installed via `uv sync` (from project root)

## Getting Started

### 1. Prepare WARC Files

Place your WARC files (`.warc.gz`) in the `input/segment-2026-01/` directory, organized by website folders:

```bash
cd datatrove_extraction
# Create segment directory structure
mkdir -p input/segment-2026-01

# Copy WARC files from crawling output, maintaining folder structure
# Each website should have its own folder
cp -r ../crawling/crawl_out/<prefix>/<prefix> input/segment-2026-01/<website_name>/
```

The script will automatically process all `.warc.gz` files in the `input/segment-2026-01/` directory and its subdirectories using the glob pattern `*/*.warc.gz`.

### 2. Run the Extraction

Run the extraction process:

```bash
cd datatrove_extraction
uv run process.py
```

**Optional: Validate WARC files before processing:**
```bash
# Validate WARC files (reports issues, doesn't repair)
uv run process.py --validate-warc

# Validate and automatically repair invalid WARC files
uv run process.py --validate-warc --auto-repair
```

The process will execute 5 stages:
- **Stage 1**: Read WARC files, extract text using Trafilatura, apply quality filters
- **Stage 2**: Compute MinHash signatures for deduplication
- **Stage 3**: Create buckets from signatures
- **Stage 4**: Cluster duplicate documents
- **Stage 5**: Filter duplicates, count tokens, write final output

Results are written to:
- Filtered output: `output/base_processing/output/segment-2026-01/` (after Stage 1)
- Rejected items: `output/base_processing/removed/<filter_name>/segment-2026-01/` (organized by filter type)
- Final deduplicated output: `output/minhash/segment-2026-01/final_data/` (after Stage 5)

## Output Structure

After running the extraction, you'll find:

```
output/
├── base_processing/           # Stage 1 output
│   ├── output/
│   │   └── segment-2026-01/   # Filtered JSONL files (one per WARC)
│   └── removed/               # Rejected content organized by filter type
│       ├── 1_arabic_norm/
│       │   └── segment-2026-01/
│       ├── 2_gopher_rep/
│       │   └── segment-2026-01/
│       ├── 3_gopher_qual/
│       │   └── segment-2026-01/
│       └── 4_c4_qual/
│           └── segment-2026-01/
├── minhash/                   # Stages 2-5 output
│   └── segment-2026-01/
│       ├── signatures/        # Stage 2: MinHash signatures
│       ├── buckets/           # Stage 3: Buckets
│       ├── remove_ids/        # Stage 4: Duplicate IDs to remove
│       └── final_data/        # Stage 5: Final deduplicated JSONL files
└── logs/                      # Processing logs and statistics
    ├── base_processing/       # Stage 1 logs
    │   └── segment-2026-01/
    └── minhash/               # Stages 2-5 logs
        ├── signatures/
        ├── buckets/
        ├── clustering/
        └── filtering/
```

## Configuration

The extraction process can be customized by editing `process.py`:

### Key Settings

- **Segment**: Currently set to `segment-2026-01` (can be changed in `process.py`)
- **Trafilatura**: Uses `favour_precision=True` for high-quality extraction
- **Filters Applied** (in order, Stage 1):
  1. ArabicNormalizationFilter - Normalizes Arabic text
  2. GopherRepetitionFilter - Filters repetitive content (configured for Moroccan Arabic)
  3. GopherQualityFilter - Quality filtering based on Gopher criteria
  4. C4QualityFilter - Quality filtering based on C4 dataset criteria
  5. FineWebQualityFilter - Currently commented out (optional)
- **MinHash Deduplication**:
  - Hash function: SHA1
  - Precision: 64 bits
  - Buckets: 14
  - Hashes per bucket: 8
  - N-grams: 5
- **TokensCounter**: Uses Arabic GPT-2 tokenizer from `models_cache/aragpt2_base_tokenizer/tokenizer.json`
- **Parallelism**: 
  - Tasks: Automatically set to number of website folders in input directory
  - Workers: Automatically set to `CPU_COUNT - 1` (or 1 if single core)

### Customizing the Pipeline

You can modify `process.py` to:
- Change the segment name (`SEGMENT_TO_PROCESS`)
- Change extraction settings (e.g., `favour_precision=False` for speed)
- Adjust filtering parameters
- Enable FineWebQualityFilter (uncomment line 87-89)
- Add additional filters or processors
- Change MinHash configuration (buckets, hashes, n-grams)
- Modify parallelism settings (tasks/workers)
- Change output paths

### WARC Validation

The pipeline includes optional WARC file validation:
- `--validate-warc`: Validates WARC file integrity before processing
- `--auto-repair`: Automatically repairs invalid WARC files (requires `--validate-warc`)
- Validation creates backups before repairing files
- Invalid files are reported with detailed error messages

## Output Format

Each JSONL file (compressed as `.jsonl.gz`) contains one JSON object per line, with extracted text and metadata:

```json
{
  "id": "unique_document_id",
  "text": "Extracted clean text content...",
  "url": "https://example.com/page",
  "metadata": {
    "title": "Page Title",
    "author": "Author Name",
    "date": "2024-01-01",
    ...
  },
  "tokenizer_name_or_path": "path/to/tokenizer",
  "tokens": 1234
}
```

Note: Output files are compressed with gzip (`.jsonl.gz` format).

## Processing Details

### Stage 1: Text Extraction and Filtering

**Trafilatura Extractor:**
- **Mode**: Precision-focused (`favour_precision=True`)
- Extracts main content, title, author, date, and other metadata
- Handles various HTML structures and content types
- Removes navigation, headers, footers, and other boilerplate
- Timeout: 30 seconds per page

**Quality Filters (applied in sequence):**
1. **ArabicNormalizationFilter**: Normalizes Arabic text content
2. **GopherRepetitionFilter**: Detects and filters repetitive content (configured for Moroccan Arabic language)
3. **GopherQualityFilter**: Applies quality criteria from the Gopher dataset
4. **C4QualityFilter**: Applies quality criteria from the C4 dataset
5. **FineWebQualityFilter**: Currently commented out (optional, can be enabled)

Rejected items from each filter are saved separately in `output/base_processing/removed/<filter_name>/segment-2026-01/` for review and analysis.

### Stages 2-4: MinHash Deduplication

**MinHash Configuration:**
- Hash function: SHA1
- Precision: 64 bits
- Number of buckets: 14
- Hashes per bucket: 8
- N-gram size: 5

**Process:**
1. **Stage 2**: Computes MinHash signatures for all documents
2. **Stage 3**: Creates buckets from signatures for efficient duplicate detection
3. **Stage 4**: Clusters duplicate documents based on MinHash similarity

### Stage 5: Final Deduplication and Token Counting

**TokensCounter:**
- Uses Arabic GPT-2 tokenizer from `models_cache/aragpt2_base_tokenizer/tokenizer.json`
- Counts tokens before and after deduplication
- Token counts are included in the output JSONL files

**Deduplication:**
- Filters out duplicate documents identified in Stage 4
- Only unique documents are included in the final output

## Troubleshooting

**Issue**: No WARC files found
- Ensure WARC files are in the `input/segment-2026-01/` directory
- Check that files are organized in subdirectories (one folder per website)
- Verify file extensions are `.warc.gz`
- Check the segment name matches `SEGMENT_TO_PROCESS` in `process.py`

**Issue**: Invalid WARC files
- Run with `--validate-warc` to check file integrity
- Use `--validate-warc --auto-repair` to automatically repair files
- Check logs for specific error messages
- Backups are created before repair attempts

**Issue**: Memory errors
- The pipeline automatically sets workers to `CPU_COUNT - 1`
- Process WARC files in smaller batches by organizing them into separate segments
- Increase system memory if possible
- Reduce parallelism by manually setting `number_of_workers` in `process.py`

**Issue**: Empty output files
- Check that WARC files contain valid web content
- Verify Trafilatura can extract content from the pages
- Review logs in the `output/logs/` directory
- Check rejected items in `output/base_processing/removed/` to see what was filtered

**Issue**: Too many rejected items
- Review files in `output/base_processing/removed/` to understand filtering
- Check which filter is rejecting most content (each filter has its own subdirectory)
- Adjust filter parameters in `process.py` if needed
- Some websites may have high repetition rates or low quality content

**Issue**: Deduplication taking too long
- MinHash deduplication is computationally intensive
- Processing time depends on the number of documents and system resources
- Check logs in `output/logs/minhash/` for progress information

## Logs

The extraction process creates logs in the `output/logs/` directory:

**Stage 1 logs** (`output/logs/base_processing/segment-2026-01/`):
- Task-specific logs with processing progress
- Statistics about extracted content per task
- Completion markers for each task

**Stages 2-5 logs** (`output/logs/minhash/`):
- `signatures/` - MinHash signature computation logs
- `buckets/` - Bucket creation logs
- `clustering/` - Duplicate clustering logs
- `filtering/` - Final deduplication and filtering logs

Each stage also generates:
- `executor.json` - Executor configuration and status
- `stats.json` - Overall statistics

## Integration with Crawling Process

This extraction process is designed to work with WARC files created by the crawling process:

1. **Crawling** → Creates WARC files in `crawling/crawl_out/<prefix>/<prefix>/`
2. **Extraction** → Processes WARC files from `input/segment-2026-01/` directory (organized by website folders)
3. **Dataset** → Final deduplicated output in `output/minhash/segment-2026-01/final_data/` (can be moved to `crawled_dataset/`)

**Recommended workflow:**
```bash
# 1. Crawl websites
cd crawling
./crawl_script.sh file.txt website_name

# 2. Organize WARC files for extraction
cd ../datatrove_extraction
mkdir -p input/segment-2026-01
cp -r ../crawling/crawl_out/website_name/website_name input/segment-2026-01/website_name

# 3. Run extraction pipeline
uv run process.py --validate-warc --auto-repair

# 4. Final dataset is in output/minhash/segment-2026-01/final_data/
```

## Notes

- The extraction process is CPU-intensive, especially with large WARC files and MinHash deduplication
- Processing time depends on WARC file size, content complexity, and number of documents
- Trafilatura's precision mode prioritizes quality over speed
- MinHash deduplication requires significant computational resources for large datasets
- The pipeline automatically scales parallelism based on available CPU cores
- Rejected items are preserved for review and analysis in `output/base_processing/removed/`
- Processing is organized by segments to allow batch processing of multiple website collections
- The segment name (`segment-2026-01`) can be changed in `process.py` to process different batches
