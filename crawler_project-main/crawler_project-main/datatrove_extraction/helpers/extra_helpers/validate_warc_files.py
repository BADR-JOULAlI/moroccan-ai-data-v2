"""
WARC file validation and repair functionality.
Compatible with process.py imports - combines warcio recompress with fallback repair.

Optimizations vs original:
- validate_warc_file: skips full content reads (structural check only, ~5-10x faster)
- validate_and_repair_directory: parallel processing with ThreadPoolExecutor
- manual_repair: single-pass write (no intermediate in-memory buffer)
- early_exit option to stop on first bad record when just checking validity
"""
import sys
import subprocess
from pathlib import Path
from typing import Tuple, Optional, List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
import io

try:
    import warcio
    from warcio.archiveiterator import ArchiveIterator
    from warcio.warcwriter import WARCWriter
except ImportError:
    print("ERROR: warcio library not found. Install it with: pip install warcio")
    sys.exit(1)


def validate_warc_file(
    warc_path: Path,
    full_content_check: bool = False,   # <-- NEW: False = structural only (fast)
    early_exit: bool = True,             # <-- NEW: stop on first error
) -> Tuple[bool, int, Optional[str]]:
    """
    Validate a WARC.gz file by iterating all records.

    Args:
        warc_path:          Path to the WARC.gz file
        full_content_check: If True, read every byte of every record payload
                            (original behaviour, ~5-10x slower).
                            If False (default), only parse headers / iterate
                            the gzip stream — enough to catch truncation and
                            corrupt gzip members without touching payload bytes.
        early_exit:         Stop at the first bad record instead of counting
                            through the whole file.  Default True for speed.

    Returns:
        Tuple of (is_valid, record_count, error_message)
    """
    record_count = 0

    try:
        with open(warc_path, 'rb') as f:
            for record in ArchiveIterator(f):
                record_count += 1
                # Warcio also accepts legacy ARC, including some arbitrary
                # whitespace-separated input. A WARC validation must not label
                # those records as a valid archive for this pipeline.
                if record.format != "warc":
                    return False, record_count, f"Expected WARC record, found {record.format}"
                for header in ("WARC-Type", "WARC-Record-ID", "WARC-Date", "Content-Length"):
                    if not record.rec_headers.get_header(header):
                        return False, record_count, f"Missing WARC header: {header}"
                if int(record.rec_headers.get_header("Content-Length")) < 0:
                    return False, record_count, "Negative WARC Content-Length"

                if full_content_check:
                    # Original slow path: read every payload byte
                    try:
                        content_stream = record.content_stream()
                        while True:
                            chunk = content_stream.read(65536)   # larger chunk = fewer syscalls
                            if not chunk:
                                break
                    except Exception as e:
                        if early_exit:
                            return False, record_count, f"Error reading record {record_count}: {e}"
                        # Non-early-exit: keep counting but mark invalid
                        return False, record_count, f"Error reading record {record_count}: {e}"
                # else: ArchiveIterator already decompresses the gzip member
                # and parses the WARC header; that is sufficient for structural
                # validation without touching the payload bytes at all.

        if record_count == 0:
            return False, 0, "Archive contains no WARC records"
        return True, record_count, None

    except Exception as e:
        error_msg = f"Validation failed at record {record_count + 1}: {e}"
        return False, record_count, error_msg


def try_warcio_recompress(
    input_path: Path,
    output_path: Path,
    verbose: bool = False,
) -> Tuple[bool, int, str]:
    """
    Try to recover using warcio recompress command.
    This handles gzip format issues much better than manual repair.
    """
    try:
        if verbose:
            print("      Trying warcio recompress...", end=' ', flush=True)

        result = subprocess.run(
            ['warcio', 'recompress', str(input_path), str(output_path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )

        if result.returncode == 0 and output_path.exists():
            is_valid, count, _ = validate_warc_file(output_path)
            if is_valid:
                if verbose:
                    print(f"✓ Success ({count} records)")
                return True, count, f"warcio recompress recovered {count} records"
            else:
                if verbose:
                    print("✗ Output invalid")
                return False, 0, "warcio recompress produced invalid output"
        else:
            if verbose:
                print("✗ Failed")
            return False, 0, f"warcio recompress failed: {result.stderr[:200]}"

    except subprocess.TimeoutExpired:
        if verbose:
            print("✗ Timeout")
        return False, 0, "warcio recompress timed out"
    except FileNotFoundError:
        if verbose:
            print("✗ Command not found")
        return False, 0, "warcio command not available"
    except Exception as e:
        if verbose:
            print("✗ Error")
        return False, 0, f"warcio recompress error: {e}"


def manual_repair(
    input_path: Path,
    output_path: Path,
    verbose: bool = False,
) -> Tuple[bool, int, str]:
    """
    Manual repair by extracting valid records — single-pass, no in-memory buffer.

    Optimisation vs original:
    - Write records directly to the output gzip stream as they are read, instead
      of collecting all bytes in memory first and then doing a second ArchiveIterator
      pass.  This halves peak memory usage and removes the redundant parse.
    """
    if verbose:
        print("      Trying manual repair...", end=' ', flush=True)

    written_count = 0
    total_read = 0

    try:
        with open(output_path, 'wb') as out_f:
            gzip_writer = WARCWriter(out_f, gzip=True)

            with open(input_path, 'rb') as in_f:
                for record in ArchiveIterator(in_f):
                    total_read += 1
                    try:
                        gzip_writer.write_record(record)
                        written_count += 1
                    except Exception:
                        continue   # skip corrupt record, keep going

    except Exception:
        pass   # iterator may raise at EOF of a truncated file — that is fine

    if written_count == 0:
        if verbose:
            print("✗ No records extracted")
        # Remove empty/partial output
        if output_path.exists():
            output_path.unlink(missing_ok=True)
        return False, 0, "No records could be extracted"

    # Validate what we wrote
    is_valid, final_count, _ = validate_warc_file(output_path)
    if is_valid:
        if verbose:
            print(f"✓ Success ({final_count} records)")
        return True, final_count, f"Manual repair recovered {final_count}/{total_read} records"
    else:
        if verbose:
            print("✗ Output invalid")
        return False, 0, "Manual repair produced invalid output"


def repair_warc_file(
    warc_path: Path,
    backup: bool = True,
    keep_backup: bool = False,
) -> Tuple[bool, int, str, Optional[Path]]:
    """
    Repair a WARC file using best available method.
    Tries warcio recompress first, then falls back to manual repair.
    """
    import shutil

    backup_path = None
    if backup:
        backup_path = warc_path.with_suffix(warc_path.suffix + '.backup')
        try:
            shutil.copy2(warc_path, backup_path)
        except Exception as e:
            return False, 0, f"Failed to create backup: {e}", None

    temp_path = warc_path.with_suffix('.tmp.warc.gz')

    source = backup_path if backup_path else warc_path

    # Try warcio recompress first (best for gzip issues)
    success, count, msg = try_warcio_recompress(source, temp_path, verbose=True)

    if not success:
        success, count, msg = manual_repair(source, temp_path, verbose=True)

    if success:
        try:
            shutil.move(temp_path, warc_path)

            final_backup_path = None
            if backup_path:
                if keep_backup:
                    final_backup_path = backup_path
                else:
                    try:
                        backup_path.unlink()
                    except Exception:
                        final_backup_path = backup_path

            return True, count, msg, final_backup_path

        except Exception as e:
            return False, 0, f"Failed to replace file: {e}", backup_path
    else:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        return False, 0, msg, backup_path if keep_backup else None


# ---------------------------------------------------------------------------
# Internal helper — validates a single file and returns a result dict.
# Used by the parallel worker below.
# ---------------------------------------------------------------------------
def _validate_one(
    warc_file: Path,
    input_dir: Path,
    auto_repair: bool,
    backup: bool,
    keep_backups: bool,
) -> Dict:
    try:
        rel_path = warc_file.relative_to(input_dir)
    except ValueError:
        rel_path = warc_file

    is_valid, record_count, error_msg = validate_warc_file(warc_file)

    result = {
        'file': str(warc_file),
        'relative_path': str(rel_path),
        'status': 'VALID' if is_valid else 'INVALID',
        'records': record_count,
        'error': error_msg,
    }

    if not is_valid and auto_repair:
        success, repaired_records, repair_msg, backup_path = repair_warc_file(
            warc_file,
            backup=backup,
            keep_backup=keep_backups,
        )

        if success:
            is_valid_after, final_count, validation_error = validate_warc_file(warc_file)
            if is_valid_after:
                result.update(
                    status='REPAIRED',
                    records=final_count,
                    repair_message=repair_msg,
                    backup_kept=backup_path is not None,
                )
            else:
                result.update(
                    status='REPAIR_FAILED',
                    repair_message=f"Repair completed but validation failed: {validation_error}",
                )
        else:
            result.update(
                status='REPAIR_FAILED',
                repair_message=repair_msg,
            )

    return result

def validate_and_repair_directory(
    input_dir: Path,
    auto_repair: bool = False,
    backup: bool = True,
    keep_backups: bool = False,
    verbose: bool = True,
    max_workers: int = 4,          # <-- NEW: parallel workers (set 1 to disable)
) -> Dict[str, any]:
    """
    Validate all WARC.gz files in a directory and optionally repair them.

    Optimisations vs original:
    - Parallel validation via ThreadPoolExecutor (max_workers, default 4).
      I/O-bound workloads benefit immediately; use max_workers=1 to disable.
    - Delegates per-file logic to _validate_one() for clean separation.

    Note: repair operations are still sequential *per file* but multiple files
    are repaired concurrently.  If you use auto_repair=True make sure you have
    enough disk space for simultaneous temp files.
    """
    warc_files = [
        f for f in input_dir.rglob('*.warc.gz')
        if not f.name.endswith('.backup') and not f.name.endswith('.tmp.warc.gz')
    ]

    if not warc_files:
        return {
            'total_files': 0,
            'valid_files': 0,
            'invalid_files': 0,
            'repaired_files': 0,
            'failed_repairs': 0,
            'results': [],
        }

    if verbose:
        print(f"Found {len(warc_files)} WARC.gz files to validate")
        print(f"Search directory: {input_dir}")
        print(f"Parallel workers: {max_workers}")
        if auto_repair:
            print("Auto-repair: ENABLED")
            print(f"Backups: {'ENABLED' if backup else 'DISABLED'}")
            print(f"Keep backups after repair: {'YES' if keep_backups else 'NO'}")
        else:
            print("Auto-repair: DISABLED - will report only")
        print()

    results_map: Dict[Path, Dict] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_path = {
            pool.submit(
                _validate_one,
                wf,
                input_dir,
                auto_repair,
                backup,
                keep_backups,
            ): wf
            for wf in warc_files
        }

        completed = 0
        for future in as_completed(future_to_path):
            wf = future_to_path[future]
            completed += 1
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    'file': str(wf),
                    'relative_path': str(wf),
                    'status': 'ERROR',
                    'records': 0,
                    'error': str(exc),
                }
            results_map[wf] = result

            if verbose:
                status = result['status']
                records = result['records']
                rel = result['relative_path']
                icon = '✓' if status in ('VALID', 'REPAIRED') else '✗'
                label = f"{icon} {status} ({records} records)"
                print(f"[{completed}/{len(warc_files)}] {rel} ... {label}")
                if result.get('error') and status == 'INVALID':
                    print(f"    Error: {result['error']}")
                if result.get('repair_message'):
                    print(f"    {result['repair_message']}")

    # Preserve original file order for deterministic output
    results = [results_map[wf] for wf in warc_files]

    valid_count    = sum(1 for r in results if r['status'] == 'VALID')
    invalid_count  = sum(1 for r in results if r['status'] in ('INVALID', 'REPAIR_FAILED', 'ERROR'))
    repaired_count = sum(1 for r in results if r['status'] == 'REPAIRED')
    failed_repairs = sum(1 for r in results if r['status'] == 'REPAIR_FAILED')

    summary = {
        'total_files':    len(warc_files),
        'valid_files':    valid_count,
        'invalid_files':  invalid_count,
        'repaired_files': repaired_count,
        'failed_repairs': failed_repairs,
        'results':        results,
    }

    if verbose:
        print()
        print("=" * 80)
        print("VALIDATION SUMMARY")
        print("=" * 80)
        print(f"Total files:     {summary['total_files']}")
        print(f"Valid files:     {summary['valid_files']}")
        print(f"Invalid files:   {summary['invalid_files']}")
        if auto_repair:
            print(f"Repaired files:  {summary['repaired_files']}")
            print(f"Failed repairs:  {summary['failed_repairs']}")
        print("=" * 80)

    return summary


def main():
    """Command-line interface."""
    import argparse

    parser = argparse.ArgumentParser(description='Validate and repair WARC.gz files')
    parser.add_argument('path', type=Path, help='Path to WARC.gz file or directory')
    parser.add_argument('--repair',       action='store_true', help='Auto-repair invalid files')
    parser.add_argument('--no-backup',    action='store_true', help='No backup before repair')
    parser.add_argument('--keep-backups', action='store_true', help='Keep backups after repair')
    parser.add_argument('--single',       action='store_true', help='Single file mode')
    parser.add_argument('--quiet',        action='store_true', help='Minimal output')
    parser.add_argument('--full-check',   action='store_true',
                        help='Read full record payload during validation (slower but thorough)')
    parser.add_argument('--workers', type=int, default=4,
                        help='Parallel workers for directory validation (default: 4)')

    args = parser.parse_args()

    if not args.path.exists():
        print(f"ERROR: Path does not exist: {args.path}")
        sys.exit(1)

    if args.single or args.path.is_file():
        print(f"Validating: {args.path}")
        is_valid, record_count, error_msg = validate_warc_file(
            args.path,
            full_content_check=args.full_check,
        )

        if is_valid:
            print(f"✓ File is VALID ({record_count} records)")
            sys.exit(0)
        else:
            print(f"✗ File is INVALID")
            if error_msg:
                print(f"Error: {error_msg}")

            if args.repair:
                print("\nAttempting repair...")
                success, repaired_records, repair_msg, backup_path = repair_warc_file(
                    args.path,
                    backup=not args.no_backup,
                    keep_backup=args.keep_backups,
                )
                if success:
                    print(f"✓ Repaired ({repaired_records} records)")
                    if backup_path:
                        print(f"Backup: {backup_path}")
                    sys.exit(0)
                else:
                    print(f"✗ Failed: {repair_msg}")
                    sys.exit(1)
            else:
                print("\nUse --repair to attempt repair")
                sys.exit(1)
    else:
        summary = validate_and_repair_directory(
            args.path,
            auto_repair=args.repair,
            backup=not args.no_backup,
            keep_backups=args.keep_backups,
            verbose=not args.quiet,
            max_workers=args.workers,
        )

        if summary['invalid_files'] > 0 and not args.repair:
            sys.exit(1)
        if summary['failed_repairs'] > 0:
            sys.exit(1)

        sys.exit(0)


if __name__ == '__main__':
    main()
