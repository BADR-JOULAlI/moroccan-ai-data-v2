import gzip
import json
from pathlib import Path

# Folder containing jsonl.gz files
jsonl_folder = Path(__file__).parent.parent.parent / "output" / "base_processing" / "output" / "segment-2026-01"
# jsonl_folder = Path(__file__).parent.parent.parent / "output" / "minhash" / "segment-2026-01" / "final_data"

experiments_folder = Path(__file__).parent.parent.parent / "experiments"
experiments_folder.mkdir(exist_ok=True)
output_file = experiments_folder / "read_jsonl_output.txt"

# Find all jsonl.gz files in the folder
jsonl_files = sorted(jsonl_folder.glob("*.jsonl.gz"))

if not jsonl_files:
    print(f"No .jsonl.gz files found in: {jsonl_folder}")
    exit(1)

print(f"Found {len(jsonl_files)} .jsonl.gz files to process")
print(f"Processing files from: {jsonl_folder}")

total_docs = 0

with open(output_file, "w", encoding="utf-8",) as out_f:
    for jsonl_file in jsonl_files:
        print(f"Processing: {jsonl_file.name}")
        
        with gzip.open(jsonl_file, "rt", encoding="utf-8") as f:
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
                out_f.write("#" * 80 + "\n")
                out_f.write("\n")
                
                total_docs += 1
                
                # if total_docs == 3:
                #     break

print(f"\nTotal documents processed: {total_docs}")
print(f"Content written to: {output_file}")