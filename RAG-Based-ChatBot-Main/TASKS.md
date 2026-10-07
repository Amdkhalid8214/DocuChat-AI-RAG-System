# Implementation Tasks & Roadmap
## DocuChat AI — Engineering Milestones & Backlog

---

## 1. Completed Implementation Phases

### Phase 1: Local Stack & Infrastructure Setup
- [x] Configure FastAPI backend structure with async SQLAlchemy and SQLite (`rag_app.db`).
- [x] Configure Qdrant vector database with embedded fallback (`./data/qdrant_storage`).
- [x] Integrate FastEmbed ONNX runtime with `BAAI/bge-small-en-v1.5` (384 dimensions).
- [x] Set up Ollama client with `qwen2.5:1.5b` model on `http://localhost:11434`.
- [x] Build Docker Compose configuration for multi-service deployment.

### Phase 2: Document Ingestion & Structure Extraction
- [x] Build Docling REST parser client for document structure decomposition.
- [x] Implement robust PyMuPDF (Fitz) fallback for offline document extraction.
- [x] Extract bounding box coordinates (`x0, y0, x1, y1`, page width, page height, origin).
- [x] Associate raw sentence/phrase text with each individual bounding box.
- [x] Develop `StructureChunker` respecting headings, paragraphs, and tables ($\approx 400$ tokens).

### Phase 3: Hybrid Retrieval & Fusion Optimization
- [x] Implement disk-persisted sparse lexical index using `BM25Plus` (preventing negative score bugs).
- [x] Build Reciprocal Rank Fusion (RRF, $k=60$) combining vector and BM25 rankings.
- [x] Implement Cross-Encoder reranker fallback with **Max-Scaling Normalization** (`raw / max_s`).
- [x] Prevent dropping valid secondary candidate chunks with calibrated score thresholding.
- [x] Multi-query query expansion with pronoun resolution.

### Phase 4: Query Routing & Grounded Generation
- [x] Build intelligent `QueryRouter` distinguishing between Document and ChatGPT modes.
- [x] Implement strict document prompt rules: cite inline with `[1]` and avoid extrapolation.
- [x] Handle missing document information with clear *"This is not mentioned in the document."* message.
- [x] Stream SSE tokens, metadata, citations, and completion signals.

### Phase 5: Precision Answer Highlighting on PDF Viewer
- [x] Fix "blue screen" bug where all 20+ chunk boxes covered the document.
- [x] Build `refine_citations_for_answer()`: global scoring of bounding boxes against generated answer tokens.
- [x] Filter highlights to **only the single exact bounding box** containing the answer.
- [x] Synchronize PDF.js HTML5 canvas with normalized coordinate overlays.
- [x] Add pulsing glow animation (`pulseHighlight`) for high-contrast visibility.

### Phase 6: Real-Time Live Web Knowledge Integration
- [x] Build `LiveWebSearch` module in `retrieval/web_search.py`.
- [x] Real-time financial market lookup via Yahoo Finance API (live quotes, changes, previous closes).
- [x] Live movie and theater search via DuckDuckGo HTML & Lite endpoints.
- [x] Sports scores, league standings, and political world event lookup via Wikipedia API.
- [x] Seamless ChatGPT-style general chat mode with zero API key dependencies.

---

## 2. Verification Matrix (Automated & Live Tests)

| Test ID | Test Scenario | Expected Outcome | Status |
| :--- | :--- | :--- | :---: |
| **TEST-01** | Resume intermediate percentage query | Answers 81%, cites [1], highlights Narayana Junior College box | Passed ✅ |
| **TEST-02** | Full technical skills list query | Comprehensive listing of all 6 categories, highlights Technical Skills box | Passed ✅ |
| **TEST-03** | Degree CGPA query | Answers 8.01/10, highlights SVIT education box | Passed ✅ |
| **TEST-04** | Off-topic query with doc active | Reports "not mentioned in document", provides suggestions | Passed ✅ |
| **TEST-05** | Live stock market query (AAPL/NVDA) | Returns real-time trading price and percentage change | Passed ✅ |
| **TEST-06** | Real-world general chat (movies/sports) | Returns up-to-date recommendations and tournament data | Passed ✅ |

---

## 3. Future Roadmap & Backlog

### Phase 7: Planned Enhancements (v2.1+)
- [ ] **OCR Engine for Scanned Documents:** Integrate Tesseract/PaddleOCR for scanned image PDFs.
- [ ] **Multi-Modal Vision LLM:** Add support for Qwen 2.5-VL / LLaVA to answer visual questions about charts and diagrams.
- [ ] **Document Comparison Mode:** Allow scoping queries across 2 uploaded documents simultaneously with split-screen highlights.
- [ ] **Conversation Export:** Export grounded chat transcripts to PDF or Markdown with embedded citations.
- [ ] **Voice Input / TTS Output:** Add browser speech recognition and synthesis for audio interaction.
