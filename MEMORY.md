# Engineering Memory & Lessons Learned
## DocuChat AI — Technical Decisions, Gotchas & Rationale

---

## 1. Key Architectural Decisions & Rationale

### Decision 1.1: Ollama with Qwen 2.5 (1.5B) as Default LLM
- **Rationale:** High reasoning capabilities, strong structured JSON compliance, multilingual support, and native 32k context window in a compact parameter footprint that runs at 40+ tokens/sec on standard consumer CPU/GPUs without requiring cloud API subscriptions.

### Decision 1.2: FastEmbed ONNX Runtime for Embeddings (`BAAI/bge-small-en-v1.5`)
- **Rationale:** Pure ONNX C++ runtime without heavyweight PyTorch dependencies. Generates 384-dimensional dense vectors in $< 5\text{ ms}$ per query, perfectly matching Qdrant cosine similarity search.

### Decision 1.3: BM25Plus Over BM25Okapi
- **Rationale:** Standard BM25Okapi computes negative IDF scores when document frequency $n$ approaches corpus size $N$ (e.g. $N=2$ chunks). In contrast, `BM25Plus` uses a lower-bounded IDF formulation that guarantees strictly positive, well-calibrated scores for single-document and multi-document retrieval alike.

### Decision 1.4: Max-Scaling Over Min-Max Normalization
- **Rationale:** Min-max normalization:
  $$\text{norm} = \frac{s - \min(s)}{\max(s) - \min(s)}$$
  mathematically forces the lowest candidate chunk to $0.0$. In a two-chunk document, Chunk 2 always becomes $0.0$ and gets dropped by `score_threshold >= 0.25`. Max-scaling:
  $$\text{norm} = \frac{s}{\max(s)}$$
  preserves relative strength and allows all relevant chunks to pass to the LLM.

---

## 2. Critical Gotchas Solved

### Gotcha 2.1: The 900-Character Context Truncation Bug
- **Symptom:** AI abruptly stopped listing technical skills at "Oracle", missing ML, Generative AI, and tools.
- **Root Cause:** In `generator.py`, `snippet = text[:900]` truncated Chunk 0 right in the middle of the Technical Skills line at character 900.
- **Fix:** Increased chunk snippet limit to 3,500 characters, allowing complete sections to be passed to the LLM.

### Gotcha 2.2: The "Blue Screen" 20-Box Highlighting Bug
- **Symptom:** Entire page covered with blue boxes instead of just the answer.
- **Root Cause:** The parser attached all element boxes to the chunk, and the backend passed all 20 chunk boxes directly to the citation payload.
- **Fix:** Implemented `refine_citations_for_answer()` in `generator.py` to evaluate bounding boxes against generated answer keywords and return **only the single highest-scoring box** (`allBoxes.slice(0, 1)`).

### Gotcha 2.3: BM25 Zero Hits on Small Resume PDF
- **Symptom:** Vector search worked, but BM25 returned 0 hits for exact words like "technical skills".
- **Root Cause:** BM25Okapi produced negative scores (`-0.044`), triggering `if score > 0` to discard all chunks.
- **Fix:** Upgraded to `BM25Plus` in `retrieval/bm25.py`.

### Gotcha 2.4: Ollama 404 Model Not Found
- **Symptom:** Generation requests returned HTTP 404 from Ollama.
- **Root Cause:** Container `docuchat_ollama` on port 11434 did not have `qwen2.5:1.5b` pre-pulled.
- **Fix:** Executed `docker exec docuchat_ollama ollama pull qwen2.5:1.5b` and added automated model readiness verification.

### Gotcha 2.5: Windows Console `cp1252` Encoding Error
- **Symptom:** Python terminal crashed with `UnicodeEncodeError: 'charmap' codec can't encode character '\u025b'`.
- **Root Cause:** Wikipedia search results contained phonetic symbols (IPA) that Windows command prompt CP1252 could not display.
- **Fix:** Added `clean_snippet()` with `html.unescape` and safe string normalization in `retrieval/web_search.py`.

---

## 3. Key File & Responsibility Map

| File Path | Primary Responsibility |
| :--- | :--- |
| [`main.py`](file:///C:/Users/AMD/OneDrive/Desktop/Git%20rag/RAG-Based-ChatBot-Main/backend/main.py) | FastAPI app entry point, CORS, lifespan database initialization |
| [`config.py`](file:///C:/Users/AMD/OneDrive/Desktop/Git%20rag/RAG-Based-ChatBot-Main/backend/config.py) | Centralized Pydantic settings, model paths, port numbers, tuning parameters |
| [`parsers/docling_parser.py`](file:///C:/Users/AMD/OneDrive/Desktop/Git%20rag/RAG-Based-ChatBot-Main/backend/parsers/docling_parser.py) | Docling client with PyMuPDF fallback, coordinate extraction |
| [`chunking/structure_chunker.py`](file:///C:/Users/AMD/OneDrive/Desktop/Git%20rag/RAG-Based-ChatBot-Main/backend/chunking/structure_chunker.py) | Structural chunking respecting headings, table preservation |
| [`retrieval/pipeline.py`](file:///C:/Users/AMD/OneDrive/Desktop/Git%20rag/RAG-Based-ChatBot-Main/backend/retrieval/pipeline.py) | Parallel hybrid retrieval orchestrator (Vector + BM25Plus + RRF + Reranker) |
| [`retrieval/bm25.py`](file:///C:/Users/AMD/OneDrive/Desktop/Git%20rag/RAG-Based-ChatBot-Main/backend/retrieval/bm25.py) | Disk-persisted BM25Plus sparse index |
| [`retrieval/reranker.py`](file:///C:/Users/AMD/OneDrive/Desktop/Git%20rag/RAG-Based-ChatBot-Main/backend/retrieval/reranker.py) | Cross-encoder rescoring with Max-scaling normalization |
| [`retrieval/web_search.py`](file:///C:/Users/AMD/OneDrive/Desktop/Git%20rag/RAG-Based-ChatBot-Main/backend/retrieval/web_search.py) | Real-time live data for stocks (Yahoo Finance), movies, sports, politics (DDG/Wiki) |
| [`llm/router.py`](file:///C:/Users/AMD/OneDrive/Desktop/Git%20rag/RAG-Based-ChatBot-Main/backend/llm/router.py) | Query intent classifier (Document Mode vs ChatGPT Real-World Mode) |
| [`llm/generator.py`](file:///C:/Users/AMD/OneDrive/Desktop/Git%20rag/RAG-Based-ChatBot-Main/backend/llm/generator.py) | Grounded prompt construction, SSE streaming, global best-box answer refinement |
| [`frontend/src/App.jsx`](file:///C:/Users/AMD/OneDrive/Desktop/Git%20rag/RAG-Based-ChatBot-Main/frontend/src/App.jsx) | React 18 UI, PDF.js canvas, SSE consumer, single-box answer highlighting |
