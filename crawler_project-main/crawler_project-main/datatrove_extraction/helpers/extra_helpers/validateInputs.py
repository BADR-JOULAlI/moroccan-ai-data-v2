from pathlib import Path
import sys

def validate_inputs(validate_warc: bool = False, auto_repair: bool = False, segment: str = None):
    """
    Validate input directory and optionally validate/repair WARC files.
    
    Args:
        validate_warc: If True, validate WARC file integrity
        auto_repair: If True, automatically repair invalid WARC files (requires validate_warc=True)
        segment: Optional segment name to validate (e.g., "segment-2026-01")
    """
    input_dir = Path(__file__).parent.parent.parent / "input"
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")
    
    # If segment specified, validate only that segment
    if segment:
        input_dir = input_dir / segment
    
    warc_files = [file for file in input_dir.rglob("*.warc.gz") if file.is_file()]
    if not warc_files:
        raise ValueError(f"No WARC files found in {input_dir}")
    
    # Validate output directories can be created
    output_dir = Path(__file__).parent.parent.parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    num_files = len(warc_files)
    print(f"Found {num_files} WARC files to process")
    
    # Optional: Validate and repair WARC files
    if validate_warc:
        print("\n" + "=" * 80)
        print("WARC FILE VALIDATION")
        print("=" * 80)
        
        try:
            from helpers.extra_helpers.validate_warc_files import validate_and_repair_directory
            
            # Determine directory to validate
            if segment:
                validate_dir = Path(__file__).parent.parent.parent / "input" / segment
            else:
                validate_dir = Path(__file__).parent.parent.parent / "input"
            
            results = validate_and_repair_directory(
                input_dir=validate_dir,
                auto_repair=auto_repair,
                backup=True,
                verbose=True
            )
            
            # Check if there are critical issues
            if results['invalid_files'] > 0 and not auto_repair:
                print(f"\n⚠️  WARNING: {results['invalid_files']} invalid WARC files found!")
                print("   Run with --auto-repair to fix them automatically, or")
                print("   use: python explanation/validate_and_repair_warc.py --directory <path>")
                print()
                response = input("Continue processing anyway? (y/n): ").strip().lower()
                if response != 'y':
                    print("Aborting. Please repair invalid files first.")
                    sys.exit(1)
            
            if results['failed_repairs'] > 0:
                print(f"\n❌ ERROR: {results['failed_repairs']} files could not be repaired!")
                print("   Please check these files manually.")
                sys.exit(1)
            
            if results['repaired_files'] > 0:
                print(f"\n✓ Successfully repaired {results['repaired_files']} files")
            
            if results['invalid_files'] == 0:
                print("\n✓ All WARC files are valid!")
            
        except ImportError as e:
            print(f"⚠️  WARNING: Could not import WARC validation module: {e}")
            print("   Skipping WARC validation. Install warcio if needed.")
        except Exception as e:
            print(f"⚠️  WARNING: WARC validation failed: {e}")
            print("   Continuing with processing anyway...")
        
        print("=" * 80 + "\n")

