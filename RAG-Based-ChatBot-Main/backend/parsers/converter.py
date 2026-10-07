import os
import shutil
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def convert_to_pdf(input_path: str, output_dir: str) -> str:
    """
    Ensures any supported file type (PDF, DOCX, PPTX, XLSX, TXT, HTML, Images)
    has a corresponding PDF version for viewer rendering.
    If the file is already a PDF, returns the existing path.
    Otherwise, converts it via LibreOffice (or Python fallback) and saves it to output_dir.
    """
    path = Path(input_path)
    ext = path.suffix.lower()

    if ext == ".pdf":
        return input_path

    os.makedirs(output_dir, exist_ok=True)
    pdf_filename = f"{path.stem}_{path.name.split('_')[0] if '_' in path.name else 'converted'}.pdf"
    output_pdf_path = os.path.join(output_dir, pdf_filename)

    if os.path.exists(output_pdf_path):
        return output_pdf_path

    # Try LibreOffice conversion
    soffice_cmd = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice_cmd:
        try:
            cmd = [
                soffice_cmd,
                "--headless",
                "--convert-to", "pdf",
                "--outdir", output_dir,
                input_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                expected_out = os.path.join(output_dir, f"{path.stem}.pdf")
                if os.path.exists(expected_out):
                    if expected_out != output_pdf_path:
                        shutil.move(expected_out, output_pdf_path)
                    return output_pdf_path
        except Exception as e:
            logger.warning(f"LibreOffice conversion failed for {input_path}: {e}")

    # Fallback conversion for images and plain text using PyMuPDF (fitz) or basic generator
    try:
        import fitz  # PyMuPDF
        doc = fitz.open()

        if ext in [".png", ".jpg", ".jpeg", ".bmp", ".webp"]:
            img_doc = fitz.open(input_path)
            rect = img_doc[0].rect
            page = doc.new_page(width=rect.width, height=rect.height)
            page.insert_image(rect, filename=input_path)
            doc.save(output_pdf_path)
            doc.close()
            return output_pdf_path

        elif ext in [".txt", ".html", ".md", ".csv", ".json"]:
            with open(input_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            # Split text into pages
            lines = content.splitlines()
            page_size = 50
            for i in range(0, max(1, len(lines)), page_size):
                page = doc.new_page()
                page_text = "\n".join(lines[i:i+page_size])
                page.insert_text((50, 50), page_text, fontsize=11)
            doc.save(output_pdf_path)
            doc.close()
            return output_pdf_path

    except Exception as e:
        logger.error(f"Fallback PDF generation failed: {e}")

    # If all else fails, return original path
    return input_path
