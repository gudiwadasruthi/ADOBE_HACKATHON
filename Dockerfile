# Use the specified Python version on a standard linux/amd64 base
FROM --platform=linux/amd64 python:3.10-slim

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies, including Tesseract OCR Engine.
# The `tesseract-ocr-jpn` is for the bonus multilingual requirement.
# Add other languages here if needed (e.g., tesseract-ocr-hin for Hindi).
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-jpn \
    --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

# Copy the Python requirements file
COPY requirements.txt .

# Install Python libraries
RUN pip install --no-cache-dir -r requirements.txt

# Copy all our Python source code into the container
COPY *.py .

# Define the command to run when the container starts
CMD ["python", "process_pdfs.py"]