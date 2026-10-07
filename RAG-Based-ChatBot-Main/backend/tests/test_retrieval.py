import sys
from pathlib import Path

# Add project root to sys.path
root_dir = str(Path(__file__).resolve().parent.parent.parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

try:
    import pytest
except ImportError:
    pytest = None
from backend.chunking.structure_chunker import StructureChunker
from backend.parsers.docling_parser import ParsedElement
from backend.retrieval.fusion import reciprocal_rank_fusion, weighted_score_fusion
from backend.retrieval.dedup import deduplicate_chunks, jaccard_similarity, get_char_ngrams

def test_structure_chunking():
    chunker = StructureChunker(min_tokens=20, max_tokens=50, overlap_percent=0.1)
    elements = [
        ParsedElement(text="# Section 1: Overview", page=1, bboxes=[{"x0": 0, "y0": 0, "x1": 10, "y1": 10}], heading_path=["Section 1"], elem_type="heading"),
        ParsedElement(text="This is paragraph one of the document discussing the initial introduction and requirements.", page=1, bboxes=[{"x0": 10, "y0": 10, "x1": 20, "y1": 20}], heading_path=["Section 1"], elem_type="paragraph"),
        ParsedElement(text="This is paragraph two providing additional context and architectural notes for the system.", page=1, bboxes=[{"x0": 20, "y0": 20, "x1": 30, "y1": 30}], heading_path=["Section 1"], elem_type="paragraph"),
        ParsedElement(text="# Section 2: Data Flow", page=2, bboxes=[{"x0": 0, "y0": 0, "x1": 10, "y1": 10}], heading_path=["Section 2"], elem_type="heading"),
        ParsedElement(text="Data flows directly from client to backend through SSE streaming.", page=2, bboxes=[{"x0": 10, "y0": 10, "x1": 20, "y1": 20}], heading_path=["Section 2"], elem_type="paragraph"),
    ]
    chunks = chunker.chunk_elements(elements, doc_id="doc_123")
    assert len(chunks) >= 2
    for chunk in chunks:
        assert chunk.doc_id == "doc_123"
        assert len(chunk.text) > 0
        assert chunk.page in [1, 2]
        assert isinstance(chunk.bboxes, list)

def test_reciprocal_rank_fusion():
    ranking_1 = [
        {"chunk_id": "c1", "text": "Doc 1 text"},
        {"chunk_id": "c2", "text": "Doc 2 text"},
        {"chunk_id": "c3", "text": "Doc 3 text"},
    ]
    ranking_2 = [
        {"chunk_id": "c2", "text": "Doc 2 text"},
        {"chunk_id": "c1", "text": "Doc 1 text"},
        {"chunk_id": "c4", "text": "Doc 4 text"},
    ]

    fused = reciprocal_rank_fusion([ranking_1, ranking_2], k=60)
    assert len(fused) == 4
    # c1 and c2 appeared in both rankings, so their RRF scores should be higher than c3 and c4
    top_ids = [fused[0]["chunk_id"], fused[1]["chunk_id"]]
    assert "c1" in top_ids
    assert "c2" in top_ids
    assert fused[0]["score"] > fused[2]["score"]

def test_weighted_score_fusion():
    vector_results = [
        {"chunk_id": "c1", "vector_score": 0.95},
        {"chunk_id": "c2", "vector_score": 0.80},
    ]
    bm25_results = [
        {"chunk_id": "c2", "bm25_score": 10.0},
        {"chunk_id": "c1", "bm25_score": 2.0},
    ]
    # Equal 50/50 weight
    fused = weighted_score_fusion(vector_results, bm25_results, alpha=0.5)
    assert len(fused) == 2
    assert "weighted_score" in fused[0]

def test_deduplication():
    chunks = [
        {"chunk_id": "c1", "text": "The quick brown fox jumps over the lazy dog and runs into the forest."},
        {"chunk_id": "c1", "text": "Duplicate chunk ID"},
        {"chunk_id": "c2", "text": "The quick brown fox jumps over the lazy dog and runs into the forest!"},  # near duplicate of c1
        {"chunk_id": "c3", "text": "Completely unique text discussing quantum computing and entanglement."},
    ]
    deduped = deduplicate_chunks(chunks, similarity_threshold=0.85)
    # c1 duplicate ID removed, c2 near duplicate removed, c3 kept
    assert len(deduped) == 2
    assert deduped[0]["chunk_id"] == "c1"
    assert deduped[1]["chunk_id"] == "c3"

if __name__ == "__main__":
    test_structure_chunking()
    test_reciprocal_rank_fusion()
    test_weighted_score_fusion()
    test_deduplication()
    print("All retrieval unit tests passed successfully!")
