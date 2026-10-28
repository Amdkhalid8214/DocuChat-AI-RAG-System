import React, { useState } from "react";
import "./DocumentArtifactCard.css";
import { api } from "../../services/api";

export default function DocumentArtifactCard({ artifact }) {
  const [downloading, setDownloading] = useState(false);
  const [showPreview, setShowPreview] = useState(false);

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
  const title = art.title || filename;
  const docType = (art.document_type || "Document").replace(/_/g, " ").toUpperCase();
  const format = (art.format || filename.split(".").pop() || "DOCX").toUpperCase();
  const fileSize = art.file_size ? `${(art.file_size / 1024).toFixed(1)} KB` : "Ready";
  const sectionsCount = art.sections_count || null;
  const wordCount = art.word_count || null;
  const estPages = art.estimated_pages || 1;
  const previewText = art.preview_text || null;

  // Determine icon & theme color by format
  const getFormatBadgeTheme = (fmt) => {
    switch (fmt) {
      case "PDF":
        return {
          color: "#dc2626",
          bg: "#fef2f2",
          border: "#fecaca",
          label: "PDF Document"
        };
      case "DOCX":
        return {
          color: "#2563eb",
          bg: "#eff6ff",
          border: "#bfdbfe",
          label: "Word Document (DOCX)"
        };
      case "MD":
        return {
          color: "#9333ea",
          bg: "#faf5ff",
          border: "#e9d5ff",
          label: "Markdown (MD)"
        };
      case "TXT":
      default:
        return {
          color: "#475569",
          bg: "#f8fafc",
          border: "#e2e8f0",
          label: "Plain Text (TXT)"
        };
    }
  };

  const theme = getFormatBadgeTheme(format);

  const handleDownload = async (e) => {
    e.preventDefault();
    if (downloading) return;
    setDownloading(true);
    try {
      if (api.downloadDocumentFile) {
        await api.downloadDocumentFile(artifactId, filename);
      } else {
        const backendBase = process.env.REACT_APP_API_BASE || "http://localhost:5000/api";
        const url = `${backendBase}/tools/download/${encodeURIComponent(artifactId)}`;
        window.open(url, "_blank");
      }
    } catch (err) {
      console.error("Error downloading document:", err);
      const backendBase = process.env.REACT_APP_API_BASE || "http://localhost:5000/api";
      window.open(`${backendBase}/tools/download/${encodeURIComponent(artifactId)}`, "_blank");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="doc-artifact-card-container">
      <div className="doc-card-header-row">
        {/* Dynamic File Format Icon */}
        <div
          className="doc-card-icon-box"
          style={{ background: theme.bg, color: theme.color, borderColor: theme.border }}
          title={theme.label}
        >
          {format === "PDF" ? (
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
              <polyline points="10 9 9 9 8 9" />
            </svg>
          ) : format === "DOCX" ? (
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M4 4v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6H6a2 2 0 0 0-2 2z" />
              <path d="M14 2v6h6" />
              <path d="M9 13v4" />
              <path d="M12 13v4" />
              <path d="M15 13v4" />
            </svg>
          ) : format === "MD" ? (
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M4 4h16v16H4z" />
              <path d="M7 15V9l3 3 3-3v6" />
              <path d="M17 12l-2 2v-4" />
            </svg>
          ) : (
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
            </svg>
          )}
        </div>

        {/* File Metadata Column */}
        <div className="doc-card-meta-col">
          <div className="doc-card-title-row">
            <h4 className="doc-card-title" title={title}>
              {title}
            </h4>
            <span
              className="doc-card-format-pill"
              style={{ background: theme.bg, color: theme.color, borderColor: theme.border }}
            >
              {format}
            </span>
          </div>
          <div className="doc-card-subtitle">
            <span className="doc-type-tag">{docType}</span>
            <span>•</span>
            <span>{fileSize}</span>
            {sectionsCount && (
              <>
                <span>•</span>
                <span>{sectionsCount} sections</span>
              </>
            )}
            {wordCount && (
              <>
                <span>•</span>
                <span>~{wordCount} words ({estPages} {estPages === 1 ? "page" : "pages"})</span>
              </>
            )}
          </div>
          <div className="doc-card-filename" title={filename}>
            📁 {filename}
          </div>
        </div>
      </div>

      {/* Action Buttons Row */}
      <div className="doc-card-actions-row">
        <button
          type="button"
          onClick={handleDownload}
          disabled={downloading}
          className="doc-card-btn doc-download-btn"
          title={`Download ${filename}`}
        >
          {downloading ? (
            <>
              <span className="doc-spinner"></span>
              <span>Downloading...</span>
            </>
          ) : (
            <>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              <span>Download {format}</span>
            </>
          )}
        </button>

        {previewText && (
          <button
            type="button"
            onClick={() => setShowPreview(!showPreview)}
            className="doc-card-btn doc-preview-btn"
            title="Toggle Document Outline Preview"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
            <span>{showPreview ? "Hide Preview" : "Quick Outline"}</span>
          </button>
        )}
      </div>

      {/* Expandable Preview Section */}
      {showPreview && previewText && (
        <div className="doc-preview-accordion-box">
          <div className="doc-preview-badge">Document Structure Preview</div>
          <pre className="doc-preview-content">{previewText}</pre>
        </div>
      )}
    </div>
  );
}
