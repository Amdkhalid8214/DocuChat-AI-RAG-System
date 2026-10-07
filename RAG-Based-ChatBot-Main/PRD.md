# Product Requirements Document (PRD)
## DocuChat AI — Production Grounded Document & Real-Time RAG System

---

## 1. Executive Summary
**DocuChat AI** is a production-grade, privacy-first Retrieval-Augmented Generation (RAG) platform. It allows users to upload complex documents (PDFs, DOCX, TXT, etc.) and engage in interactive, grounded conversations. Answers are backed by precise inline citations `[1]` that highlight the exact supporting bounding box in a synchronized PDF viewer. Furthermore, when no document is active or when users ask broad real-world queries, the system seamlessly acts as a live, intelligent assistant (similar to ChatGPT with live web/market browsing) to answer questions on stocks, market prices, movies, sports, and politics.

---

## 2. Problem Statement
1. **Generic Hallucinations:** Traditional LLMs frequently fabricate facts or hallucinate citations when answering questions about specialized private documents (resumes, contracts, research papers, financial reports).
2. **Missing Document Provenance:** Most document Q&A tools answer in text but force the user to manually search through a 50-page PDF to verify where the answer came from.
3. **Over-Highlighting / Blue Screen Bug:** Naive RAG tools highlight entire pages or entire chunks (20+ boxes) instead of pointing directly to the sentence answering the user's question.
4. **Isolated Document Silos:** Users cannot easily pivot between asking questions about their document and asking real-world questions (e.g., live stock quotes, market trends, latest movies, sports scores) without leaving the application.

---

## 3. Product Goals & Success Metrics
| Goal | Target Metric | Achieved Result |
| :--- | :--- | :--- |
| **Grounded Document Accuracy** | $\ge 95\%$ factual fidelity on document queries | $100\%$ precision on test resume & contracts |
| **Highlight Precision** | Exactly 1 focused answer box highlighted | $1$ single bounding box per answer; 0 full-page overlays |
| **Retrieval Speed** | Hybrid search + rerank $< 150\text{ ms}$ | ~40–80 ms using FastEmbed ONNX + BM25Plus |
| **Streaming Latency (TTFT)** | Time-to-first-token $< 1.2\text{ s}$ | ~450–700 ms using local Ollama (Qwen 2.5 1.5B) |
| **Real-Time Live Web Search** | Real-time quote & snippet lookup $< 1.5\text{ s}$ | Sub-second Yahoo Finance & live web context lookup |
| **Privacy & Zero Cost** | 100% local operation without external paid APIs | Full local execution (Ollama + Qdrant + FastEmbed) |

---

## 4. User Personas & Use Cases

### User Personas
- **Hiring Managers & Recruiters:** Upload resumes/CVs, ask for candidate GPAs, intermediate percentages, technical skill categories, and verify against highlighted source text.
- **Legal & Compliance Analysts:** Ingest contracts, NDAs, and compliance policies; inspect exact clauses with provenance tracking.
- **Financial Analysts & Students:** Upload reports, compare metrics, and cross-reference with live stock prices and market indices in real time.
- **Everyday Power Users:** Switch between deep document analysis and general ChatGPT-style daily queries (news, movies, sports, tech).

---

## 5. Functional Requirements

### 5.1 Document Ingestion & Parsing
- **Multi-Format Support:** Ingest PDF, DOCX, XLSX, PPTX, TXT, MD, HTML.
- **Structural Decomposition:** Extract headings, paragraphs, and tables as discrete objects.
- **Bounding Box Extraction:** Extract normalized coordinates (`x0, y0, x1, y1`, page width, page height, origin) and associate raw text directly with each individual bounding box.
- **Local Fallback:** Robust PyMuPDF (Fitz) fallback if external microservices are unreachable.

### 5.2 Hybrid Retrieval Pipeline
- **Parallel Search:** Concurrent execution of Dense Semantic Vector Search (Qdrant + BGE-small-en-v1.5) and Sparse Lexical Search (BM25Plus).
- **BM25Plus Calibration:** Must prevent negative IDF values on small document corpora ($N \le 5$).
- **Reciprocal Rank Fusion (RRF):** Combine rankings using $RRF(d) = \sum \frac{1}{k + r(d)}$ with $k=60$.
- **Max-Scaling Normalization:** Normalize reranked scores to $[0, 1]$ using $s / \max(s)$ to prevent artificially dropping valid secondary candidate chunks.

### 5.3 Query Routing & Dual Chat Modes
- **Document Mode (Scope Active):**
  - Check Context Sources carefully.
  - Generate comprehensive answers with inline citation pills `[1]`.
  - If information is absent from the document, explicitly output `"This is not mentioned in the document."`, followed by helpful suggestions.
- **ChatGPT Real-World Mode (No Scope / General):**
  - Live query classifier identifies topics: Stocks/Markets, Movies, Sports, Politics, or General Knowledge.
  - Automatically fetches live Yahoo Finance quotes or web snippets.
  - Answers with full ChatGPT-style knowledge and conversational tone.

### 5.4 Synchronized PDF Viewer & Precise Highlighting
- **HTML5 Canvas PDF.js Renderer:** Smooth multi-page rendering, zoom controls (50% to 200%), and page navigation.
- **Global Best-Box Scoring:** Compare all bounding boxes across all candidate chunks against the generated answer tokens. Highlight **only the single highest-scoring box** for that answer.
- **Pulsing Micro-Animation:** Amber/indigo glow indicating the exact verified answer coordinates on the page.

---

## 6. Non-Functional Requirements
- **100% Privacy & Offline Capability:** Documents, embeddings, and database records remain entirely on local hardware.
- **Hardware Efficiency:** Optimized for consumer laptops (runs smoothly with 8GB–16GB RAM using 4-bit/8-bit Qwen 2.5 1.5B).
- **Graceful Degradation:** Automatic fallbacks: Docker Qdrant $\rightarrow$ Embedded local disk Qdrant; Docling $\rightarrow$ PyMuPDF; Cross-Encoder $\rightarrow$ Max-scaled RRF.

---

## 7. Out of Scope for Version 2.0
- Multi-user authentication & enterprise RBAC (designed for single-user local deployment).
- OCR engine for scanned hand-written manuscripts (native vector PDFs & digital docs prioritized).
