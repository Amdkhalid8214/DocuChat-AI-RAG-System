import React, { useState } from "react";
import "./ExcelArtifactCard.css";
import { api } from "../../services/api";

export default function ExcelArtifactCard({ artifact }) {
  const [downloading, setDownloading] = useState(false);

  let art = artifact;
  if (typeof art === "string") {
    try {
      art = JSON.parse(art);
    } catch {
      art = null;
    }
  }

  if (!art || !art.filename || art.valid === false) {
    return null;
  }

  const filename = art.filename;
  const artifactId = art.artifact_id || filename;
  const sheetCount = art.sheet_count || 1;
  const isQa = art.is_qa_test_data !== false;
  const casesOrRows = art.data_row_count || art.total_rows || art.total_cases || 0;
  const countLabel = isQa ? "test cases" : "data rows";
  const colCount = art.data_column_count || (art.columns ? art.columns.length : (!isQa ? art.total_columns : null));
  const validationStatus = art.validation_status || "Created and validated";

  // Build secure download URL bound strictly to this artifact
  const backendBase = process.env.REACT_APP_API_BASE || "http://localhost:5000/api";
  const directDownloadUrl = art.download_url
    ? (art.download_url.startsWith("http")
        ? art.download_url
        : `${backendBase.replace(/\/api$/, "")}${art.download_url.startsWith("/") ? "" : "/"}${art.download_url}`)
    : `${backendBase}/tools/download/${encodeURIComponent(artifactId)}`;

  const handleDownloadClick = async (e) => {
    e.preventDefault();
    if (downloading) return;
    setDownloading(true);
    try {
      if (api.downloadExcelFile) {
        await api.downloadExcelFile(artifactId, filename);
      } else {
        const res = await fetch(directDownloadUrl);
        if (!res.ok) throw new Error("Download failed");
        const blob = await res.blob();
        const blobUrl = window.URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = blobUrl;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        window.URL.revokeObjectURL(blobUrl);
        document.body.removeChild(link);
      }
    } catch (err) {
      console.error("Error downloading Excel workbook:", err);
      // Fallback: direct window open
      window.open(directDownloadUrl, "_blank");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="excel-artifact-card-container">
      <div className="excel-card-header-row">
        {/* Excel 2x2 Grid Icon in Green */}
        <div className="excel-card-icon-box" title="Excel Workbook">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <rect x="3" y="3" width="18" height="18" rx="3.5" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="12" y1="3" x2="12" y2="21" />
          </svg>
        </div>

        {/* File Metadata Column */}
        <div className="excel-card-meta-col">
          <h4 className="excel-card-filename">{filename}</h4>
          <div className="excel-card-subtitle">
            Excel workbook · {sheetCount} {sheetCount === 1 ? "sheet" : "sheets"} · {casesOrRows} {countLabel}
            {colCount ? ` · ${colCount} columns` : ""}
          </div>
          {art.sheet_names && art.sheet_names.length > 1 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: "4px", margin: "4px 0" }}>
              {art.sheet_names.map((s, idx) => (
                <span key={idx} style={{
                  fontSize: "11px",
                  padding: "1px 6px",
                  borderRadius: "4px",
                  background: "#e2e8f0",
                  color: "#334155",
                  fontWeight: 500
                }}>
                  {s}
                </span>
              ))}
            </div>
          )}
          <div>
            <span className="excel-validated-badge">{validationStatus}</span>
          </div>
        </div>
      </div>

      {/* Download Action Row */}
      <div className="excel-card-action-row">
        <a
          href={directDownloadUrl}
          onClick={handleDownloadClick}
          className="excel-download-link"
          download={filename}
        >
          {downloading ? "Downloading workbook..." : (isQa ? "Download the Excel test workbook" : "Download Excel workbook")}
          <span className="excel-download-arrow">↗</span>
        </a>
      </div>
    </div>
  );
}
