Adobe India Hackathon 2025 - Round 1A  
PDF Structure Extraction Solution  
Submitted by: [Your Name / Your Team Name]

## 1. Our Approach: A Hybrid, "Structure-First" Engine

Our solution is designed to be both incredibly fast and highly accurate by intelligently adapting its strategy to the type of PDF it is processing. The core philosophy is to trust the PDF's own structure first, and only use advanced visual analysis when that structure is missing.  

Think of it like trying to understand a book. The fastest way is to look at the Table of Contents. If the book doesn't have one, you then have to flip through the pages yourself, looking for big, bold chapter titles. Our script does exactly that, automatically.

This hybrid approach unfolds in two main stages:

**Stage 1: The "Structure-First" Method (The Fast Path)**  
When the script first opens a PDF, it doesn't immediately start scanning pages. It first looks for two "gold standard" pieces of information that well-made PDFs provide internally.

- **Finding the Title via Metadata:** The script first checks the PDF's metadata for an official "Title" entry. This is the document's self-declared title, making it the most reliable source.

- **Finding the Outline via Bookmarks:** Next, it checks if the PDF has a built-in Table of Contents (known as "bookmarks" or the "Outline Tree"). If it does, the script reads this entire structure in a single, lightning-fast operation. This gives us the complete, perfectly accurate list of all headings, their levels (H1, H2, etc.), and their page numbers.

If a PDF provides this structural information (as most professional reports or books do), our script can finish its job in a fraction of a second, with guaranteed accuracy.

**Stage 2: The "Visual Analysis" Fallback (The Smart Path)**  
Many PDFs, especially simpler or older ones, don't have a built-in Table of Contents. When our script detects this, it seamlessly switches to its powerful visual analysis engine. This engine is designed to read and understand the layout of each page, just like a human would.

This fallback is not just one simple process; it's a series of intelligent steps:

- **Proactive Header & Footer Filtering:** Before analyzing a page for headings, the script first identifies repeating content like company logos, page numbers, or confidentiality notices. It does this by recognizing a special PDF feature called "Form XObjects" (reusable content). This content is immediately tagged and ignored, preventing it from ever being mistaken for a heading.

- **Adaptive Page-Type Detection:** The engine is smart enough to know that not all pages are the same. It quickly analyzes the layout to determine what kind of page it's looking at:
  - A Standard Document Page: A typical page with paragraphs and headings.
  - A Poster or Form: A visually complex page with lots of images or scattered text.
  - A Scanned Image: A page with no digital text at all.
  Based on this diagnosis, it chooses the best tool for the job. For standard pages, it uses its most sophisticated analysis.

- **Relative Typographical Analysis:** This is the core of our heading detection. Instead of using fragile rules like "16pt font is always a heading," our engine is adaptive:
  - First, it scans the page to determine the most common font size, which we assume is the normal paragraph text.
  - Then, it defines a heading as any line of text that is stylistically different from this paragraph text—specifically, any text that is noticeably bolder or larger. This allows our script to adapt to any document's design, whether the main text is 9pt or 12pt.

- **Multi-Pass Layout Recognition:** To handle complex layouts with tables (like forms), the engine scans each page twice:
  - Pass 1: It looks for text that is positioned directly above a table, correctly identifying these as "table headers."
  - Pass 2: It then looks for all other standalone headings, making sure to ignore the text inside the tables.

- **OCR Safety Net:** If the adaptive detection identifies a page as a scanned image, the script automatically activates its OCR (Optical Character Recognition) engine. It converts the page to a high-resolution image and uses Tesseract OCR to read the text from the pixels, ensuring that even non-digital documents can be processed.

By combining this intelligent, multi-layered visual analysis with the "structure-first" approach, our solution is a robust, all-in-one tool that delivers both the speed required for simple, well-structured PDFs and the deep analytical power needed for complex, real-world documents.

## 2. Models and Libraries Used

No pre-trained ML models are used (model size = 0MB).  
Libraries:
- **PyMuPDF (fitz):** Fast PDF access, metadata, bookmarks, text extraction.
- **pdfplumber:** Robust table detection for visual analysis.
- **Pillow (PIL):** Image processing for OCR pipeline.
- **pytesseract:** Python wrapper for Tesseract-OCR.
- **Tesseract-OCR Engine:** Installed in Docker for text recognition.

## 3. How to Build and Run the Solution

The solution is containerized with Docker. All dependencies, including Tesseract OCR, are installed in the container.

**Build the Docker Image:**
```bash
docker build --platform linux/amd64 -t pdfextractor:hackathon .
```


**Run the Container:**
```bash
docker run --rm -v "%cd%\input:/app/input:ro" -v "%cd%\output:/app/output" --network none pdfextractor:hackathon
```
- `--rm`: Removes the container after processing.
- `-v $(pwd)/input:/app/input:ro`: Mounts your input directory (read-only).
- `-v $(pwd)/output:/app/output`: Mounts your output directory for results.
- `--network none`: No network access (challenge constraint).
- `pdfextractor:hackathon`: Docker image name.

Upon completion, the output directory will contain a `.json` file for each `.pdf` in the input directory.

---
