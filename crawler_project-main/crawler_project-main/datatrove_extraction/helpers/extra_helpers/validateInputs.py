"""Validate configured input archives without interactive or permissive fallback."""

from pathlib import Path


def validate_inputs(
    validate_warc: bool = False,
    auto_repair: bool = False,
    segment: str | None = None,
    *,
    input_dir: Path | None = None,
) -> int:
    """Return the archive count, raising on missing or invalid input.

    Legacy callers may supply a segment; the configured entry point supplies
    its resolved input directory. Repairs are explicit and retain backups.
    """
    if auto_repair and not validate_warc:
        raise ValueError("auto_repair requires validate_warc")
    if input_dir is None:
        input_dir = Path(__file__).resolve().parents[2] / "input"
        if segment:
            input_dir /= segment
    input_dir = Path(input_dir)
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")
    archives = sorted(input_dir.glob("*/*.warc.gz"))
    if not archives:
        raise ValueError(f"No WARC files found in <site>/*.warc.gz under {input_dir}")
    if validate_warc:
        from .validate_warc_files import validate_and_repair_directory

        summary = validate_and_repair_directory(
            input_dir, auto_repair=auto_repair, backup=True,
            keep_backups=True, verbose=True,
        )
        if summary["invalid_files"] or summary["failed_repairs"]:
            raise ValueError(
                f"WARC validation failed: {summary['invalid_files']} invalid archives, "
                f"{summary['failed_repairs']} failed repairs"
            )
    return len(archives)
