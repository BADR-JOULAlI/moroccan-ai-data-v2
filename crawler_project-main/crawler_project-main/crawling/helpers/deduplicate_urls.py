"""
Script to remove duplicate URLs from a text file.
Ignores differences in protocol (http/https) and www prefix.
"""

from urllib.parse import urlparse
from pathlib import Path
import re


def normalize_url(url):
    """
    Normalize a URL by removing protocol, www, and trailing slashes.
    This allows us to identify duplicates regardless of these differences.
    
    Args:
        url: The URL string to normalize
        
    Returns:
        A normalized version of the URL for comparison
    """
    # Remove leading/trailing whitespace
    url = url.strip()
    
    # Skip empty lines or comments
    if not url or url.startswith('#'):
        return None
    
    # Remove protocol (http:// or https://)
    url_without_protocol = re.sub(r'^https?://', '', url, flags=re.IGNORECASE)
    
    # Remove www. prefix
    url_without_www = re.sub(r'^www\.', '', url_without_protocol, flags=re.IGNORECASE)
    
    # Remove trailing slashes
    url_normalized = url_without_www.rstrip('/')
    
    # Convert to lowercase for case-insensitive comparison
    return url_normalized.lower()


def remove_duplicate_urls(input_file, output_file):
    """
    Remove duplicate URLs from input file and write unique URLs to output file.
    
    Args:
        input_file: Path to the input file containing URLs
        output_file: Path to the output file for unique URLs
    """
    # Dictionary to store normalized URL -> original URL mapping
    unique_urls = {}
    
    # Lists to preserve comments and structure
    lines_to_write = []
    
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.rstrip('\n\r')
                
                # Preserve empty lines and comments (lines starting with #)
                if not line.strip() or line.strip().startswith('#'):
                    lines_to_write.append(line)
                    continue
                
                # Normalize the URL for comparison
                normalized = normalize_url(line)
                
                if normalized and normalized not in unique_urls:
                    # Store the original URL with its normalized version as key
                    unique_urls[normalized] = line
                    lines_to_write.append(line)
                else:
                    # This is a duplicate, we skip it
                    print(f"Duplicate found (skipped): {line}")
        
        # Write unique URLs to output file
        with open(output_file, 'w', encoding='utf-8') as f:
            for line in lines_to_write:
                f.write(line + '\n')
        
        print(f"\n✓ Processing complete!")
        print(f"  Total unique URLs: {len(unique_urls)}")
        print(f"  Output saved to: {output_file}")
        
    except FileNotFoundError:
        print(f"Error: Input file '{input_file}' not found.")
    except Exception as e:
        print(f"Error: {e}")


def main():
    """Main function to run the script."""
    import sys
    
    # Default file names - look in parent directory of the script
    input_file = Path(__file__).parent.parent / "file.txt"
    output_file = Path(__file__).parent.parent / "file_dedup.txt"
    
    # Check if command line arguments are provided
    if len(sys.argv) > 1:
        input_file = Path(sys.argv[1])  # Convert string to Path object
    if len(sys.argv) > 2:
        output_file = Path(sys.argv[2])  # Convert string to Path object
    
    print(f"Input file: {input_file}")
    print(f"Output file: {output_file}")
    print("-" * 50)
    
    remove_duplicate_urls(str(input_file), str(output_file))  # Convert Path to string for open()


if __name__ == "__main__":
    main()