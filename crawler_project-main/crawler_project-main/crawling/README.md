# Crawling Process

This process creates WARC (Web ARChive) files from websites using wget recursion. Perfect for archiving and analyzing web content.

## Overview

The crawling script uses `wget` to recursively crawl websites and generate compressed WARC archive files. WARC files preserve the complete HTTP request/response data, making them ideal for downstream text extraction and analysis.

## Prerequisites

- `wget` with WARC support
- Bash shell

## Getting Started

### 1. Prepare Your Input File

Start by creating `file.txt` with just the origin website URL (the main website you want to crawl):

Example `file.txt`:
```
https://www.example.com/
```

**Important:** Only put the origin URL on the first line. The sitemaps will be added automatically in the next step.

### 2. Discover and Add Sitemaps Automatically

Run the helper script to automatically discover and add all sitemap URLs:

```bash
cd crawling
uv run helpers/get_sitmaps.py
```

This script will:
- Read the origin URL from the first line of `file.txt`
- Discover all sitemaps for that domain
- Automatically append them to `file.txt` after the origin URL

After running the script, your `file.txt` will look like:
```
https://www.example.com/
https://www.example.com/sitemap.xml
https://www.example.com/sitemap-posts.xml
https://www.example.com/sitemap-pages.xml
```

**Format Rules:**
- Each URL should be on its own line
- Blank lines are ignored
- Lines starting with `#` are treated as comments
- The first URL must be the main website origin URL

### 3. Run the Crawler

Run the crawl script from the `crawling` directory:

```bash
cd crawling
./crawl_script_batched.sh file.txt <prefix>
```

Replace `<prefix>` with a descriptive tag for the website (e.g., `example_com`). This prefix is used to organize output files and logs.

If you are using the Moroccan sources collector, first validate links in
`moroccan_sources_collector/data/output/liens_a_valider_manuellement.csv`, then generate crawler input:

```bash
cd ../../moroccan_sources_collector
uv run python -m src.main export-crawler-input
```

Then run the crawler with accepted URLs only:

```bash
cd ../crawler_project-main/crawler_project-main/crawling
./crawl_script_batched.sh ../../../moroccan_sources_collector/data/output/crawler_urls.txt moroccan_validated_sources
```

**Default Settings:**
- **Depth**: 5 (crawls 5 levels deep from the seed URLs)
- **Robots**: on (respects robots.txt files)
- **Wait**: 1 second between requests (with random jitter)
- **Quota**: unlimited
- **PDF files**: Allowed (not filtered out)

The crawler will create WARC files in `crawl_out/<prefix>/<prefix>/` directory.

### 4. Customize Parameters (Optional)

You can customize the crawling behavior using environment variables:

```bash
DEPTH=6 ROBOTS=on WAIT_SECS=2 QUOTA=5G ./crawl_script_batched.sh file.txt <prefix>
DRY_RUN=1 ./crawl_script_batched.sh file.txt <prefix>
```

**Available Parameters:**
- `DEPTH`: Recursion depth (default: 5)
- `ROBOTS`: Respect robots.txt - use `on` or `off` (default: on)
- `WAIT_SECS`: Delay between requests in seconds (default: 1)
- `RANDOM_WAIT`: Add jitter to wait times - use `0` or `1` (default: 1)
- `TIMEOUT_SECS`: Network timeout per request (default: 30)
- `TRIES`: Retry attempts per URL (default: 3)
- `MAX_REDIRECT`: Max redirects to follow (default: 10)
- `QUOTA`: Download limit, e.g., `5G`, `500M` (default: 0 = unlimited)
- `WARC_MAX_SIZE`: Rotate WARC chunks at this size (default: 1G)
- `UA`: Custom User-Agent string (default: Wget-WARC/1.0 (project: warc-crawl))
- `REJECT_REGEX`: Custom regex pattern for URLs to exclude (default: common crawler traps)
- `DELETE_AFTER`: Delete downloaded mirror files after WARC creation - use `0` or `1` (default: 1)
- `KEEP_TEMPDIR`: Keep temporary WARC assembly directory - use `0` or `1` (default: 0)
- `LOGFILE`: Custom path for wget logs
- `REJECTED_LOG`: Custom path for rejected URLs log
- `FAILED_URLS`: Custom path for failed URLs log
- `DRY_RUN`: Print planned crawl settings without running wget - use `0` or `1` (default: 0)

## Helper Tools

### Manual Sitemap Addition (Optional)

If you prefer to manually add sitemap URLs instead of using the automatic discovery, you can edit `file.txt` directly and add sitemap URLs one per line after the origin URL.

## Output Structure

After running the crawler, you'll find:

```
crawl_out/
└── <prefix>/
    ├── <prefix>/
    │   └── <prefix>-*.warc.gz    # Main WARC files
    ├── logs/
    │   ├── <prefix>.log              # Crawl log
    │   └── <prefix>.rejected.log     # Rejected URLs
    └── _meta/                        # Metadata WARC files
```

## Verifying Your Crawl

You can verify and explore the WARC files using [ReplayWeb.page](https://replayweb.page/):

1. Go to https://replayweb.page/
2. Upload your WARC file(s) from the `crawl_out/<prefix>/<prefix>/` directory
3. Browse the archived website as it was captured during the crawl

This is a great way to ensure everything worked correctly and preview what was captured!

## Features

- **Host-bound crawling**: Stays on the same host as seed URLs (no cross-site crawling)
- **Crawler trap filtering**: Automatically filters out common traps (login pages, admin areas, etc.)
- **PDF support**: PDF files are allowed and will be included in the crawl
- **Polite crawling**: Default delays between requests with random jitter to avoid overwhelming servers
- **WARC rotation**: Automatically splits large archives into manageable chunks (default: 1G per chunk)
- **Automatic cleanup**: Temporary files are cleaned up after crawling completes (unless `KEEP_TEMPDIR=1`)
- **Comprehensive logging**: Detailed logs and rejected URL tracking
- **Metadata organization**: Metadata WARC files are automatically moved to `_meta/` subdirectory
- **Flexible input**: Supports both single URLs and seed files with multiple URLs

## Notes

- The crawler uses `--delete-after` by default, so downloaded mirror files are removed after WARC creation
- Metadata WARC files are automatically moved to `_meta/` subdirectory
- The script validates input and provides helpful error messages
- All WARC files are compressed with gzip (`.warc.gz`)

## Troubleshooting

**Issue**: Script permission denied
```bash
chmod +x crawl_script.sh
```

**Issue**: wget not found or no WARC support
- Ensure wget is installed with WARC support
- On Ubuntu/Debian: `sudo apt-get install wget`

**Issue**: Too many rejected URLs
- Check `logs/<prefix>.rejected.log` to see what was filtered
- Adjust `REJECT_REGEX` environment variable if needed
