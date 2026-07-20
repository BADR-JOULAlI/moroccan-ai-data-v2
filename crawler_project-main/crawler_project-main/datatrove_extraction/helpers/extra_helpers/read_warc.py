import warcio
from pathlib import Path

record_limit = 0
n_records = 0

# Default path - can be modified
warc_path = Path(__file__).parent.parent.parent / "input" / "segment-2026-01" / "moroccophobiaa-00000.warc.gz"
# warc_path = Path(__file__).parent.parent.parent / "input" / "segment-2026-01" / "ar.wikipedia.org-00000.warc.gz"

experiments_folder = Path(__file__).parent.parent.parent / "experiments"
experiments_folder.mkdir(exist_ok=True)
output_file = experiments_folder / "read_warc_output.txt"

if not warc_path.exists():
    error_msg = f"Error: WARC file not found at {warc_path}"
    print(error_msg)
    with open(output_file, "w", encoding="utf-8") as out_f:
        out_f.write(error_msg + "\n")
    exit(1)

with open(output_file, "w", encoding="utf-8") as out_f:
    out_f.write(f"Reading WARC file: {warc_path}\n")
    out_f.write("=" * 80 + "\n")
    out_f.write("\n")
    
    with open(warc_path, 'rb') as f:
        for i, record in enumerate(warcio.ArchiveIterator(f)):
            n_records += 1
            out_f.write("#" * 80 + "\n")
            out_f.write(f"Record {i + 1}\n")
            out_f.write("#" * 80 + "\n")
            
            # WARC headers
            out_f.write("WARC Headers:\n")
            out_f.write(f"  Type: {record.rec_type}\n")
            out_f.write(f"  Record ID: {record.rec_headers.get('WARC-Record-ID', 'N/A')}\n")
            out_f.write(f"  Date: {record.rec_headers.get('WARC-Date', 'N/A')}\n")
            out_f.write(f"  Target URI: {record.rec_headers.get('WARC-Target-URI', 'N/A')}\n")
            out_f.write(f"  Content-Type: {record.rec_headers.get('Content-Type', 'N/A')}\n")
            out_f.write("\n")
            
            # Read content
            if record.rec_type == 'response':
                try:
                    content = record.content_stream().read()
                    content_str = content.decode('utf-8', errors='ignore')
                    
                    out_f.write("Content Preview:\n")
                    out_f.write("-" * 80 + "\n")
                    # Show first 2000 characters
                    preview = content_str[:2000]
                    out_f.write(preview + "\n")
                    
                    if len(content_str) > 2000:
                        out_f.write(f"\n... (truncated, total length: {len(content_str)} characters)\n")
                    out_f.write("-" * 80 + "\n")
                    out_f.write("\n")
                    
                    # Try to extract HTTP status if it's an HTTP response
                    if content_str.startswith('HTTP/'):
                        lines = content_str.split('\n', 5)
                        if len(lines) > 0:
                            out_f.write(f"HTTP Status: {lines[0].strip()}\n")
                            out_f.write("\n")
                except Exception as e:
                    out_f.write(f"Error reading content: {e}\n")
                    out_f.write("\n")
            else:
                out_f.write(f"Record type '{record.rec_type}' - content not displayed\n")
                out_f.write("\n")
            
            out_f.write("=" * 80 + "\n")
            out_f.write("\n")
            
            # # Limit to first 5 records for preview
            if record_limit != 0:
                if i+1 >= record_limit:
                    out_f.write(f"... (showing first {i+1} records, use the script to see more)\n")
                    break
    
    out_f.write(f"Total records processed: {n_records}\n")

print(f"Total records processed: {n_records}")
print(f"Content written to: {output_file}")
