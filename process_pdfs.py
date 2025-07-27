import sys
from pathlib import Path
import json
from heading_extractor import extract_outline # Import our main function

def process_all_pdfs_in_directory():
    """
    Finds all PDF files in the /app/input directory, processes them to
    extract a structured outline, and saves the result as a JSON file
    in the /app/output directory.
    """
    input_dir = Path("/app/input")
    output_dir = Path("/app/output")

    # Ensure the output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    if not any(input_dir.iterdir()):
        print("Warning: Input directory is empty. Nothing to process.")
        return

    print(f"Starting processing for files in {input_dir}...")

    for pdf_file in input_dir.glob("*.pdf"):
        print(f"Processing: {pdf_file.name}")
        try:
            # Call our core extraction logic
            extracted_data = extract_outline(str(pdf_file))
            
            # Define the output path
            output_file_path = output_dir / f"{pdf_file.stem}.json"
            
            # Save the structured data as a JSON file
            with open(output_file_path, 'w', encoding='utf-8') as f:
                json.dump(extracted_data, f, ensure_ascii=False, indent=2)
            print(f"[SUCCESS] Saved output to {output_file_path}")

        except Exception as e:
            print(f"[ERROR] Failed to process {pdf_file.name}: {e}", file=sys.stderr)

if __name__ == '__main__':
    process_all_pdfs_in_directory()