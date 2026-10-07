# Operational Rules & Coding Standards
## DocuChat AI — System Principles & Constraints

---

## 1. Grounded Generation Principles

### Rule 1.1: Strict Document Provenance
- When answering in **Document Mode**, the model must NEVER fabricate facts, guess unmentioned numbers, or extrapolate beyond the provided text sources.
- Every factual assertion originating from the document MUST be cited immediately inline using square bracket notation: `[1]`, `[2]`.

### Rule 1.2: Explicit "Not in Document" Handling
- If the question cannot be answered from the provided document context, the assistant must explicitly begin its response with:
  > *"This is not mentioned in the document."*
- It must then provide helpful real-world suggestions or general advice under a distinct header: `**Suggestions / Real-World Answer:**`.

### Rule 1.3: Dual Chat Mode Discipline
- **Document Scope Active:** Route to `"document"`. Prioritize document context, extract facts, provide citations, and trigger PDF viewer navigation.
- **No Document / ChatGPT Mode:** Route to `"general"`. Direct conversation with ChatGPT-style versatility, augmented with live web/market data. Do NOT mention documents or display empty document notices.

---

## 2. Bounding Box & Highlight Precision Rules

### Rule 2.1: Single-Answer Highlighting Guarantee
- The application must NEVER highlight an entire chunk, a whole paragraph array, or the whole PDF page.
- The backend MUST filter candidate bounding boxes to the single best-matching sentence or line answering the query (`allBoxes.slice(0, 1)`).

### Rule 2.2: Coordinate System Fidelity
- All bounding box coordinates stored in Qdrant and SQLite must preserve:
  - `x0, y0, x1, y1`
  - `page_width, page_height`
  - `coord_origin`: either `"TOPLEFT"` (PyMuPDF standard) or `"BOTTOMLEFT"` (Docling/PDF standard).
- The frontend canvas overlay MUST normalize coordinates using the current canvas width/height:
  ```javascript
  const top = box.coord_origin === "BOTTOMLEFT"
    ? (pHeight - box.y1) * scaleY
    : box.y0 * scaleY;
  ```

---

## 3. Privacy & Local Infrastructure Rules

### Rule 3.1: Zero External API Cost
- The system must remain fully operational without requiring paid API keys (no OpenAI, Anthropic, or Pinecone keys required).
- The default LLM is **Ollama with Qwen 2.5 1.5B** (`qwen2.5:1.5b`).
- The default embedding model is **FastEmbed BGE-Small** (`BAAI/bge-small-en-v1.5`, 384 dimensions).

### Rule 3.2: Resilient Local Fallbacks
- If Qdrant Docker is offline, the backend must seamlessly switch to embedded local disk storage (`./data/qdrant_storage`).
- If Docling microservice is unreachable, the backend must fall back to PyMuPDF (`fitz`).
- If Cross-Encoder reranker is not installed, the pipeline must fall back to Max-Scaled Reciprocal Rank Fusion.

---

## 4. API & Streaming Contract Rules

### Rule 4.1: Server-Sent Events (SSE) Protocol
Every streaming response from `/api/chat` MUST strictly follow this event sequence:

```text
event: meta
data: {"badge": "From document", "route": "document", "queries": ["query 1", "query 2"]}

event: token
data: {"content": "The "}

event: token
data: {"content": "intermediate "}

event: citations
data: {"citations": [{"source_index": 1, "page": 1, "bboxes": [{...}]}]}

event: done
data: {"status": "complete"}
```

1. **`meta`**: Sent immediately before LLM generation begins (badge and search queries).
2. **`token`**: Real-time streaming chunks from the LLM.
3. **`citations`**: Sent after generation completes, containing filtered bounding boxes.
4. **`done`**: Closes the event stream.

---

## 5. Code Quality & Maintenance Rules

- **Do Not Break Working Pipelines:** When adding features (such as live web search or CSS tweaks), never alter or bypass the established document retrieval and highlighting workflow.
- **Deterministic BM25 Scoring:** Always use `BM25Plus` to prevent negative scores on small corpora.
- **Preserve Clean CSS Variables:** All styling must reference CSS custom properties defined in `:root` (e.g., `var(--bg-primary)`, `var(--accent-indigo)`, `var(--text-main)`).
