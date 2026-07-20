"""
Enhanced sitemap extraction script with robust URL handling + detailed logging.

Usage:
    uv run append_sitemaps.py

This script:
1. Reads URLs from file.txt
2. Extracts sitemap links for each URL
3. Handles various URL formats (with/without www, http/https, trailing slashes)
4. Writes results incrementally after each URL (saves partial results if disk quota exceeded)
5. Creates detailed logs:
   - ignored lines (not valid links)
   - duplicates removed
   - full stacktrace on sitemap errors
"""

from trafilatura import sitemaps
from pathlib import Path
import sys
from datetime import datetime
from urllib.parse import urlparse, urlunparse
import traceback


# ---------------------
# Configuration
# ---------------------
CRAWLING_DIR = Path(__file__).resolve().parents[1]
LINKS_FILE = CRAWLING_DIR / "file.txt"
LOGS_DIR = CRAWLING_DIR / "logs" / "append_sitemaps"
LOG_FILE = LOGS_DIR / f"append_sitemaps_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# Create logs directory if it doesn't exist
LOGS_DIR.mkdir(exist_ok=True)


def normalize_url(url: str) -> str:
    """
    Normalize a URL to its root domain form for comparison.
    Lowercase, no trailing slash, no query/fragment.
    """
    url = url.strip()

    parsed = urlparse(url)

    # Ensure scheme exists
    if not parsed.scheme:
        url = "https://" + url
        parsed = urlparse(url)

    normalized = urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path.rstrip("/"),
        "", "", ""
    ))
    return normalized


def extract_root_url(url: str) -> str:
    """
    Extract the root URL from any URL (scheme + netloc).
    Example:
        https://example.com/page -> https://example.com
    """
    parsed = urlparse(url)
    scheme = parsed.scheme or "https"
    return f"{scheme}://{parsed.netloc}"


def log(message: str, file_handle=None):
    """Write to log file and display in console."""
    print(message)
    if file_handle:
        file_handle.write(message + "\n")
        file_handle.flush()


def read_urls_from_file(file_path: Path, log_file=None):
    """
    Read and parse URLs from the input file.
    Handles comments, empty lines, and various URL formats.

    Returns:
        urls: list[str] valid unique root urls
        ignored_lines: list[dict] lines ignored because not considered links
        duplicate_lines: list[dict] lines ignored because duplicates after normalization
    """
    urls = []
    seen = set()

    ignored_lines = []
    duplicate_lines = []

    with file_path.open("r", encoding="utf-8") as f:
        for line_num, raw_line in enumerate(f, 1):
            line = raw_line.strip()

            # Skip empty lines
            if not line:
                ignored_lines.append({
                    "line_num": line_num,
                    "line": raw_line.rstrip("\n"),
                    "reason": "empty line"
                })
                continue

            # Skip comments
            if line.startswith("#"):
                ignored_lines.append({
                    "line_num": line_num,
                    "line": raw_line.rstrip("\n"),
                    "reason": "comment"
                })
                continue

            # Check if line looks like a URL
            if not (
                line.startswith("http://")
                or line.startswith("https://")
                or line.startswith("www.")
                or "." in line
            ):
                ignored_lines.append({
                    "line_num": line_num,
                    "line": raw_line.rstrip("\n"),
                    "reason": "does not look like a URL"
                })
                continue

            # Add scheme if missing
            if not line.startswith("http"):
                line = "https://" + line

            try:
                root_url = extract_root_url(line)
                normalized = normalize_url(root_url)

                # Malformed parsing: empty netloc
                if urlparse(root_url).netloc.strip() == "":
                    ignored_lines.append({
                        "line_num": line_num,
                        "line": raw_line.rstrip("\n"),
                        "reason": f"malformed URL after parsing -> root_url='{root_url}'"
                    })
                    continue

                # Duplicate detection
                if normalized in seen:
                    duplicate_lines.append({
                        "line_num": line_num,
                        "line": raw_line.rstrip("\n"),
                        "root_url": root_url,
                        "normalized": normalized,
                        "reason": "duplicate after normalization"
                    })
                    continue

                urls.append(root_url)
                seen.add(normalized)

            except Exception as e:
                ignored_lines.append({
                    "line_num": line_num,
                    "line": raw_line.rstrip("\n"),
                    "reason": f"exception while parsing: {e}"
                })
                continue

    # Quick stats in log
    log(f"  Lines ignored (not links): {len(ignored_lines)}", log_file)
    log(f"  Lines ignored (duplicates): {len(duplicate_lines)}", log_file)

    return urls, ignored_lines, duplicate_lines


def fetch_sitemap_links(url: str, log_file=None):
    """
    Fetch sitemap links for a given URL.
    Logs full stacktrace if any error happens.
    """
    try:
        log(f"    Searching for sitemap...", log_file)

        mylinks = sitemaps.sitemap_search(url)

        if mylinks:
            sitemap_list = list(mylinks)
            log(f"   ✓ Found {len(sitemap_list)} link(s)", log_file)
            return sitemap_list

        log(f"     No sitemap found", log_file)
        return []

    except Exception as e:
        # Short error line
        log(f"    Error: {e}", log_file)

        # Full stacktrace
        tb = traceback.format_exc()
        log(tb.rstrip("\n"), log_file)

        log(f"     No sitemap found", log_file)
        return []


def main():
    """Main execution function."""
    with LOG_FILE.open("w", encoding="utf-8") as log_file:

        if not LINKS_FILE.exists():
            log(f"✗ File not found: {LINKS_FILE}", log_file)
            sys.exit(1)

        # Header
        log("=" * 70, log_file)
        log(" SITEMAP EXTRACTION TOOL (INCREMENTAL WRITING)", log_file)
        log("=" * 70, log_file)
        log(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", log_file)
        log(f"Input file: {LINKS_FILE}", log_file)
        log(f"Log file: {LOG_FILE}", log_file)
        log("", log_file)

        # Read URLs
        log("⏳ Reading URLs from file...", log_file)
        try:
            original_urls, ignored_lines, duplicate_lines = read_urls_from_file(LINKS_FILE, log_file)
        except Exception as e:
            log(f"✗ Error reading file: {e}", log_file)
            log(traceback.format_exc().rstrip("\n"), log_file)
            sys.exit(1)

        if not original_urls:
            log("✗ No valid URLs found in file.txt", log_file)
            sys.exit(1)

        log("", log_file)
        log(f"✓ Found {len(original_urls)} unique root URL(s):", log_file)
        for url in original_urls:
            log(f"  • {url}", log_file)
        log("", log_file)

        # Log ignored lines
        if ignored_lines:
            log("=" * 70, log_file)
            log(" IGNORED LINES (NOT CONSIDERED LINKS)", log_file)
            log("=" * 70, log_file)
            for item in ignored_lines:
                log(f"  Line {item['line_num']}: {item['line']}  --> {item['reason']}", log_file)
            log("", log_file)

        # Log duplicates
        if duplicate_lines:
            log("=" * 70, log_file)
            log(" DUPLICATE LINES REMOVED", log_file)
            log("=" * 70, log_file)
            for item in duplicate_lines:
                log(
                    f"  Line {item['line_num']}: {item['line']}  --> {item['reason']} "
                    f"(root={item['root_url']}, normalized={item['normalized']})",
                    log_file
                )
            log("", log_file)

        # Process each URL
        log("=" * 70, log_file)
        log(" PROCESSING URLS (WRITING INCREMENTALLY)", log_file)
        log("=" * 70, log_file)
        log("", log_file)

        total_links = 0
        successful_urls = 0
        total_lines_written = 0
        last_completed_url_index = 0

        # Open file for writing (this will overwrite the original file)
        try:
            output_file = LINKS_FILE.open("w", encoding="utf-8")
            log("✓ Output file opened for writing", log_file)
            log("", log_file)
        except Exception as e:
            log(f"✗ Error opening output file: {e}", log_file)
            log(traceback.format_exc().rstrip("\n"), log_file)
            sys.exit(1)

        try:
            for i, origin_url in enumerate(original_urls, 1):
                log("-" * 70, log_file)
                log(f"[{i}/{len(original_urls)}]  {origin_url}", log_file)

                # Write section header + original root URL
                output_file.write(f"# {origin_url}\n")
                output_file.write(f"{origin_url}\n")
                total_lines_written += 2

                # Fetch sitemap links
                sitemap_links = fetch_sitemap_links(origin_url, log_file)

                if sitemap_links:
                    total_links += len(sitemap_links)
                    successful_urls += 1
                    for link in sitemap_links:
                        output_file.write(f"{link}\n")
                        total_lines_written += 1

                # Blank line between groups
                output_file.write("\n")
                total_lines_written += 1

                # Flush to disk after each URL to ensure data is saved
                output_file.flush()
                last_completed_url_index = i
                log(f"    ✓ Written to file (total lines so far: {total_lines_written})", log_file)
                log("", log_file)

            log("=" * 70, log_file)
            log("✓ All URLs processed and written successfully!", log_file)

        except OSError as e:
            if e.errno == 122:  # Disk quota exceeded
                log("=" * 70, log_file)
                log(f"✗ DISK QUOTA EXCEEDED at URL #{i}", log_file)
                log(f"⚠ Partial results saved for URLs 1-{last_completed_url_index}", log_file)
                log(f"⚠ To continue: free up disk space and re-run with remaining URLs", log_file)
            else:
                log("=" * 70, log_file)
                log(f"✗ OS Error during processing: {e}", log_file)
                log(traceback.format_exc().rstrip("\n"), log_file)
                log(f"⚠ Partial results saved up to URL #{last_completed_url_index}", log_file)
        except Exception as e:
            log("=" * 70, log_file)
            log(f"✗ Error during processing: {e}", log_file)
            log(traceback.format_exc().rstrip("\n"), log_file)
            log("", log_file)
            log(f"⚠ Partial results saved up to URL #{last_completed_url_index}", log_file)
        finally:
            output_file.close()
            log("✓ Output file closed", log_file)

        # Summary
        log("", log_file)
        log("=" * 70, log_file)
        log(" SUMMARY", log_file)
        log("=" * 70, log_file)
        log(f"Root URLs to process:       {len(original_urls)}", log_file)
        log(f"URLs successfully processed: {last_completed_url_index}", log_file)
        log(f"Lines ignored (not links):  {len(ignored_lines)}", log_file)
        log(f"Lines ignored (duplicates): {len(duplicate_lines)}", log_file)
        log(f"URLs with sitemaps found:   {successful_urls}", log_file)
        log(f"Total sitemap links:        {total_links}", log_file)
        if last_completed_url_index > 0:
            log(f"Average links per URL:      {total_links / last_completed_url_index:.1f}", log_file)
        log(f"Total lines written:        {total_lines_written}", log_file)
        log("", log_file)
        log(f"Output file:  {LINKS_FILE}", log_file)
        log(f"Log file:     {LOG_FILE}", log_file)
        log("=" * 70, log_file)
        log(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", log_file)
        log("=" * 70, log_file)

    print(f"\n✓ Extraction completed! Log available at: {LOG_FILE}")


if __name__ == "__main__":
    main()