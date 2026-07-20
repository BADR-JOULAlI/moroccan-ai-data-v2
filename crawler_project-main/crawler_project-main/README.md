# Crawler Project

A comprehensive web crawling and text extraction pipeline that creates WARC archives from websites and extracts clean text content with deduplication for downstream processing.

## Overview

This project consists of two main processes:

1. **Crawling** - Web crawling using wget to create WARC (Web ARChive) files
2. **Datatrove Extraction** - Multi-stage text extraction pipeline from WARC files using datatrove, Trafilatura, quality filtering, and MinHash deduplication

## Project Structure

```
crawler_project/
├── crawling/              # Web crawling process
│   ├── crawl_script.sh    # Main crawling script
│   ├── file.txt          # Input URLs file
│   ├── crawl_out/        # WARC output directory
│   └── helpers/          # Helper scripts
│       └── get_sitmaps.py # Sitemap discovery helper
├── datatrove_extraction/ # Text extraction process
│   ├── process.py        # Main extraction script
│   ├── input/            # WARC input directory
│   ├── output/           # Extracted text output
│   │   ├── data/         # Processed JSONL files
│   │   ├── rejected/     # Filtered out content
│   │   └── log/          # Processing logs
│   └── helpers/          # Helper modules
│       ├── filters/      # Custom quality filters
│       └── extra_helpers/ # Validation and utilities
├── crawled_dataset/       # Final processed dataset storage
├── models_cache/          # Cached models (tokenizers, language IDs)
├── explanation/           # Documentation and analysis
├── main.py                # Project entry point
└── pyproject.toml         # Project dependencies
```

## Prerequisites

- **Python 3.11** or higher
- `wget` (with WARC support)
- `uv` package manager

## Installation

Install all project dependencies using `uv`:

```bash
uv sync
```

This will install all required packages listed in `pyproject.toml`, including:
- `datatrove[all]` - Text extraction pipeline
- `trafilatura` - Web content extraction
- `warcio` - WARC file handling
- `transformers` - Tokenizer support
- `fasttext` - Language identification

## Workflow

### 1. Crawling Process

The crawling process uses wget to recursively crawl websites and create WARC archive files. See the [crawling README](crawling/README.md) for detailed instructions.

**Quick Start:**
```bash
cd crawling
# 1. Put origin URL in file.txt, or use collector-approved URLs
echo "https://www.example.com/" > file.txt

# 2. Optional: discover and add sitemaps automatically
uv run helpers/append_sitemaps.py

# 3. Run the crawler
./crawl_script_batched.sh file.txt <prefix>
```

With the Moroccan sources collector validation flow:

```bash
cd moroccan_sources_collector
uv run python -m src.main export-crawler-input

cd ../crawler_project-main/crawler_project-main/crawling
./crawl_script_batched.sh ../../../moroccan_sources_collector/data/output/crawler_urls.txt moroccan_validated_sources
```

Output: WARC files in `crawling/crawl_out/<prefix>/<prefix>/`

### 2. Datatrove Extraction Process

The extraction process is a 5-stage pipeline that reads WARC files, extracts clean text content using Trafilatura, applies quality filters, and performs MinHash-based deduplication. See the [datatrove_extraction README](datatrove_extraction/README.md) for detailed instructions.

**Quick Start:**
```bash
cd datatrove_extraction
# Place WARC files in input/segment-2026-01/ directory (organized by website folders)
uv run process.py

# Optional: process another segment
uv run process.py --segment segment-2026-07

# Optional: Validate WARC files before processing
uv run process.py --validate-warc

# Optional: Validate and auto-repair invalid WARC files
uv run process.py --validate-warc --auto-repair
```

Output: Deduplicated JSONL files in `datatrove_extraction/output/minhash/segment-2026-01/final_data/`

### 3. Crawled Dataset

The final processed dataset is stored in the `crawled_dataset/` directory.

## Getting Help

- For crawling-specific questions, see [crawling/README.md](crawling/README.md)
- For extraction-specific questions, see [datatrove_extraction/README.md](datatrove_extraction/README.md)

## Notes

- The crawler stays on the same host as seed URLs (no cross-site crawling)
- Common crawler traps (login pages, admin areas, etc.) are automatically filtered out
- The crawler is polite by default, with delays between requests
- PDF files are allowed (not filtered out)
- Text extraction uses Trafilatura with precision-focused settings
- The extraction pipeline includes 5 stages: filtering, MinHash signature computation, bucketing, clustering, and deduplication
- Quality filters include Arabic normalization, Gopher repetition/quality, and C4 quality filters
- MinHash deduplication removes duplicate content across the entire dataset
- Processing is organized by segments (e.g., `segment-2026-01`)

Happy crawling! 🕷️
