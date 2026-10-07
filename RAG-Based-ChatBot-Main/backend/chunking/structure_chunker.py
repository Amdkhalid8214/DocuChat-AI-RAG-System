import uuid
import re
from typing import List, Dict, Any, Optional
from backend.parsers.docling_parser import ParsedElement
from backend.config import settings

def estimate_tokens(text: str) -> int:
    """Approximate token count (whitespace + punctuation splitting or ~4 chars/token)."""
    words = re.findall(r"\w+|[^\w\s]", text, re.UNICODE)
    return max(1, len(words))

class Chunk:
    def __init__(
        self,
        chunk_id: str,
        doc_id: str,
        text: str,
        page: int,
        bboxes: List[Dict[str, Any]],
        heading_path: List[str],
        token_count: int,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.chunk_id = chunk_id
        self.doc_id = doc_id
        self.text = text
        self.page = page
        self.bboxes = bboxes
        self.heading_path = heading_path
        self.token_count = token_count
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "text": self.text,
            "page": self.page,
            "bboxes": self.bboxes,
            "heading_path": self.heading_path,
            "token_count": self.token_count,
            "metadata": self.metadata,
        }

class StructureChunker:
    def __init__(
        self,
        min_tokens: int = 300,
        max_tokens: int = 500,
        overlap_percent: float = 0.12
    ):
        self.min_tokens = min_tokens
        self.max_tokens = max_tokens
        self.overlap_tokens = int(max_tokens * overlap_percent)

    def chunk_elements(self, elements: List[ParsedElement], doc_id: str) -> List[Chunk]:
        """
        Groups parsed elements into structure-aware chunks respecting headings and tables.
        Accumulates bounding boxes, pages, and heading paths.
        """
        if not elements:
            return []

        chunks: List[Chunk] = []
        current_texts: List[str] = []
        current_bboxes: List[Dict[str, Any]] = []
        current_pages: List[int] = []
        current_headings: List[str] = []
        current_tokens = 0

        def flush_current():
            nonlocal current_texts, current_bboxes, current_pages, current_headings, current_tokens
            if not current_texts:
                return

            full_text = "\n\n".join(current_texts).strip()
            if not full_text:
                return

            primary_page = current_pages[0] if current_pages else 1
            chunk_obj = Chunk(
                chunk_id=str(uuid.uuid4()),
                doc_id=doc_id,
                text=full_text,
                page=primary_page,
                bboxes=list(current_bboxes),
                heading_path=list(current_headings),
                token_count=current_tokens,
                metadata={"page_list": list(set(current_pages))}
            )
            chunks.append(chunk_obj)

            # Compute overlap: keep the tail elements that fit within overlap_tokens
            overlap_acc_texts = []
            overlap_acc_bboxes = []
            overlap_acc_pages = []
            overlap_tokens_count = 0

            for t, b_list, p in zip(reversed(current_texts), reversed(current_bboxes), reversed(current_pages)):
                t_tokens = estimate_tokens(t)
                if overlap_tokens_count + t_tokens <= self.overlap_tokens:
                    overlap_acc_texts.insert(0, t)
                    if isinstance(b_list, list):
                        overlap_acc_bboxes.extend(b_list)
                    else:
                        overlap_acc_bboxes.append(b_list)
                    overlap_acc_pages.insert(0, p)
                    overlap_tokens_count += t_tokens
                else:
                    break

            current_texts = overlap_acc_texts
            current_bboxes = overlap_acc_bboxes
            current_pages = overlap_acc_pages
            current_tokens = overlap_tokens_count

        for elem in elements:
            elem_tokens = estimate_tokens(elem.text)

            # Case 1: Standalone Tables
            if elem.elem_type == "table":
                # Flush previous content first to keep table distinct
                if current_texts:
                    flush_current()

                # If table itself exceeds max_tokens, split by table lines
                if elem_tokens > self.max_tokens:
                    lines = elem.text.splitlines()
                    header = lines[:2] if len(lines) >= 2 else []
                    rows = lines[2:] if len(lines) >= 2 else lines

                    batch = []
                    batch_tok = estimate_tokens("\n".join(header))
                    for row in rows:
                        r_tok = estimate_tokens(row)
                        if batch_tok + r_tok > self.max_tokens and batch:
                            sub_text = "\n".join(header + batch)
                            chunks.append(Chunk(
                                chunk_id=str(uuid.uuid4()),
                                doc_id=doc_id,
                                text=sub_text,
                                page=elem.page,
                                bboxes=elem.bboxes,
                                heading_path=elem.heading_path,
                                token_count=batch_tok,
                                metadata={"is_table": True}
                            ))
                            batch = [row]
                            batch_tok = estimate_tokens("\n".join(header)) + r_tok
                        else:
                            batch.append(row)
                            batch_tok += r_tok

                    if batch:
                        sub_text = "\n".join(header + batch)
                        chunks.append(Chunk(
                            chunk_id=str(uuid.uuid4()),
                            doc_id=doc_id,
                            text=sub_text,
                            page=elem.page,
                            bboxes=elem.bboxes,
                            heading_path=elem.heading_path,
                            token_count=batch_tok,
                            metadata={"is_table": True}
                        ))
                else:
                    chunks.append(Chunk(
                        chunk_id=str(uuid.uuid4()),
                        doc_id=doc_id,
                        text=elem.text,
                        page=elem.page,
                        bboxes=elem.bboxes,
                        heading_path=elem.heading_path,
                        token_count=elem_tokens,
                        metadata={"is_table": True}
                    ))
                continue

            # Case 2: Heading
            if elem.elem_type == "heading":
                # If we already reached min_tokens, break cleanly at heading boundary
                if current_tokens >= self.min_tokens:
                    flush_current()
                current_headings = elem.heading_path

            # Case 3: Overflow check
            if current_tokens + elem_tokens > self.max_tokens and current_texts:
                flush_current()

            current_texts.append(elem.text)
            current_bboxes.extend(elem.bboxes)
            current_pages.append(elem.page)
            if elem.heading_path and not current_headings:
                current_headings = elem.heading_path
            current_tokens += elem_tokens

        # Flush any remaining items
        if current_texts:
            full_text = "\n\n".join(current_texts).strip()
            if full_text:
                chunks.append(Chunk(
                    chunk_id=str(uuid.uuid4()),
                    doc_id=doc_id,
                    text=full_text,
                    page=current_pages[0] if current_pages else 1,
                    bboxes=list(current_bboxes),
                    heading_path=list(current_headings),
                    token_count=current_tokens,
                    metadata={"page_list": list(set(current_pages))}
                ))

        return chunks

structure_chunker = StructureChunker(
    min_tokens=settings.CHUNK_TARGET_TOKENS - 100,
    max_tokens=settings.CHUNK_TARGET_TOKENS + 100,
    overlap_percent=0.12
)
