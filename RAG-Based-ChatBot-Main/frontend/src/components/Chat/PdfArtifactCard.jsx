import React, { useState } from "react";
import "./PdfArtifactCard.css";
import { api, getApiBase } from "../../services/api";

export default function PdfArtifactCard({ artifact, onPreviewInViewer }) {
  const [downloading, setDownloading] = useState(false);

  let art = artifact;
  if (typeof art === "string") {
    try {
      art = JSON.parse(art);
    } catch {
      art = null;
    }
  }

  if (!art || !art.filename) {
    return null;
  }

  const filename = art.filename;
  const artifactId = art.artifact_id || filename;
  const operation = (art.operation || "pdf_operation").replace(/_/g, " ").toUpperCase();
  const format = (art.format || filename.split(".").pop() || "pdf").toLowerCase();
  const fileSize = art.file_size ? `${(art.file_size / 1024).toFixed(1)} KB` : "Ready";
  const pageCount = art.page_count || art.total_pages || null;
  const reductionPercent = art.reduction_percent !== undefined ? art.reduction_percent : null;
  const disclaimer = art.disclaimer || art.honest_note || null;
  const scannedWarning = art.scanned_warning || art.ocr_note || null;
  const tablesCount = art.tables_count !== undefined ? art.tables_count : (art.table_count !== undefined ? art.table_count : null);

  const isPdf = format === "pdf";
  const isExcel = format === "xlsx" || format === "xls";
  const isText = format === "txt" || format === "md" || format === "csv";

  // Dynamic Icon Theme
  const getTheme = () => {
    if (isExcel) {
      return {
        bg: "#f0fdf4",
        color: "#16a34a",
        border: "#bbf7d0",
        label: "Excel Spreadsheet"
      };
    }
    if (isText) {
      return {
        bg: "#f8fafc",
        color: "#475569",
        border: "#cbd5e1",
        label: format.toUpperCase()
      };
    }
    return {
      bg: "#fef2f2",
      color: "#dc2626",
      border: "#fecaca",
      label: "PDF Document"
    };
  };

  const theme = getTheme();

  const handleDownload = async (e) => {
    e.preventDefault();
    if (downloading) return;
    setDownloading(true);
    try {
      if (api.downloadPdfArtifact) {
        await api.downloadPdfArtifact(artifactId, filename);
      } else {
        const url = `${getApiBase()}/tools/download/${encodeURIComponent(artifactId)}`;
        window.open(url, "_blank");
      }
    } catch (err) {
      console.error("Error downloading PDF artifact:", err);
      const url = `${getApiBase()}/tools/download/${encodeURIComponent(artifactId)}`;
      window.open(url, "_blank");
    } finally {
      setDownloading(false);
    }
  };

  const handlePreviewClick = () => {
    if (onPreviewInViewer) {
      onPreviewInViewer({
        id: artifactId,
        filename: filename,
        file_type: "pdf",
        download_url: `${getApiBase()}/tools/download/${encodeURIComponent(artifactId)}`
      });
    } else {
      // Direct open in new tab
      const url = `${getApiBase()}/tools/download/${encodeURIComponent(artifactId)}`;
      window.open(url, "_blank");
    }
  };

  return (
    <div className="pdf-artifact-card-container">
      <div className="pdf-card-header-row">
        {/* Dynamic File Format Icon */}
        <div
          className="pdf-card-icon-box"
          style={{ background: theme.bg, color: theme.color, borderColor: theme.border }}
          title={theme.label}
        >
          {isExcel ? (
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <path d="M8 13h8" />
              <path d="M8 17h8" />
              <path d="M10 9H8" />
            </svg>
          ) : isText ? (
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
            </svg>
          ) : (
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <path d="M9 15h6" />
              <path d="M9 11h6" />
            </svg>
          )}
        </div>

        {/* Content Column */}
        <div className="pdf-card-title-col">
          <div className="pdf-card-top-tags">
            <span className="pdf-operation-badge">
              🛠️ {operation}
            </span>
            <span className="pdf-status-tag">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                <polyline points="20 6 9 17 4 12" />
              </svg>
              Validated
            </span>
          </div>

          <h4 className="pdf-card-filename" title={filename}>
            {filename}
          </h4>

          <div className="pdf-card-meta-chips">
            <span className="pdf-meta-chip">
              📦 {fileSize}
            </span>
            {pageCount !== null && (
              <span className="pdf-meta-chip">
                📄 {pageCount} {pageCount === 1 ? "page" : "pages"}
              </span>
            )}
            {reductionPercent !== null && (
              <span className="pdf-meta-chip highlight">
                ⚡ {reductionPercent > 0 ? `-${reductionPercent}% size` : "Optimized"}
              </span>
            )}
            {tablesCount !== null && (
              <span className="pdf-meta-chip highlight">
                📊 {tablesCount} {tablesCount === 1 ? "table" : "tables"} extracted
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Compression / Extraction Disclaimers */}
      {disclaimer && (
        <div className="pdf-card-callout info">
          <span>ℹ️</span>
          <span>{disclaimer}</span>
        </div>
      )}

      {scannedWarning && (
        <div className="pdf-card-callout warn">
          <span>⚠️</span>
          <span>{scannedWarning}</span>
        </div>
      )}

      {/* Action Buttons */}
      <div className="pdf-card-actions-row">
        <button
          className="pdf-btn-primary"
          onClick={handleDownload}
          disabled={downloading}
          title={`Download ${filename}`}
        >
          {downloading ? (
            <>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="12" y1="2" x2="12" y2="6" />
                <line x1="12" y1="18" x2="12" y2="22" />
                <line x1="4.93" y1="4.93" x2="7.76" y2="7.76" />
                <line x1="16.24" y1="16.24" x2="19.07" y2="19.07" />
              </svg>
              Downloading...
            </>
          ) : (
            <>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              Download {format.toUpperCase()}
            </>
          )}
        </button>

        {isPdf && (
          <button
            className="pdf-btn-secondary"
            onClick={handlePreviewClick}
            title="Preview generated PDF in viewer"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
            Preview PDF
          </button>
        )}
      </div>
    </div>
  );
}
