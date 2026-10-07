<div align="center">

# 📑 DocuChat AI
### **Enterprise-Grade Hybrid RAG & Visual Document Intelligence Platform**

*An end-to-end, production-ready Document RAG platform featuring visual bounding-box provenance highlighting, hybrid dense/sparse retrieval with Reciprocal Rank Fusion (RRF), live web knowledge fallback, and grounded LLM generation powered by Ollama (`qwen2.5:1.5b`) & Qdrant.*

---

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![Qdrant](https://img.shields.io/badge/Vector_DB-Qdrant-red?logo=qdrant&logoColor=white)](https://qdrant.tech/)
[![Ollama](https://img.shields.io/badge/LLM_Engine-Ollama_(Qwen_2.5)-black?logo=ollama&logoColor=white)](https://ollama.ai/)
[![Docker](https://img.shields.io/badge/Deployment-Docker_Compose-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![Hit Rate@3](https://img.shields.io/badge/Benchmark-Hit_Rate%403:_100%25-success)](https://github.com/Amdkhalid8214/DocuChat-AI-RAG-System#--retrieval-benchmark--evaluation)
[![License](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)

[**Live Architecture**](#-system-architecture) • [**Key Features**](#-key-features) • [**Quickstart Guide**](#-quickstart-guide) • [**Evaluation Benchmarks**](#--retrieval-benchmark--evaluation) • [**API Reference**](#-api-endpoints) • [**Configuration**](#-configuration-reference)

---

</div>

## 🌟 Executive Overview

**DocuChat AI** transforms multi-format documents (PDF, DOCX, PPTX, XLSX, TXT, Images) into structured, auditable knowledge. Unlike standard RAG implementations that hallucinate or return vague document references, DocuChat AI provides **visual provenance**: clicking any cited passage instantly jumps the embedded PDF viewer to the exact page and paints an interactive, golden bounding-box overlay directly on the canvas.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                   DOCUCHAT AI WORKFLOW                                 │
│                                                                                        │
│   [Document Upload] ──► [Layout Parsing] ──► [Structure Chunker] ──► [Hybrid Indexing] │
│                                                                            │           │
│   [User Question]   ──► [Query Routing]  ──► [Parallel Retrieval] ◄────────┘           │
│                                                     │                                  │
│   [PDF Canvas BBox] ◄── [SSE Token Stream] ◄── [Reranker & LLM] ◄── [RRF Fusion]       │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🏛️ System Architecture

```mermaid
flowchart TD
    subgraph Ingestion["1. Document Ingestion Subsystem"]
        Doc[User Document\nPDF, DOCX, PPTX, XLSX, Images] --> Convert[Multi-Format Converter\nLibreOffice / PyMuPDF Engine]
        Convert --> Parser[Layout-Aware Parser\nDocling / PyMuPDF Fitz]
        Parser --> Chunker[Structure-Aware Chunker\n400 Tokens, 12% Overlap]
        Chunker --> DenseEmbed[Dense Vector Embeddings\nBAAI/bge-small-en-v1.5 384d]
        Chunker --> SparseIndex[Sparse Lexical Index\nOkapi BM25Plus JSON Cache]
        DenseEmbed --> Qdrant[(Qdrant Vector Database\nCosine Similarity)]
        SparseIndex --> BM25Disk[(Local BM25 Store\ndata/bm25/*.json)]
    end

    subgraph Retrieval["2. Hybrid Retrieval & Ranking Subsystem"]
        Q[User Question] --> Router{Query Router\nRule Heuristic + LLM Classifier}
        Router -- "Document Scope" --> Rewrite[Query Transformation\nMulti-Query Expansion & Pronoun Resolver]
        Router -- "General Scope" --> GeneralAnswer[Direct Chat Generation\nBadge: 'General Knowledge']
        Router -- "Real-Time Query" --> WebSearch[Live Web Fallback\nYahoo Finance / DDG / Wiki]

        Rewrite --> ParFetch["Parallel Candidate Retrieval\nTop 30 Vector + Top 30 BM25"]
        ParFetch --> Fusion["Hybrid Rank Fusion\nReciprocal Rank Fusion k=60"]
        Fusion --> Dedup["Near-Duplicate Dedup\nChunk ID + 3-Gram Jaccard >= 0.88"]
        Dedup --> Reranker["Cross-Encoder Reranker\nBAAI/bge-reranker-base"]
        Reranker --> TopFilter["Relevance Filtering\nTop-5 Passages, Score >= 0.25"]
    end

    subgraph Generation["3. Grounded Generation & UI Visualization"]
        TopFilter --> PromptBuilder[Budgeted Prompt Builder\nStrict Markdown Citations [1], [2]]
        PromptBuilder --> LLMEngine[Ollama LLM Engine\nqwen2.5:1.5b @ temp=0.1]
        LLMEngine --> SSEStream[Server-Sent Events Stream\nTokens + Provenance Bounding Boxes]
        SSEStream --> ReactUI[3-Panel Interface\nSidebar | Live Chat | PDF Viewer]
        ReactUI --> CanvasHighlight[PDF.js Canvas Highlighting\nAuto-Scroll to Page & Draw BBox Overlay]
    end
```

---

## ⚡ Key Features

| Capability | Implementation | Benefit |
| :--- | :--- | :--- |
| **Hybrid Search (Dense + Sparse)** | Qdrant Cosine Vectors + Okapi BM25Plus | Eliminates vector blindness for acronyms, part numbers, and exact technical terms |
| **Reciprocal Rank Fusion (RRF)** | $RRF(d) = \sum_{m} \frac{1}{60 + r_m(d)}$ | Merges disparate score distributions into a calibrated, fair priority ranking |
| **Visual Provenance & Highlighting** | PyMuPDF Bounding Box Coordinate Mapping | Users can verify every LLM assertion on the exact document page in real time |
| **Cross-Encoder Reranking** | `BAAI/bge-reranker-base` | Scores deep query-passage semantic cross-attention before generation |
| **Adaptive Query Routing** | Hybrid Rule & Small-LLM JSON Classifier | Instantly routes general questions, document inquiries, or live web lookups |
| **Live Knowledge Integration** | Yahoo Finance, DuckDuckGo, Wikipedia API | Answers real-time financial, market, and breaking news queries without hallucinations |
| **Small-Model Tuning (`1.5B`)** | Compact prompts (<60 tokens), JSON schema defense | Runs blisteringly fast on edge / CPU / modest GPU hardware without attention drift |
| **Production UI (3 Panels)** | React 18, PDF.js, Server-Sent Events (SSE) | Simultaneous navigation of conversations, streaming answers, and full PDF pages |

---

## 🖥️ 3-Panel Pro Interface Layout

```
┌─────────────────────┬────────────────────────────────────┬───────────────────────────────────┐
│  📁 SESSIONS & DOCS │         💬 GROUNDED CHAT STREAM    │      📄 INTERACTIVE PDF VIEWER    │
├─────────────────────┼────────────────────────────────────┼───────────────────────────────────┤
│                     │                                    │                                   │
│  [+ New Session]    │  User: What is the quarterly net   │  [Page 12 / 84]   [-] [100%] [+]  │
│                     │        revenue according to 10-Q?  │  ┌─────────────────────────────┐  │
│  💬 Q3 Financials   │                                    │  │                             │  │
│  💬 Tech Specs v2   │  Assistant: [Document Grounded]    │  │ Consolidated Statement      │  │
│                     │  Net revenue for the third quarter │  │ ┌─────────────────────────┐ │  │
│  ───────────────    │  reached $4.2B, an increase of     │  │ │ 🟨 Net revenue reached   │ │  │
│  📄 Q3_Report.pdf   │  18% year-over-year [1].           │  │ │ $4.2B for Q3 [BBox]     │ │  │
│  📄 Architecture.pdf│                                    │  │ └─────────────────────────┘ │  │
│                     │  [1] Q3_Report.pdf (Page 12)       │  │                             │  │
│  ⚙️ Settings Drawer │      ↳ Click to view highlight     │  └─────────────────────────────┘  │
│                     │                                    │                                   │
└─────────────────────┴────────────────────────────────────┴───────────────────────────────────┘
```

---

## 📊 Retrieval Benchmark & Evaluation

Tested against realistic domain document queries using the embedded evaluation suite (`backend/eval/retrieval_eval.py`):

| Metric | Target | Result | Status |
| :--- | :---: | :---: | :---: |
| **Hit Rate@1** | $\ge 40\%$ | **50.00%** | ✅ Exceeded |
| **Hit Rate@3** | $\ge 85\%$ | **100.00%** | 🏆 Perfect Retrieval |
| **Hit Rate@5** | $\ge 90\%$ | **100.00%** | 🏆 Perfect Retrieval |
| **Hit Rate@10** | $\ge 95\%$ | **100.00%** | 🏆 Perfect Retrieval |
| **Mean Reciprocal Rank (MRR)** | $\ge 0.65$ | **0.7083** | ✅ Exceeded |

Run the benchmark locally:
```bash
python backend/eval/retrieval_eval.py
```

---

## 🚀 Quickstart Guide

### Option 1: Docker Compose (All-in-One — Recommended)

Start the complete stack (Backend, Frontend, Qdrant Vector DB, Ollama, Docling) with a single command:

```bash
# 1. Clone the repository
git clone https://github.com/Amdkhalid8214/DocuChat-AI-RAG-System.git
cd DocuChat-AI-RAG-System/RAG-Based-ChatBot-Main

# 2. Configure environment
copy .env.example .env

# 3. Launch Docker containers
docker compose up --build -d
```
Access the application:
- **Frontend UI**: [http://localhost:3000](http://localhost:3000)
- **FastAPI Interactive Docs**: [http://localhost:5000/docs](http://localhost:5000/docs)
- **Qdrant Vector Dashboard**: [http://localhost:6333/dashboard](http://localhost:6333/dashboard)

---

### Option 2: Local Native Setup (Developer Mode)

#### Prerequisites
- **Python 3.10+**
- **Node.js 18+** & **npm**
- **Ollama**: Download from [ollama.ai](https://ollama.ai/) and pull the model:
  ```bash
  ollama pull qwen2.5:1.5b
  ```
- **Qdrant**: Run via lightweight Docker:
  ```bash
  docker run -d -p 6333:6333 -v qdrant_storage:/qdrant/storage qdrant/qdrant:latest
  ```

#### Backend Setup
```bash
cd backend

# Install Python dependencies
pip install -r requirements.txt

# Start FastAPI server
python main.py
# Backend runs at http://localhost:5000
```

#### Frontend Setup
```bash
cd frontend

# Install dependencies and start React application
npm install
npm start
# Frontend runs at http://localhost:3000
```

---

## 📡 API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/documents` | Upload & ingest document (PDF, DOCX, PPTX, XLSX, TXT) |
| `GET` | `/api/documents` | Retrieve list of ingested documents and status |
| `GET` | `/api/documents/{id}/file` | Stream raw PDF for the embedded canvas viewer |
| `DELETE` | `/api/documents/{id}` | Purge document, Qdrant vectors, and local BM25 cache |
| `POST` | `/api/chat` | Server-Sent Events (SSE) streaming chat with BBox citations |
| `GET` | `/api/conversations` | List user conversation sessions |
| `POST` | `/api/conversations` | Create a new conversation session |
| `GET` | `/api/conversations/{id}` | Fetch full message history for a conversation |
| `DELETE` | `/api/conversations/{id}` | Delete a conversation and associated message history |
| `GET` | `/health` | Live system health and configuration status check |

---

## ⚙️ Configuration Reference

All settings can be customized in `.env` or through the UI **Settings Drawer**:

```env
# Application Settings
APP_NAME="DocuChat Production RAG"
DEBUG=true
PORT=5000

# Database
DATABASE_URL=sqlite+aiosqlite:///./data/rag_app.db

# LLM Engine (Ollama)
LLM_BASE_URL=http://localhost:11434
LLM_MODEL=qwen2.5:1.5b
LLM_TEMPERATURE=0.1
LLM_MAX_TOKENS=1024

# Embeddings (BAAI SOTA Dense)
EMBEDDING_PROVIDER=sentence-transformers
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_DIM=384

# Vector DB (Qdrant)
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=doc_chunks

# Reranker
RERANKER_MODEL=BAAI/bge-reranker-base
USE_RERANKER=true

# Hybrid Search Tuning
ROUTER_MODE=hybrid                 # 'hybrid', 'rule', or 'llm'
RETRIEVAL_TOP_K=30                # Candidates retrieved from each searcher
FUSION_METHOD=rrf                 # 'rrf' (Reciprocal Rank Fusion) or 'weighted'
RRF_K=60                          # Constant for RRF formula
DEDUP_SIMILARITY_THRESHOLD=0.88   # Jaccard 3-gram deduplication threshold
FINAL_TOP_K=5                     # Context snippets passed to LLM
SCORE_THRESHOLD=0.25              # Minimum candidate relevance cut-off
```

---

## 🔒 Security & Safe Deployment

This repository is configured with zero-leak security standards:
- 🚫 **No API Secrets Stored**: Real `.env` files are ignored by git; `.env.example` provides an illustrative template.
- 🚫 **No Virtual Environment Bloat**: `.venv/` and `node_modules/` are strictly ignored.
- 🚫 **No Data or Upload Leaks**: User PDFs, sqlite database files, and vector indices in `backend/data/` are never committed.

---

## 👤 Author & Acknowledgments

Developed by **AMD Khalid**  
- **GitHub**: [@Amdkhalid8214](https://github.com/Amdkhalid8214)
- **Repository**: [DocuChat-AI-RAG-System](https://github.com/Amdkhalid8214/DocuChat-AI-RAG-System)

If you find this project helpful or inspiring, please consider giving it a ⭐ on GitHub!
