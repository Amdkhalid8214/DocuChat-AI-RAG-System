# ============================================
# DocuChat Backend - Multi-Stage Dockerfile
# ============================================

# Stage 1: Build & Dependencies
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Production Runtime
FROM python:3.11-slim

WORKDIR /app

# Install LibreOffice for document format conversions (DOCX, PPTX, XLSX -> PDF)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Create non-root user for security compliance
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/backend/data/uploads /app/backend/data/converted /app/backend/data/bm25 && \
    chown -R appuser:appuser /app

# Copy application source code
COPY backend/ /app/backend/

USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=5000

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "5000"]
