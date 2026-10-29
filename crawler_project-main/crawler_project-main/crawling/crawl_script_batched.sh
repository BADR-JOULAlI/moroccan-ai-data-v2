#!/usr/bin/env bash
set -euo pipefail

# =========================
# Goal: Create .warc.gz files (for downstream text extraction) using wget recursion.
# Supports:
# - Single seed URL OR a seeds file (one URL per line)
# - AUTOMATIC BATCHING for large seed files to prevent memory issues
# Notes:
# - Stays on the seed host by default (no cross-host traversal).
# - Uses reject-regex to avoid common crawler traps.
# - Uses quota + warc rotation to keep outputs bounded.
# - Uses --delete-after to avoid storing a local mirror long-term.
# - Moves wget-generated *-meta.warc.gz files under $OUTDIR/_meta/
# - This work was done in MNRT, a team of 4 members supervised by Mr. Abderrahman
# - use this website to check your crawling: https://replayweb.page/

usage() {
  cat >&2 <<'EOF'
Usage:
  ./crawl_script_batched.sh file.txt <prefix>

Examples:
  ./crawl_script_batched.sh file.txt <prefix>
  ./crawl_script_batched.sh "https://example.com/" <prefix>
  DEPTH=4 ROBOTS=on ./crawl_script_batched.sh "https://example.com/" <prefix>
  DEPTH=3 BATCH_SIZE=25 ./crawl_script_batched.sh file.txt <prefix>
  DRY_RUN=1 ./crawl_script_batched.sh file.txt <prefix>

Seeds file format:
  - One URL per line
  - Blank lines are ignored
  - Lines starting with # are ignored

Environment variables (tunable):
  DEPTH           Recursion depth (default: 3)
  WAIT_SECS       Polite delay between requests (default: 1)
  RANDOM_WAIT     1 to add jitter (default: 1)
  TIMEOUT_SECS    Network timeout per request (default: 30)
  TRIES           Retry attempts per URL (default: 3)
  MAX_REDIRECT    Max redirects to follow per URL (default: 10)
  QUOTA           Total download cap (default: 0 = unlimited), e.g., 2G, 500M
  ROBOTS          Respect robots.txt: on|off (default: on)
  UA              User-Agent string (default: Wget-WARC/1.0 (project: warc-crawl))
  REJECT_REGEX    URLs to exclude (default: common traps)
  DELETE_AFTER    1 to delete downloaded mirror files (default: 1)

  WARC_MAX_SIZE   Rotate WARC chunks at this size (default: 1G)
  WARC_TEMPDIR    Temp dir for WARC assembly (default: crawl_out/<prefix>/.warc-tmp)
  KEEP_TEMPDIR    1 to keep temp dir after exit (default: 0)

  LOGFILE         If set, write wget logs to this file (default: crawl_out/<prefix>/logs/<prefix>.log)
  REJECTED_LOG    If set, write rejected URLs to this file (default: crawl_out/<prefix>/logs/<prefix>.rejected.log)
  FAILED_URLS     If set, write failed URLs to this file (default: crawl_out/<prefix>/logs/<prefix>.failed_urls.txt)
  DRY_RUN         1 to print planned crawl settings without running wget (default: 0)

  BATCH_SIZE      Number of URLs per batch (default: 100, set to 0 to disable batching)
  BATCH_PAUSE     Seconds to pause between batches (default: 5)

Exit codes:
  2 - usage / input error
  3 - crawl completed with wget failures
EOF
}

die() {
  local msg="${1:-Unknown error}"
  local code="${2:-2}"
  echo "Error: $msg" >&2
  echo >&2
  usage
  exit "$code"
}

extract_host() {
  local url="$1"
  url="${url#http://}"
  url="${url#https://}"
  url="${url%%/*}"
  printf '%s' "$url"
}

first_seed_from_file() {
  local f="$1"
  grep -E -v '^[[:space:]]*($|#)' "$f" | head -n 1
}

# -------------------------
# Parse inputs (URL or file)
# -------------------------
[[ $# -eq 2 ]] || die "Expected exactly 2 arguments: <file.txt|website_url> <prefix>"

# Get script directory for consistent path resolution
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TARGET="$1"
PREFIX="$2"
OUTDIR="$SCRIPT_DIR/crawl_out/$PREFIX"

[[ "$PREFIX" =~ ^[A-Za-z0-9._-]+$ ]] || die "Invalid prefix. Use only A-Za-z0-9._- (got: $PREFIX)"

# Resolve file path: if relative path or filename, check script directory if not found in current dir
resolve_file_path() {
  local file_path="$1"

  # If it's a URL, return as-is
  if [[ "$file_path" =~ ^https?:// ]]; then
    echo "$file_path"
    return 0
  fi

  # If absolute path exists, return as-is
  if [[ "$file_path" =~ ^/ ]] && [[ -f "$file_path" ]]; then
    echo "$file_path"
    return 0
  fi

  # If file exists in current directory, return absolute path
  if [[ -f "$file_path" ]]; then
    echo "$(cd "$(dirname "$file_path")" && pwd)/$(basename "$file_path")"
    return 0
  fi

  # If not found, try in script directory
  local script_dir_file="$SCRIPT_DIR/$(basename "$file_path")"
  if [[ -f "$script_dir_file" ]]; then
    echo "$script_dir_file"
    return 0
  fi

  # Not found anywhere
  return 1
}

MODE=""         # url|file
SEED_URL=""
SEEDS_FILE=""

if [[ "$TARGET" =~ ^https?:// ]]; then
  MODE="url"
  SEED_URL="$TARGET"
else
  # Try to resolve file path
  RESOLVED_TARGET="$(resolve_file_path "$TARGET")" || \
    die "First argument must be an http(s) URL or an existing file path (got: $TARGET)"

  if [[ "$RESOLVED_TARGET" =~ ^https?:// ]]; then
    # Should not happen, but handle it
    MODE="url"
    SEED_URL="$RESOLVED_TARGET"
  elif [[ -f "$RESOLVED_TARGET" ]]; then
    MODE="file"
    SEEDS_FILE="$RESOLVED_TARGET"
  else
    die "First argument must be an http(s) URL or an existing file path (got: $TARGET)"
  fi
fi

# Validate seed(s) and derive reference host for logs
HOST=""
if [[ "$MODE" == "url" ]]; then
  HOST="$(extract_host "$SEED_URL")"
else
  FIRST_URL="$(first_seed_from_file "$SEEDS_FILE" || true)"
  [[ -n "${FIRST_URL:-}" ]] || die "Seeds file is empty (or only comments): $SEEDS_FILE"
  [[ "$FIRST_URL" =~ ^https?:// ]] || die "Seeds file first URL must start with http(s):// (got: $FIRST_URL)"
  HOST="$(extract_host "$FIRST_URL")"

  # Optional warning if seeds file contains multiple hosts (allowed; just a warning)
  unique_hosts_count="$(
    grep -E -v '^[[:space:]]*($|#)' "$SEEDS_FILE" \
      | sed -E 's#^[a-zA-Z]+://([^/]+).*#\1#' \
      | sort -u | wc -l | tr -d ' '
  )"
  if [[ "${unique_hosts_count:-1}" -gt 1 ]]; then
    echo "Warning: seeds file contains multiple hosts ($unique_hosts_count). This can expand scope unintentionally." >&2
  fi
fi

# -------------------------
# Defaults (can be overridden via env)
# -------------------------
DEPTH="${DEPTH:-5}"
WAIT_SECS="${WAIT_SECS:-1}"
RANDOM_WAIT="${RANDOM_WAIT:-1}"
TIMEOUT_SECS="${TIMEOUT_SECS:-30}"
TRIES="${TRIES:-3}"
MAX_REDIRECT="${MAX_REDIRECT:-10}"
QUOTA="${QUOTA:-0}"
ROBOTS="${ROBOTS:-on}"
UA="${UA:-Wget-WARC/1.0 (project: warc-crawl)}"
DELETE_AFTER="${DELETE_AFTER:-1}"
DRY_RUN="${DRY_RUN:-0}"

WARC_MAX_SIZE="${WARC_MAX_SIZE:-1G}"
WARC_TEMPDIR="${WARC_TEMPDIR:-$OUTDIR/.warc-tmp}"
KEEP_TEMPDIR="${KEEP_TEMPDIR:-0}"

# NEW: Batching configuration
BATCH_SIZE="${BATCH_SIZE:-100}"      # URLs per batch
BATCH_PAUSE="${BATCH_PAUSE:-5}"      # Seconds between batches

mkdir -p "$OUTDIR/$PREFIX" "$OUTDIR/logs" "$OUTDIR/files" "$WARC_TEMPDIR"

LOGFILE="${LOGFILE:-$OUTDIR/logs/$PREFIX.log}"
REJECTED_LOG="${REJECTED_LOG:-$OUTDIR/logs/$PREFIX.rejected.log}"
FAILED_URLS="${FAILED_URLS:-$OUTDIR/logs/$PREFIX.failed_urls.txt}"
OVERALL_FAILURES=0
: > "$FAILED_URLS"

# allowing pdf
DEFAULT_REJECT_REGEX="$(
  printf '%s' \
'/(login|logout|signin|signout|signup|cart|checkout)(/|$)' \
'|/wp-admin(/|$)' \
'|([?&](session|sid|phpsessid|jsessionid|token)=)' \
'|([?&](utm_[[:alnum:]_]+|ref|fbclid|gclid)=)' \
'|\.(png|jpe?g|gif|svg|webp|ico|js|css|woff2?|ttf|eot|otf|mp4|webm|mp3|wav|avi|mov|zip|rar|7z|tar|gz|bz2|xz)(\?|$)' \
'|([?&](format|ext|type|output)(=)?(png|jpe?g|gif|svg|webp|mp4|mp3))([&#]|$)'
)"

REJECT_REGEX="${REJECT_REGEX:-$DEFAULT_REJECT_REGEX}"

# -------------------------
# Validate basics
# -------------------------
[[ "$DEPTH" =~ ^[0-9]+$ ]] || die "DEPTH must be an integer (got: $DEPTH)"
[[ "$WAIT_SECS" =~ ^[0-9]+$ ]] || die "WAIT_SECS must be an integer (got: $WAIT_SECS)"
[[ "$TIMEOUT_SECS" =~ ^[0-9]+$ ]] || die "TIMEOUT_SECS must be an integer (got: $TIMEOUT_SECS)"
[[ "$TRIES" =~ ^[0-9]+$ ]] || die "TRIES must be an integer (got: $TRIES)"
[[ "$MAX_REDIRECT" =~ ^[0-9]+$ ]] || die "MAX_REDIRECT must be an integer (got: $MAX_REDIRECT)"
[[ "$ROBOTS" == "on" || "$ROBOTS" == "off" ]] || die "ROBOTS must be 'on' or 'off' (got: $ROBOTS)"
[[ "$RANDOM_WAIT" == "0" || "$RANDOM_WAIT" == "1" ]] || die "RANDOM_WAIT must be 0 or 1 (got: $RANDOM_WAIT)"
[[ "$DELETE_AFTER" == "0" || "$DELETE_AFTER" == "1" ]] || die "DELETE_AFTER must be 0 or 1 (got: $DELETE_AFTER)"
[[ "$DRY_RUN" == "0" || "$DRY_RUN" == "1" ]] || die "DRY_RUN must be 0 or 1 (got: $DRY_RUN)"
[[ "$KEEP_TEMPDIR" == "0" || "$KEEP_TEMPDIR" == "1" ]] || die "KEEP_TEMPDIR must be 0 or 1 (got: $KEEP_TEMPDIR)"
[[ "$BATCH_SIZE" =~ ^[0-9]+$ ]] || die "BATCH_SIZE must be an integer (got: $BATCH_SIZE)"
[[ "$BATCH_PAUSE" =~ ^[0-9]+$ ]] || die "BATCH_PAUSE must be an integer (got: $BATCH_PAUSE)"

# -------------------------
# NEW: Check if batching is needed
# -------------------------
NEEDS_BATCHING=0
TOTAL_URLS=0

if [[ "$MODE" == "file" ]] && [[ "$BATCH_SIZE" -gt 0 ]]; then
  TOTAL_URLS=$(grep -E -v '^[[:space:]]*($|#)' "$SEEDS_FILE" | wc -l | tr -d ' ')
  
  if [[ "$TOTAL_URLS" -gt "$BATCH_SIZE" ]]; then
    NEEDS_BATCHING=1
    NUM_BATCHES=$(( (TOTAL_URLS + BATCH_SIZE - 1) / BATCH_SIZE ))
    
    echo "=========================================="
    echo "BATCHING ENABLED"
    echo "=========================================="
    echo "Total URLs    : $TOTAL_URLS"
    echo "Batch size    : $BATCH_SIZE URLs/batch"
    echo "Total batches : $NUM_BATCHES"
    echo "Batch pause   : $BATCH_PAUSE seconds"
    echo "=========================================="
    echo
  fi
fi

# -------------------------
# Cleanup (best effort)
# -------------------------
cleanup() {
  if [[ "$KEEP_TEMPDIR" != "1" ]]; then
    rm -rf "$WARC_TEMPDIR" || true
  fi
  # Clean up batch temp files
  rm -f "$OUTDIR/.batch_"*.txt 2>/dev/null || true
}
trap cleanup EXIT

# -------------------------
# Function to run wget for a single batch or full file
# -------------------------
run_wget_crawl() {
  local input_file="$1"
  local batch_num="${2:-0}"
  local is_batch="${3:-0}"
  
  # Adjust output names for batches
  local warc_base="$OUTDIR/$PREFIX/$PREFIX"
  local logfile="$LOGFILE"
  local rejected_log="$REJECTED_LOG"
  
  if [[ "$is_batch" == "1" ]]; then
    warc_base="${warc_base}_batch$(printf "%04d" "$batch_num")"
    logfile="${LOGFILE%.log}_batch$(printf "%04d" "$batch_num").log"
    rejected_log="${REJECTED_LOG%.log}_batch$(printf "%04d" "$batch_num").rejected.log"
  fi
  
  # Build wget args
  local wget_args=(
    --recursive
    --level="$DEPTH"
    --no-parent

    --wait="$WAIT_SECS"
    --timeout="$TIMEOUT_SECS"
    --tries="$TRIES"
    --max-redirect="$MAX_REDIRECT"
    --user-agent="$UA"
    --execute="robots=$ROBOTS"

    --reject-regex="$REJECT_REGEX"

    --warc-file="$warc_base"
    --warc-max-size="$WARC_MAX_SIZE"
    --warc-tempdir="$WARC_TEMPDIR"

    -o "$logfile"
    --rejected-log="$rejected_log"

    --directory-prefix="$OUTDIR/files"
  )

  if [[ "$RANDOM_WAIT" == "1" ]]; then
    wget_args+=( --random-wait )
  fi

  if [[ "$QUOTA" != "0" ]]; then
    wget_args+=( --quota="$QUOTA" )
  fi

  if [[ "$DELETE_AFTER" == "1" ]]; then
    wget_args+=( --delete-after )
  fi
  
  # Print batch info
  if [[ "$is_batch" == "1" ]]; then
    echo "----------------------------------------"
    echo "Processing BATCH $batch_num / $NUM_BATCHES"
    echo "WARC output: $(basename "$warc_base")"
    echo "Log file   : $(basename "$logfile")"
    echo "----------------------------------------"
  fi

  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[DRY RUN] Would run wget with input: $input_file"
    echo "[DRY RUN] WARC output base: $warc_base"
    return 0
  fi
  
  # Run wget
  set +e
  wget "${wget_args[@]}" --input-file="$input_file"
  local wget_exit_code=$?
  set -e
  
  # Every nonzero wget status means this input may need to be retried.
  if [[ $wget_exit_code -ne 0 ]]; then
    echo "Warning: wget exited with code $wget_exit_code for batch $batch_num" >&2
    cat "$input_file" >> "$FAILED_URLS"
    OVERALL_FAILURES=$((OVERALL_FAILURES + 1))
    return "$wget_exit_code"
  fi
  
  return 0
}

# -------------------------
# Main execution
# -------------------------
echo "Mode          : $MODE"
echo "Host (ref)    : $HOST"
echo "Output dir    : $OUTDIR"
echo "Prefix        : $PREFIX"
echo "Depth         : $DEPTH"
echo "Wait/random   : $WAIT_SECS / $RANDOM_WAIT"
echo "Timeout/tries : $TIMEOUT_SECS / $TRIES"
echo "Quota         : $QUOTA"
echo "Robots        : $ROBOTS"
echo "Delete-after  : $DELETE_AFTER"
echo "WARC max size : $WARC_MAX_SIZE"
echo "Failed URLs   : $FAILED_URLS"
echo "Dry run       : $DRY_RUN"
echo

OVERALL_START_TIME=$(date +%s)

if [[ "$MODE" == "url" ]]; then
  # Single URL mode - no batching
  WARC_BASE="$OUTDIR/$PREFIX/$PREFIX"
  
  WGET_ARGS=(
    --recursive
    --level="$DEPTH"
    --no-parent

    --wait="$WAIT_SECS"
    --timeout="$TIMEOUT_SECS"
    --tries="$TRIES"
    --max-redirect="$MAX_REDIRECT"
    --user-agent="$UA"
    --execute="robots=$ROBOTS"

    --reject-regex="$REJECT_REGEX"

    --warc-file="$WARC_BASE"
    --warc-max-size="$WARC_MAX_SIZE"
    --warc-tempdir="$WARC_TEMPDIR"

    -o "$LOGFILE"
    --rejected-log="$REJECTED_LOG"

    --directory-prefix="$OUTDIR/files"
  )

  if [[ "$RANDOM_WAIT" == "1" ]]; then
    WGET_ARGS+=( --random-wait )
  fi

  if [[ "$QUOTA" != "0" ]]; then
    WGET_ARGS+=( --quota="$QUOTA" )
  fi

  if [[ "$DELETE_AFTER" == "1" ]]; then
    WGET_ARGS+=( --delete-after )
  fi
  
  echo "Seed URL      : $SEED_URL"
  echo
  echo "The process is starting .... at $(date)"

  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[DRY RUN] Would run wget for seed URL: $SEED_URL"
  else
  
    set +e
    wget "${WGET_ARGS[@]}" "$SEED_URL"
    WGET_EXIT_CODE=$?
    set -e
    if [[ $WGET_EXIT_CODE -ne 0 ]]; then
      echo "Warning: wget exited with code $WGET_EXIT_CODE for $SEED_URL" >&2
      echo "$SEED_URL" >> "$FAILED_URLS"
      OVERALL_FAILURES=$((OVERALL_FAILURES + 1))
    fi
  fi

elif [[ "$NEEDS_BATCHING" == "1" ]]; then
  # BATCH MODE: Split file and process in chunks
  echo "Seeds file    : $SEEDS_FILE"
  echo
  echo "Starting BATCH processing at $(date)"
  echo
  
  # Extract clean URLs (no comments, no blanks)
  CLEAN_URLS_FILE="$OUTDIR/.clean_urls.txt"
  grep -E -v '^[[:space:]]*($|#)' "$SEEDS_FILE" > "$CLEAN_URLS_FILE"
  
  BATCH_NUM=0
  URLS_PROCESSED=0
  
  # Process in batches
  while IFS= read -r line || [[ -n "$line" ]]; do
    # Accumulate URLs into current batch file
    if [[ $((URLS_PROCESSED % BATCH_SIZE)) -eq 0 ]]; then
      BATCH_NUM=$((BATCH_NUM + 1))
      CURRENT_BATCH_FILE="$OUTDIR/.batch_$(printf "%04d" "$BATCH_NUM").txt"
      > "$CURRENT_BATCH_FILE"  # Create empty file
    fi
    
    # Add URL to current batch
    echo "$line" >> "$CURRENT_BATCH_FILE"
    URLS_PROCESSED=$((URLS_PROCESSED + 1))
    
    # If batch is full OR this is the last URL, process the batch
    if [[ $((URLS_PROCESSED % BATCH_SIZE)) -eq 0 ]] || [[ $URLS_PROCESSED -eq $TOTAL_URLS ]]; then
      # Process this batch
      run_wget_crawl "$CURRENT_BATCH_FILE" "$BATCH_NUM" "1" || true
      
      echo "Batch $BATCH_NUM completed. URLs processed: $URLS_PROCESSED / $TOTAL_URLS"
      
      # Clean up batch file
      rm -f "$CURRENT_BATCH_FILE"
      
      # Pause between batches (except after last batch)
      if [[ $URLS_PROCESSED -lt $TOTAL_URLS ]]; then
        echo "Pausing $BATCH_PAUSE seconds before next batch..."
        sleep "$BATCH_PAUSE"
        echo
      fi
    fi
  done < "$CLEAN_URLS_FILE"
  
  # Clean up
  rm -f "$CLEAN_URLS_FILE"
  
else
  # NORMAL MODE: Process entire file at once
  echo "Seeds file    : $SEEDS_FILE"
  echo "Total URLs    : $TOTAL_URLS"
  echo
  echo "The process is starting .... at $(date)"
  
  run_wget_crawl "$SEEDS_FILE" 0 0 || true
fi

OVERALL_END_TIME=$(date +%s)
OVERALL_DURATION=$((OVERALL_END_TIME - OVERALL_START_TIME))
HOURS=$((OVERALL_DURATION / 3600))
MINUTES=$(((OVERALL_DURATION % 3600) / 60))
SECS=$((OVERALL_DURATION % 60))

echo
echo "=========================================="
echo "Done Crawling"
echo "=========================================="
echo
echo "Start Saving metadata..."

# Move meta files
shopt -s nullglob
meta_files=( "$OUTDIR/$PREFIX/"*-meta.warc.gz )

if ((${#meta_files[@]})); then
  mkdir -p "$OUTDIR/_meta"
  mv -f -- "${meta_files[@]}" "$OUTDIR/_meta/" || true
  echo "Moved ${#meta_files[@]} metadata files to $OUTDIR/_meta/"
fi

shopt -u nullglob
echo "Completed Saving"
echo
echo "=========================================="
echo "CRAWL SUMMARY"
echo "=========================================="
echo "Output dir    : $OUTDIR/$PREFIX/"
echo "Total duration: ${HOURS}h ${MINUTES}m ${SECS}s"
echo "Failures      : $OVERALL_FAILURES"
echo "Failed inputs : $FAILED_URLS"

if [[ "$NEEDS_BATCHING" == "1" ]]; then
  echo "Batches       : $NUM_BATCHES"
  echo "URLs per batch: $BATCH_SIZE"
  echo "Total URLs    : $TOTAL_URLS"
fi

echo "=========================================="
echo
echo "WARC files:"
ls -lh "$OUTDIR/$PREFIX/" | sed -n '1,50p'

if [[ "$OVERALL_FAILURES" -gt 0 ]]; then
  echo
  echo "Crawl completed with failures. See: $FAILED_URLS" >&2
  exit 3
fi
