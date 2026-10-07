import os
import time
import logging
try:
    import requests
except ImportError:
    requests = None
from typing import List, Dict, Any, Optional
from pathlib import Path
from backend.config import settings

logger = logging.getLogger(__name__)

class ParsedElement:
    def __init__(
        self,
        text: str,
        page: int,
        bboxes: List[Dict[str, float]],
        heading_path: List[str],
        elem_type: str = "paragraph",
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.text = text
        self.page = page
        self.bboxes = bboxes
        self.heading_path = heading_path
        self.elem_type = elem_type
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "page": self.page,
            "bboxes": self.bboxes,
            "heading_path": self.heading_path,
            "elem_type": self.elem_type,
            "metadata": self.metadata,
        }

class DoclingParser:
    def __init__(self, docling_url: str = settings.DOCLING_URL):
        self.docling_url = docling_url.rstrip("/")

    def parse_file(self, filepath: str, pdf_path: Optional[str] = None) -> List[ParsedElement]:
        """
        Parses document using Docling-serve if available, preserving headings,
        tables, lists, and page + bounding-box provenance for highlighting.
        Falls back to structure-aware PyMuPDF parser if Docling-serve is unavailable.
        """
        file_to_parse = pdf_path if pdf_path and os.path.exists(pdf_path) else filepath
        
        # 1. Try Docling-serve
        try:
            elements = self._parse_with_docling_serve(file_to_parse)
            if elements:
                logger.info(f"Successfully parsed {len(elements)} elements via Docling-serve.")
                return elements
        except Exception as e:
            logger.warning(f"Docling-serve failed or unavailable ({e}). Using PyMuPDF fallback.")

        # 2. Structure-aware Fallback via PyMuPDF / Text extractor
        return self._parse_with_pymupdf(file_to_parse)

    def _parse_with_docling_serve(self, filepath: str) -> Optional[List[ParsedElement]]:
        with open(filepath, "rb") as f:
            mime = "application/pdf" if filepath.endswith(".pdf") else "application/octet-stream"
            r = requests.post(
                f"{self.docling_url}/v1/convert/file",
                files={"files": (os.path.basename(filepath), f, mime)},
                timeout=15,
            )
        if r.status_code != 200:
            return None

        data = r.json()
        doc_json = None

        if "document" in data:
            doc_json = data["document"]
        elif "task_id" in data:
            task_id = data["task_id"]
            # Poll async task
            for _ in range(60):
                time.sleep(2)
                pr = requests.get(f"{self.docling_url}/v1/result/{task_id}", timeout=10)
                if pr.status_code == 200:
                    res = pr.json()
                    status = res.get("task_status", "")
                    if status in ("success", "completed", "done"):
                        doc_json = res.get("document")
                        break
                    elif status in ("failure", "failed", "error"):
                        break

        if not doc_json:
            return None

        return self._extract_docling_elements(doc_json)

    def _extract_docling_elements(self, doc_json: Dict[str, Any]) -> List[ParsedElement]:
        elements: List[ParsedElement] = []
        heading_stack: List[str] = []

        # Docling schema typically has texts, tables, and provenance
        texts = doc_json.get("texts", [])
        tables = doc_json.get("tables", [])

        # Process texts
        for item in texts:
            text = item.get("text", "").strip()
            if not text:
                continue

            label = item.get("label", "paragraph")
            prov_list = item.get("prov", [])
            bboxes = []
            page = 1

            for prov in prov_list:
                page = prov.get("page_no", 1)
                bbox_dict = prov.get("bbox", {})
                if bbox_dict:
                    bboxes.append({
                        "x0": bbox_dict.get("l", 0.0),
                        "y0": bbox_dict.get("t", 0.0),
                        "x1": bbox_dict.get("r", 0.0),
                        "y1": bbox_dict.get("b", 0.0),
                        "page": page,
                        "coord_origin": bbox_dict.get("coord_origin", "BOTTOMLEFT")
                    })

            if "heading" in label or "title" in label:
                heading_stack = [text]
                elem_type = "heading"
            else:
                elem_type = "paragraph"

            elements.append(
                ParsedElement(
                    text=text,
                    page=page,
                    bboxes=bboxes,
                    heading_path=list(heading_stack),
                    elem_type=elem_type,
                    metadata={"docling_label": label}
                )
            )

        # Process tables
        for table in tables:
            md_table = table.get("data", {}).get("markdown") or table.get("text", "")
            if not md_table.strip():
                continue

            prov_list = table.get("prov", [])
            bboxes = []
            page = 1
            for prov in prov_list:
                page = prov.get("page_no", 1)
                bbox_dict = prov.get("bbox", {})
                if bbox_dict:
                    bboxes.append({
                        "x0": bbox_dict.get("l", 0.0),
                        "y0": bbox_dict.get("t", 0.0),
                        "x1": bbox_dict.get("r", 0.0),
                        "y1": bbox_dict.get("b", 0.0),
                        "page": page,
                        "coord_origin": bbox_dict.get("coord_origin", "BOTTOMLEFT")
                    })

            elements.append(
                ParsedElement(
                    text=f"[TABLE]\n{md_table}",
                    page=page,
                    bboxes=bboxes,
                    heading_path=list(heading_stack),
                    elem_type="table",
                    metadata={"is_table": True}
                )
            )

        return elements

    def _parse_with_pymupdf(self, filepath: str) -> List[ParsedElement]:
        """
        Structure-aware extraction using PyMuPDF (fitz).
        Extracts blocks, font sizes, headings, tables, and bounding boxes.
        """
        import fitz

        elements: List[ParsedElement] = []
        heading_stack: List[str] = []

        try:
            doc = fitz.open(filepath)
        except Exception as e:
            logger.error(f"Cannot open file with PyMuPDF: {e}")
            return []

        for page_idx in range(len(doc)):
            page_num = page_idx + 1
            page = doc[page_idx]
            page_rect = page.rect
            width, height = page_rect.width, page_rect.height

            # Extract tables first if possible
            tables = []
            try:
                tabs = page.find_tables()
                for tab in tabs:
                    table_md = tab.extract()
                    # Convert list of rows to markdown table
                    if table_md and len(table_md) > 0:
                        header = table_md[0]
                        header_line = "| " + " | ".join(str(c or "").replace("\n", " ") for c in header) + " |"
                        sep_line = "| " + " | ".join("---" for _ in header) + " |"
                        body_lines = [
                            "| " + " | ".join(str(c or "").replace("\n", " ") for c in row) + " |"
                            for row in table_md[1:]
                        ]
                        full_table_text = "\n".join([header_line, sep_line] + body_lines)
                        t_rect = tab.bbox
                        tables.append({
                            "text": f"[TABLE]\n{full_table_text}",
                            "bbox": {
                                "x0": t_rect[0], "y0": t_rect[1],
                                "x1": t_rect[2], "y1": t_rect[3],
                                "page": page_num,
                                "page_width": width, "page_height": height,
                                "coord_origin": "TOPLEFT"
                            }
                        })
            except Exception:
                pass

            for t in tables:
                elements.append(
                    ParsedElement(
                        text=t["text"],
                        page=page_num,
                        bboxes=[t["bbox"]],
                        heading_path=list(heading_stack),
                        elem_type="table",
                        metadata={"is_table": True}
                    )
                )

            # Extract text blocks
            # block format: (x0, y0, x1, y1, text, block_no, block_type)
            blocks = page.get_text("blocks")
            for b in blocks:
                if len(b) < 5:
                    continue
                x0, y0, x1, y1, btext = b[0], b[1], b[2], b[3], b[4]
                text = btext.strip()
                if not text or len(text) < 2:
                    continue

                # Heuristic for headings: lines starting with # or very short lines with high font
                is_heading = False
                lines = text.splitlines()
                first_line = lines[0].strip() if lines else ""
                if first_line.startswith("#") or (len(first_line) < 60 and first_line.isupper() and len(lines) == 1):
                    is_heading = True
                    heading_stack = [first_line.lstrip("#").strip()]

                bbox = {
                    "x0": float(x0),
                    "y0": float(y0),
                    "x1": float(x1),
                    "y1": float(y1),
                    "text": text,
                    "page": page_num,
                    "page_width": float(width),
                    "page_height": float(height),
                    "coord_origin": "TOPLEFT"
                }

                elements.append(
                    ParsedElement(
                        text=text,
                        page=page_num,
                        bboxes=[bbox],
                        heading_path=list(heading_stack),
                        elem_type="heading" if is_heading else "paragraph",
                        metadata={"block_type": b[6] if len(b) > 6 else 0}
                    )
                )

        doc.close()
        return elements

docling_parser = DoclingParser()
