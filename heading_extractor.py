import fitz  # PyMuPDF
import pdfplumber
import re
from PIL import Image
import pytesseract
import io
from difflib import SequenceMatcher

def similar(a, b):
    return SequenceMatcher(None, a, b).ratio() > 0.85

def clean_text(text):
    if not text:
        return ''
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) < 3 or text.isdigit() or re.match(r'^Page \d+', text):
        return ''
    return text

def is_within_bboxes(line_bbox, table_bboxes, allow_above_margin=15):
    """
    Checks if a line is inside a table or just above it.
    Returns 'is_header', 'is_inside', or None.
    """
    for table_bbox in table_bboxes:
        horizontally_aligned = (line_bbox[0] < table_bbox[2] and line_bbox[2] > table_bbox[0])
        is_just_above = (line_bbox[3] >= table_bbox[1] - allow_above_margin and line_bbox[3] <= table_bbox[1] + 5)
        if horizontally_aligned and is_just_above:
            return 'is_header'
        is_inside = (line_bbox[0] >= table_bbox[0] and line_bbox[1] >= table_bbox[1] and
                     line_bbox[2] <= table_bbox[2] and line_bbox[3] <= table_bbox[3])
        if is_inside:
            return 'is_inside'
    return None



def get_true_table_bboxes(plumber_page, fitz_page):
    """
    Identifies "true" tables by robustly filtering out single-cell boxes that
    are visually identifiable as styled headings.
    """
    true_table_bboxes = []
    # We need the page's base font size to know if text is "larger than normal".
    base_font_size = get_base_font_size(fitz_page) 

    try:
        # Find all potential tables on the page.
        found_tables = plumber_page.find_tables()
    except Exception:
        # If pdfplumber fails for any reason on a page, return an empty list.
        return []

    for table in found_tables:
        # Rule 1: Multi-row or multi-column tables are ALWAYS considered real.
        # This is the strongest and most reliable indicator.
        if len(table.rows) > 1 or (len(table.rows) > 0 and len(table.rows[0].cells) > 1):
            true_table_bboxes.append(table.bbox)
            continue

        # From here, we are only analyzing suspicious 1x1 boxes.
        if len(table.rows) == 1 and len(table.rows[0].cells) == 1:
            # Extract the content from the single cell.
            cell_content = table.extract()[0][0]
            if not cell_content: continue # Ignore empty graphical boxes.

            # Rule 2: A styled heading is short. A real text box might have paragraphs.
            if len(cell_content.strip().split()) > 8:
                true_table_bboxes.append(table.bbox) # Too long for a heading, probably a text box.
                continue

            # Rule 3: Check the font style of the text inside the box.
            # This is the definitive test.
            words_in_cell = plumber_page.crop(table.bbox).extract_words(keep_blank_chars=True)
            if not words_in_cell:
                true_table_bboxes.append(table.bbox) # It's a graphical box with no text.
                continue

            # Get the style of the first word as a representative sample.
            font_size = words_in_cell[0].get('size', 10)
            font_name = words_in_cell[0].get('fontname', '').lower()
            is_bold = 'bold' in font_name or 'heavy' in font_name
            is_significantly_larger = font_size > (base_font_size * 1.1)

            # If the text is short AND stylistically prominent, it is a HEADING. REJECT IT.
            if (is_bold or is_significantly_larger):
                # This is our styled heading (e.g., "Background"). Do not add it to the list.
                continue

        # If a 1x1 box survives all the checks, we assume it's a legitimate text box.
        true_table_bboxes.append(table.bbox)
            
    return true_table_bboxes

def is_heading_candidate(text, span, line_bbox, page_height, base_font_size=10):
    """
    Determines if a line is a heading using stricter, more robust rules,
    including a check to filter out potential footers.
    """
    # --- NEW Negative Constraint: Filter out footers ---
    # Reject text that is in the bottom 10% of the page.
    if line_bbox[3] > (page_height * 0.9):
        return False
    # ---------------------------------------------------

    text_stripped = text.strip()
    if not text_stripped: return False
    word_count = len(text_stripped.split())

    if word_count > 15 or (text_stripped.endswith('.') and word_count > 8): return False
    if text_stripped.lower() in ["version", "date", "remarks", "identifier", "reference"]: return False

    font_size = span.get('size', 10)
    is_bold = ('bold' in span.get('font', '').lower() or (span.get('flags', 0) & 16))
    
    if (re.match(r'^\d+(\.\d+)*\s', text_stripped) and word_count < 12) or \
       re.match(r'^(Appendix|Chapter|Section|Phase|Table|Figure)\s+[A-Z0-9]', text_stripped, re.IGNORECASE):
        return True

    is_significantly_larger = font_size > (base_font_size * 1.15)
    if (is_bold or is_significantly_larger) and word_count < 10 and not text_stripped.endswith(('.', ',', ';')):
        return True
    
    return False

def determine_heading_level(text, span, base_font_size=10):
    """Assigns a heading level based on patterns and relative font size."""
    if re.match(r'^\d+\.\d+\.\d+', text): return "H3"
    if re.match(r'^\d+\.\d+', text): return "H2"
    if re.match(r'^\d+', text): return "H1"
    
    font_size = span.get('size', 10)
    if font_size > base_font_size * 1.8: return "H1"
    if font_size > base_font_size * 1.5: return "H2"
    if font_size > base_font_size * 1.2: return "H3"
    
    return "H4"



def extract_title_from_first_page(doc, plumber_doc):
    """
    Extracts the title from the visual layout of the first page.
    This version is now robust against pages with no text blocks.
    """
    page = doc[0]
    plumber_page = plumber_doc.pages[0] 

    # --- THIS IS THE FIX ---
    # 1. Get the text dictionary safely.
    blocks_dict = page.get_text("dict")
    
    # 2. Add the defensive check. If it's None or has no 'blocks' key, proceed to Stage 2.
    if not blocks_dict or 'blocks' not in blocks_dict:
        # If there are no text blocks, we can't use the font-size method.
        # Skip directly to the form-based fallback.
        pass
    else:
        # --- Stage 1: Try to find prominent text (large font size) ---
        # This code now only runs if blocks_dict is valid.
        line_candidates = []
        for l in (line for b in blocks_dict["blocks"] for line in b.get("lines", [])):
            if not l.get("spans") or l['bbox'][1] > page.rect.height * 0.5:
                continue
            
            line_text = "".join(s["text"] for s in l["spans"]).strip()
            first_span = l["spans"][0]
            
            if line_text and first_span['size'] > 14:
                line_candidates.append({"text": line_text, "size": first_span['size']})
                
        if line_candidates:
            line_candidates.sort(key=lambda x: -x['size'])
            main_title_size = line_candidates[0]['size']
            title_lines = [lc['text'] for lc in line_candidates if abs(lc['size'] - main_title_size) < 2]
            return " ".join(title_lines)

    # --- Stage 2: Fallback for forms (find first non-table text) ---
    print("Info: No prominent title candidate found on page 1. Using fallback for forms.")
    table_bboxes = get_true_table_bboxes(plumber_page)
    
    # We need to get the blocks_dict again if it was None before.
    if not blocks_dict or 'blocks' not in blocks_dict:
        blocks_dict = page.get_text("dict")
        if not blocks_dict or 'blocks' not in blocks_dict:
            return "Untitled Document" # No text at all on the page.

    for l in (line for b in blocks_dict["blocks"] for line in b.get("lines", [])):
        if not l.get("spans") or l['bbox'][1] > page.rect.height * 0.5:
            continue
        if is_within_bboxes(l['bbox'], table_bboxes) is None:
            title = clean_text("".join(s['text'] for s in l['spans']))
            if title:
                return title
            
    return "Untitled Document"

def is_bbox_inside(bbox1, bbox2, tolerance=1):
    """Checks if bbox1 is completely inside bbox2 with a small tolerance."""
    return (bbox1[0] >= bbox2[0] - tolerance and
            bbox1[1] >= bbox2[1] - tolerance and
            bbox1[2] <= bbox2[2] + tolerance and
            bbox1[3] <= bbox2[3] + tolerance)

def process_page(fitz_page, plumber_page, page_num, seen_headings):
    """
    Processes a page using the final, robust two-pass approach.
    This version correctly creates candidate dictionaries with 'size' in both passes.
    """
    form_content = get_form_xobject_text(fitz_page)
    for text in form_content:
        seen_headings.add(text)

    # This list will hold candidate dictionaries, each with a 'size' key.
    heading_candidates = []
    base_font_size = get_base_font_size(fitz_page)
    
    table_bboxes = get_true_table_bboxes(plumber_page, fitz_page)
    all_lines = [line for block in fitz_page.get_text("dict")['blocks'] for line in block.get("lines", []) if line.get("spans")]
    processed_line_indices = set()

    # Pass 1: Find Headings Inside Graphical Rectangles
    rects = plumber_page.rects
    if rects:
        for rect in rects:
            lines_in_rect = []
            for i, line in enumerate(all_lines):
                if is_bbox_inside(line['bbox'], (rect['x0'], rect['top'], rect['x1'], rect['bottom'])):
                    lines_in_rect.append((i, line))
            
            if lines_in_rect:
                full_text = " ".join([clean_text("".join(s['text'] for s in line['spans'])) for _, line in lines_in_rect])
                cleaned = clean_text(full_text)
                
                if cleaned and cleaned.lower() not in seen_headings:
                    first_line_span = lines_in_rect[0][1]['spans'][0]
                    # --- FIX IS HERE ---
                    # Create a candidate dict that INCLUDES the 'size' key.
                    heading_candidates.append({
                        "size": first_line_span['size'], 
                        "text": cleaned, 
                        "page": page_num
                    })
                    # ------------------
                    seen_headings.add(cleaned.lower())
                    for i, _ in lines_in_rect:
                        processed_line_indices.add(i)

    # Pass 2: Find Standard Headings (and Table Headers)
    for i, line in enumerate(all_lines):
        if i in processed_line_indices:
            continue

        line_text = "".join(span["text"] for span in line["spans"]).strip()
        cleaned = clean_text(line_text)
        if not cleaned or cleaned.lower() in seen_headings:
            continue

        status = is_within_bboxes(line['bbox'], table_bboxes)
        first_span = line['spans'][0]
        
        if status == 'is_header':
            # --- FIX IS HERE ---
            heading_candidates.append({
                "size": first_span['size'], 
                "text": cleaned, 
                "page": page_num
            })
            # ------------------
            seen_headings.add(cleaned.lower())
        elif status is None:
            if is_heading_candidate(cleaned, first_span, line['bbox'], fitz_page.rect.height, base_font_size):
                # --- FIX IS HERE ---
                heading_candidates.append({
                    "size": first_span['size'], 
                    "text": cleaned, 
                    "page": page_num
                })
                # ------------------
                seen_headings.add(cleaned.lower())

    return heading_candidates
    
def extract_title_from_metadata(doc):
    """
    Extracts the document title from the PDF's metadata (Info dictionary).
    This is the most reliable method if the metadata is present.
    """
    metadata = doc.metadata
    if metadata and 'title' in metadata and metadata['title']:
        # Sometimes titles are encoded strangely, clean it up.
        title = metadata['title']
        # A common issue is generic titles, we can filter these out.
        if title.lower() not in ["untitled", "microsoft word document"]:
             return clean_text(title)
    return None # Return None if no suitable title is found

def extract_outline_from_toc(doc):
    """
    Extracts the entire document outline from the PDF's internal Table of Contents
    (the "Outline Tree" or bookmarks). This is the fastest and most accurate method.
    """
    toc = doc.get_toc(simple=False)
    if not toc:
        return None # No ToC found

    headings = []
    for entry in toc:
        level = f"H{entry[0]}" # Level is the first item
        text = clean_text(entry[1])  # Title is the second item
        page_num = entry[2]        # Page number is the third item
        
        if text:
            headings.append({"level": level, "text": text, "page": page_num})
            
    return headings if headings else None

def extract_outline(pdf_path, max_pages=None, dpi=300):
    """
    Main extraction function using the full hybrid approach.
    This version correctly processes all pages for headings and uses a
    post-processing step for accurate level detection.
    """
    try:
        doc = fitz.open(pdf_path)
        plumber_doc = pdfplumber.open(pdf_path)
    except Exception as e:
        return {"error": f"Failed to open PDF: {e}"}

    title = extract_title_from_metadata(doc)
    if not title:
        title = clean_text(extract_title_from_first_page(doc, plumber_doc))

    headings = extract_outline_from_toc(doc)
    
    if headings is None:
        print("Info: No ToC/bookmarks found. Falling back to page-by-page visual analysis.")
        
        # --- THIS ENTIRE BLOCK IS THE UPGRADED LOGIC ---
        
        # 1. Create a list to hold candidates with their style info.
        heading_candidates = []
        seen_headings = set()
        if title:
            seen_headings.add(title.lower())
        
        page_count = min(len(doc), max_pages if max_pages else len(doc))
        
        # 2. FIX #1: Loop through ALL pages, starting from the first page (index 0).
        for i in range(page_count):
            fitz_page = doc[i]
            plumber_page = plumber_doc.pages[i]
            if plumber_page is None:
                continue
            
            if is_toc_page(fitz_page):
                print(f"Info: Page {i + 1} detected as a Table of Contents, skipping visual analysis.")
                continue
            
            # process_page now returns a list of candidates with font sizes.
            page_candidates = process_page(fitz_page, plumber_page, i + 1, seen_headings)
            heading_candidates.extend(page_candidates)
        
        # 3. FIX #2: Call the new post-processor to assign final levels.
        headings = post_process_and_level_headings(heading_candidates)
        # --------------------------------------------------------

    doc.close()
    plumber_doc.close()

    # The final cleanup is now more important to remove the title if it was found as a heading.
    final_headings = [h for h in headings if not similar(h['text'], title)]

    return {
        "title": title,
        "outline": final_headings
    }


def get_base_font_size(page, percentile=50):
    """
    Calculates the most common (median) font size on the page, now with a
    defensive check for pages with no text blocks.
    """
    try:
        # --- THIS IS THE FIX ---
        # 1. Get the text dictionary safely.
        blocks_dict = page.get_text("dict")
        
        # 2. Add the defensive check. If it's None or has no 'blocks' key, return a default.
        if not blocks_dict or 'blocks' not in blocks_dict:
            return 10 

        # 3. Only proceed if the dictionary is valid.
        font_sizes = [
            s['size'] 
            for b in blocks_dict['blocks'] 
            for l in b.get("lines", []) 
            for s in l.get("spans", [])
        ]
        # -----------------------

        if not font_sizes:
            return 10
        
        # Use median to find the most common font size
        return sorted(font_sizes)[int(len(font_sizes) * percentile / 100)]
    except Exception:
        # Return a default on any other unexpected error
        return 10

def get_form_xobject_text(page):
    """
    Analyzes a page to find all text that originates from a Form XObject.
    This is a reliable way to identify and filter repeating content like headers and footers.
    Returns a set of cleaned text strings found within forms.
    """
    form_text_content = set()
    # A page's resources include its XObjects (which can be Forms or Images)
    xobjects = page.get_xobjects()
    
    for _, xref in xobjects:
        try:
            # An XObject is a stream. We can load it to inspect it.
            stream = fitz.open("pdf", page.parent.xref_stream(xref))
            
            # fitz has a property to check if the XObject is a Form
            if stream[0].is_form_xobject:
                # If it is, extract all of its text content
                form_text = stream[0].get_text("text")
                cleaned_text = clean_text(form_text)
                if cleaned_text:
                    form_text_content.add(cleaned_text.lower())
            stream.close()
        except Exception:
            # If we fail to parse an XObject, just skip it.
            continue
            
    return form_text_content

def parse_poster_page_as_headings(page, page_num, seen_headings):
    """
    Parses a poster-style page and maps its content to the standard heading format.
    """
    headings = []
    # Use get_text("words") which includes font size information
    words = page.get_text("words")
    if not words: return []

    # Group words into lines based on vertical position (y1)
    lines = {}
    for w in words:
        y1 = round(w[3]) # Use the bottom coordinate of the word as the line key
        if y1 not in lines:
            lines[y1] = []
        lines[y1].append(w)

    # Sort lines by vertical position
    sorted_lines = sorted(lines.items())

    for _, line_words in sorted_lines:
        line_words.sort(key=lambda w: w[0]) # Sort words by horizontal position
        
        # Reconstruct line text and get average font size
        line_text = " ".join([w[4] for w in line_words])
        avg_font_size = sum(w[5] for w in line_words) / len(line_words)
        
        cleaned = clean_text(line_text)
        if cleaned and cleaned.lower() not in seen_headings:
            # Classify level based on absolute font size for posters
            level = "H4"
            if avg_font_size > 36: level = "H1"
            elif avg_font_size > 24: level = "H2"
            elif avg_font_size > 18: level = "H3"
            
            headings.append({"level": level, "text": cleaned, "page": page_num})
            seen_headings.add(cleaned.lower())
            
    return headings

def parse_standard_page_as_headings(fitz_page, plumber_page, page_num, seen_headings):
    """
    The original logic for parsing standard, text-heavy document pages.
    """
    headings = []
    base_font_size = get_base_font_size(fitz_page)
    table_bboxes = get_true_table_bboxes(plumber_page)

    blocks_dict = fitz_page.get_text("dict")
    if not blocks_dict or 'blocks' not in blocks_dict:
        return []
    all_lines = [line for block in blocks_dict['blocks'] for line in block.get("lines", []) if line.get("spans")]

    # Pass 1: Find table headers
    for line in all_lines:
        if is_within_bboxes(line['bbox'], table_bboxes) == 'is_header':
            line_text = "".join(span["text"] for span in line["spans"]).strip()
            cleaned = clean_text(line_text)
            if cleaned and cleaned.lower() not in seen_headings:
                level = determine_heading_level(cleaned, line['spans'][0], base_font_size)
                headings.append({"level": level, "text": cleaned, "page": page_num})
                seen_headings.add(cleaned.lower())

    # Pass 2: Find standalone headings
    for line in all_lines:
        line_text = "".join(span["text"] for span in line["spans"]).strip()
        cleaned = clean_text(line_text)
        if not cleaned or cleaned.lower() in seen_headings:
            continue
        if is_within_bboxes(line['bbox'], table_bboxes) in ['is_header', 'is_inside']:
            continue
        if is_heading_candidate(cleaned, line['spans'][0], base_font_size):
            level = determine_heading_level(cleaned, line['spans'][0], base_font_size)
            headings.append({"level": level, "text": cleaned, "page": page_num})
            seen_headings.add(cleaned.lower())
            
    return headings


def is_toc_page(page):
    """
    Heuristically determines if a page is a Table of Contents by checking for
    a high density of lines that end with a page number.
    """
    lines = page.get_text("text").strip().split('\n')
    # A page with very few lines is unlikely to be a ToC.
    if len(lines) < 10:
        return False

    lines_ending_in_number = 0
    for line in lines:
        # A typical ToC line ends with dots/spaces and then a number.
        if re.search(r'[\s\.]+\d+$', line.strip()):
            lines_ending_in_number += 1
    
    # If more than 40% of the lines fit the ToC pattern, classify the page as a ToC.
    if (lines_ending_in_number / len(lines)) > 0.4:
        return True
        
    return False


def ocr_page(fitz_page, dpi=300):
    """
    Performs OCR on a Fitz page object at a specified DPI.
    """
    try:
        pix = fitz_page.get_pixmap(dpi=dpi)
        img_data = pix.tobytes("png")
        image = Image.open(io.BytesIO(img_data))
        return pytesseract.image_to_string(image)
    except Exception as e:
        print(f"Error: OCR failed on page {fitz_page.number + 1}: {e}")
        return ""

def parse_ocr_text_as_headings(ocr_text, page_num, seen_headings):
    """
    A simple parser for OCR text. It treats any short, non-sentence line as a heading.
    """
    headings = []
    for line in ocr_text.split('\n'):
        cleaned = clean_text(line)
        word_count = len(cleaned.split())
        if cleaned and cleaned.lower() not in seen_headings:
            # Simple heuristic: if it's short and doesn't end like a sentence, it's a heading.
            if word_count > 0 and word_count < 10 and not cleaned.endswith(('.', '!', '?')):
                 headings.append({"level": "H4", "text": cleaned, "page": page_num})
                 seen_headings.add(cleaned.lower())
    return headings

def post_process_and_level_headings(heading_candidates):
    """
    Analyzes a flat list of heading candidates to assign final H1, H2, etc.,
    levels based on the relative ranking of their font sizes.
    """
    if not heading_candidates:
        return []

    # Get all unique font sizes from the candidates, sorted from largest to smallest
    font_sizes = sorted(list(set([h['size'] for h in heading_candidates])), reverse=True)
    
    # Create a mapping from a font size to a heading level
    size_to_level_map = {size: f"H{i + 1}" for i, size in enumerate(font_sizes)}

    leveled_headings = []
    for candidate in heading_candidates:
        # Assign the final level to each candidate based on its font size
        level = size_to_level_map.get(candidate['size'], "H4") # Default to a lower level
        leveled_headings.append({
            "level": level,
            "text": candidate['text'],
            "page": candidate['page']
        })

    return leveled_headings

import argparse
import json

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Extract a structured outline (title and headings) from a PDF file using a hybrid, adaptive strategy.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("pdf_path", help="The full path to the PDF file to process.")
    parser.add_argument("-o", "--output", help="Optional: Path to save the output as a JSON file.", default=None)
    parser.add_argument("--max_pages", type=int, default=None, help="Optional: Maximum number of pages to process.")
    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="Resolution (DPI) for OCR processing on scanned pages. Default: 300."
    )
    args = parser.parse_args()

    try:
        extracted_data = extract_outline(args.pdf_path, args.max_pages, args.dpi)
        
        if "error" in extracted_data:
            print(f"\nAn error occurred: {extracted_data['error']}")
        else:
            print("\n" + "="*50)
            print(f"DOCUMENT TITLE: {extracted_data.get('title', 'N/A')}")
            print("="*50)
            
            # Handle both outline and poster/form output formats
            if 'outline' in extracted_data:
                print("\nEXTRACTED OUTLINE:")
                for heading in extracted_data['outline']:
                    print(f"  - [Page {heading['page']}] [{heading['level']}] {heading['text']}")
            elif 'form_data' in extracted_data:
                 print("\nEXTRACTED FORM DATA:")
                 for key, value in extracted_data['form_data'].items():
                     print(f"  - {key}: {value}")
                 print("\nOTHER TEXT BLOCKS:")
                 for block in extracted_data['text_blocks']:
                     print(f"  - {block}")

        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(extracted_data, f, ensure_ascii=False, indent=4)
            print(f"\nSuccessfully saved structured output to: {args.output}")

    except FileNotFoundError:
        print(f"Error: The file '{args.pdf_path}' was not found.")
    except Exception as e:
        print(f"An unexpected and critical error occurred: {e}")

