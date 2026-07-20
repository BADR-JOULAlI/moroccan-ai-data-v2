import zstandard as zstd
import json
from pathlib import Path
import base64

segment = "segment-2026-01"

# Usage: uv run read_jsonl_zst.py

### Folder containing jsonl.zst files ###
# Data filtering stage
# jsonl_folder = Path(__file__).parent.parent.parent / "output" / segment / "data_filtering" / "pdfs"
# jsonl_folder = Path(__file__).parent.parent.parent / "output" / segment / "data_filtering" / "html"
# jsonl_folder = Path(__file__).parent.parent.parent / "output" / segment / "data_filtering" / "not_html_or_pdf"

# Base processing stage
# jsonl_folder = Path(__file__).parent.parent.parent / "output" / segment / "base_processing" / "html" / "output"

# final data
# jsonl_folder = Path(__file__).parent.parent.parent / "output" / segment / "minhash" / "html" / "final_data"
# jsonl_folder = Path(__file__).parent.parent.parent / "output" / segment / "minhash" / "pdfs" / "non_ocr"
# jsonl_folder = Path(__file__).parent.parent.parent / "output" / segment / "minhash" / "pdfs" / "no_ocr_extraction"

# jsonl_folder = Path(__file__).parent.parent.parent / "output" / segment / "final_data" / "html"
jsonl_folder = Path(__file__).parent.parent.parent / "output" / segment / "final_data" / "pdfs"

experiments_folder = Path(__file__).parent.parent.parent / "experiments"
experiments_folder.mkdir(exist_ok=True)
output_file = experiments_folder / f"read_jsonl_zst_output_{segment}.txt"

# Find all jsonl.zst files in the folder
jsonl_files = sorted(jsonl_folder.glob("*.jsonl.zst"))

if not jsonl_files:
    print(f"No .jsonl.zst files found in: {jsonl_folder}")
    exit(1)

print(f"Found {len(jsonl_files)} .jsonl.zst files to process")
print(f"Processing files from: {jsonl_folder}")

total_docs = 0

with open(output_file, "w", encoding="utf-8",) as out_f:
    for jsonl_file in jsonl_files:
        print(f"Processing: {jsonl_file.name}")
        
        dctx = zstd.ZstdDecompressor()
        with open(jsonl_file, "rb") as fh, dctx.stream_reader(fh) as reader:
            import io
            f = io.TextIOWrapper(reader, encoding="utf-8")
            for i, line in enumerate(f):
                doc = json.loads(line)
                out_f.write("#" * 40 + " New Document " + "#" * 40 + "\n")
                out_f.write(f"## File: {jsonl_file.name}\n")
                out_f.write(f"## Url: {doc.get('metadata', {}).get('url', '')}\n")
                out_f.write(f"## Tokens: {doc.get('metadata', {}).get('token_count')}\n")
                out_f.write("\n")
                out_f.write("## Text preview:\n")
                out_f.write(doc.get("text", "")+ "\n")
                out_f.write("\n")
                out_f.write("## Content bytes preview:\n")
                media = doc.get("media", [])
                if media and len(media) > 0:
                    content_bytes_b64 = media[0].get("metadata", {}).get("content_bytes", "")
                    if content_bytes_b64:
                        # Check if it's a placeholder string (not base64)
                        if content_bytes_b64 == "<content decoded and stored in text field>":
                            out_f.write("Content was decoded and stored in text field (HTML document)\n")
                        elif content_bytes_b64 == "<text extracted (no ocr)>":
                            out_f.write("Content was extracted and stored in text field (PDF document, no OCR)\n")
                        else:
                            try:
                                content_bytes = base64.b64decode(content_bytes_b64)
                                out_f.write(f"First 1000 bytes (decoded): {content_bytes[:100]}\n")
                            except Exception as e:
                                out_f.write(f"Error decoding content_bytes: {e}\n")
                    else:
                        out_f.write("No content_bytes found\n")
                else:
                    out_f.write("No media found\n")
                out_f.write("#" * 80 + "\n")
                out_f.write("\n")
                
                total_docs += 1
                
                # if total_docs == 3:
                #     break

print(f"\nTotal documents processed: {total_docs}")
print(f"Content written to: {output_file}")