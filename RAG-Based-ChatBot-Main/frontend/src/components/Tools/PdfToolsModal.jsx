import React, { useState, useRef } from "react";
import "./PdfToolsModal.css";
import { api, getApiBase } from "../../services/api";

const OPERATIONS = [
  { id: "merge", label: "Merge PDFs", icon: "📑" },
  { id: "split", label: "Split PDF", icon: "✂️" },
  { id: "extract", label: "Extract Pages", icon: "📑" },
  { id: "rotate", label: "Rotate Pages", icon: "🔄" },
  { id: "compress", label: "Compress PDF", icon: "🗜️" },
  { id: "text", label: "PDF to Text/MD", icon: "📝" },
  { id: "tables", label: "Extract Tables", icon: "📊" },
  { id: "watermark", label: "Watermark", icon: "💧" },
  { id: "numbers", label: "Page Numbers", icon: "🔢" },
  { id: "images", label: "Images to PDF", icon: "🖼️" },
  { id: "info", label: "PDF Information", icon: "ℹ️" },
];

export default function PdfToolsModal({
  isOpen,
  onClose,
  documents = [],
  activeDoc,
  onPreviewInViewer,
  initialOperation = "merge"
}) {
  const [activeTab, setActiveTab] = useState(initialOperation);
  const [sourceType, setSourceType] = useState(activeDoc ? "workspace" : "upload");
  const [selectedDocId, setSelectedDocId] = useState(activeDoc?.id || "");
  const [uploadedFile, setUploadedFile] = useState(null);
  const [multipleFiles, setMultipleFiles] = useState([]); // for merge & images-to-pdf
  const [isProcessing, setIsProcessing] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");
  const [resultArtifact, setResultArtifact] = useState(null);
  const [infoResult, setInfoResult] = useState(null);

  // Form states
  const [pageSpec, setPageSpec] = useState("1, 3, 5-8");
  const [splitRanges, setSplitRanges] = useState("1-3, 4-6");
  const [rotateAngle, setRotateAngle] = useState(90);
  const [rotatePageSpec, setRotatePageSpec] = useState("all");
  const [compressLevel, setCompressLevel] = useState("medium");
  const [textFormat, setTextFormat] = useState("markdown");
  const [tableFormat, setTableFormat] = useState("xlsx");
  const [watermarkText, setWatermarkText] = useState("CONFIDENTIAL");
  const [watermarkPageSpec, setWatermarkPageSpec] = useState("all");
  const [watermarkOpacity, setWatermarkOpacity] = useState(0.25);
  const [watermarkFontSize, setWatermarkFontSize] = useState(48);
  const [pageNumberPosition, setPageNumberPosition] = useState("bottom-center");
  const [pageNumberFormat, setPageNumberFormat] = useState("Page {page} of {total}");

  const fileInputRef = useRef(null);
  const multiFileInputRef = useRef(null);

  if (!isOpen) return null;

  const pdfDocs = (documents || []).filter(
    (d) => d.file_type === "pdf" || (d.filename && d.filename.toLowerCase().endsWith(".pdf"))
  );

  const resetFormState = (newTab) => {
    setActiveTab(newTab);
    setErrorMsg("");
    setResultArtifact(null);
    setInfoResult(null);
  };

  const handleFileUpload = (e) => {
    const file = e.target.files[0];
    if (file) {
      setUploadedFile(file);
      setErrorMsg("");
    }
  };

  const handleMultipleFilesUpload = (e) => {
    const files = Array.from(e.target.files || []);
    if (files.length > 0) {
      setMultipleFiles((prev) => [...prev, ...files]);
      setErrorMsg("");
    }
  };

  const moveFileOrder = (index, direction) => {
    const newIdx = index + direction;
    if (newIdx < 0 || newIdx >= multipleFiles.length) return;
    const updated = [...multipleFiles];
    const temp = updated[index];
    updated[index] = updated[newIdx];
    updated[newIdx] = temp;
    setMultipleFiles(updated);
  };

  const removeFileFromOrder = (index) => {
    setMultipleFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSubmit = async () => {
    setErrorMsg("");
    setResultArtifact(null);
    setInfoResult(null);
    setIsProcessing(true);

    try {
      const formData = new FormData();

      // Source resolution
      if (activeTab === "merge") {
        if (multipleFiles.length < 2) {
          throw new Error("Please upload or add at least 2 PDF files to merge.");
        }
        multipleFiles.forEach((file) => {
          formData.append("files", file);
        });
      } else if (activeTab === "images") {
        if (multipleFiles.length < 1) {
          throw new Error("Please upload at least 1 image file.");
        }
        multipleFiles.forEach((file) => {
          formData.append("files", file);
        });
      } else {
        if (sourceType === "upload") {
          if (!uploadedFile) {
            throw new Error("Please select a PDF file to process.");
          }
          formData.append("file", uploadedFile);
        } else {
          if (!selectedDocId) {
            throw new Error("Please select an active document from your workspace.");
          }
          formData.append("doc_id", selectedDocId);
        }
      }

      let res = null;

      switch (activeTab) {
        case "merge":
          res = await api.pdfToolsPost("merge", formData);
          setResultArtifact(res);
          break;

        case "split":
          formData.append("ranges", splitRanges);
          res = await api.pdfToolsPost("split", formData);
          if (res.artifacts && res.artifacts.length > 0) {
            setResultArtifact(res.artifacts[0]);
          } else {
            setResultArtifact(res);
          }
          break;

        case "extract":
          formData.append("page_spec", pageSpec);
          res = await api.pdfToolsPost("extract-pages", formData);
          setResultArtifact(res);
          break;

        case "rotate":
          formData.append("angle", String(rotateAngle));
          formData.append("page_spec", rotatePageSpec);
          res = await api.pdfToolsPost("rotate", formData);
          setResultArtifact(res);
          break;

        case "compress":
          formData.append("level", compressLevel);
          res = await api.pdfToolsPost("compress", formData);
          setResultArtifact(res);
          break;

        case "text":
          formData.append("format", textFormat);
          res = await api.pdfToolsPost("to-text", formData);
          setResultArtifact(res);
          break;

        case "tables":
          formData.append("format", tableFormat);
          res = await api.pdfToolsPost("extract-tables", formData);
          setResultArtifact(res);
          break;

        case "watermark":
          formData.append("text", watermarkText);
          formData.append("page_spec", watermarkPageSpec);
          formData.append("opacity", String(watermarkOpacity));
          formData.append("fontsize", String(watermarkFontSize));
          res = await api.pdfToolsPost("watermark", formData);
          setResultArtifact(res);
          break;

        case "numbers":
          formData.append("position", pageNumberPosition);
          formData.append("format_str", pageNumberFormat);
          res = await api.pdfToolsPost("page-numbers", formData);
          setResultArtifact(res);
          break;

        case "images":
          res = await api.pdfToolsPost("images-to-pdf", formData);
          setResultArtifact(res);
          break;

        case "info":
          res = await api.pdfToolsPost("info", formData);
          setInfoResult(res);
          break;

        default:
          throw new Error(`Unsupported operation: ${activeTab}`);
      }
    } catch (err) {
      console.error("PDF operation error:", err);
      setErrorMsg(err.message || "An error occurred while processing the PDF.");
    } finally {
      setIsProcessing(false);
    }
  };

  const handleDownloadResult = () => {
    if (!resultArtifact || !resultArtifact.filename) return;
    const artifactId = resultArtifact.artifact_id || resultArtifact.filename;
    api.downloadPdfArtifact(artifactId, resultArtifact.filename);
  };

  const handlePreviewResult = () => {
    if (!resultArtifact) return;
    const artifactId = resultArtifact.artifact_id || resultArtifact.filename;
    if (onPreviewInViewer) {
      onPreviewInViewer({
        id: artifactId,
        filename: resultArtifact.filename,
        file_type: "pdf",
        download_url: `${getApiBase()}/tools/download/${encodeURIComponent(artifactId)}`
      });
      onClose();
    } else {
      window.open(`${getApiBase()}/tools/download/${encodeURIComponent(artifactId)}`, "_blank");
    }
  };

  return (
    <div className="pdf-modal-backdrop" onClick={onClose}>
      <div className="pdf-modal-container" onClick={(e) => e.stopPropagation()}>
        {/* Modal Header */}
        <div className="pdf-modal-header">
          <div className="pdf-header-title-box">
            <div className="pdf-header-icon">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
              </svg>
            </div>
            <div>
              <h3>PDF Tools Workstation</h3>
              <p>Merge, split, extract, rotate, compress, tables, and convert documents</p>
            </div>
          </div>
          <button className="pdf-btn-close" onClick={onClose} title="Close">
            ✕
          </button>
        </div>

        {/* Operation Tabs */}
        <div className="pdf-modal-tabs">
          {OPERATIONS.map((op) => (
            <button
              key={op.id}
              className={`pdf-tab-btn ${activeTab === op.id ? "active" : ""}`}
              onClick={() => resetFormState(op.id)}
            >
              <span>{op.icon}</span>
              <span>{op.label}</span>
            </button>
          ))}
        </div>

        {/* Modal Body */}
        <div className="pdf-modal-body">
          {/* Source Selector (not needed for merge or images-to-pdf) */}
          {activeTab !== "merge" && activeTab !== "images" && (
            <div className="pdf-source-selector-row">
              <span className="pdf-source-label">Source Document:</span>
              <div className="pdf-source-radios">
                <label>
                  <input
                    type="radio"
                    name="sourceType"
                    value="workspace"
                    checked={sourceType === "workspace"}
                    onChange={() => setSourceType("workspace")}
                  />
                  Workspace Document ({pdfDocs.length})
                </label>
                <label>
                  <input
                    type="radio"
                    name="sourceType"
                    value="upload"
                    checked={sourceType === "upload"}
                    onChange={() => setSourceType("upload")}
                  />
                  Upload New PDF
                </label>
              </div>
            </div>
          )}

          {/* Document Picker or Dropzone */}
          {activeTab !== "merge" && activeTab !== "images" && sourceType === "workspace" && (
            <div className="pdf-form-group">
              <label className="pdf-form-label">Select Workspace PDF:</label>
              <select
                className="pdf-form-select"
                value={selectedDocId}
                onChange={(e) => setSelectedDocId(e.target.value)}
              >
                <option value="">-- Choose a loaded PDF --</option>
                {pdfDocs.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.filename} ({d.page_count || 1} pages)
                  </option>
                ))}
              </select>
              {pdfDocs.length === 0 && (
                <span className="pdf-form-hint">
                  No PDF files found in workspace. Choose "Upload New PDF" above.
                </span>
              )}
            </div>
          )}

          {activeTab !== "merge" && activeTab !== "images" && sourceType === "upload" && (
            <div className="pdf-form-group">
              <input
                type="file"
                ref={fileInputRef}
                style={{ display: "none" }}
                accept=".pdf"
                onChange={handleFileUpload}
              />
              <div className="pdf-dropzone" onClick={() => fileInputRef.current?.click()}>
                <div className="pdf-dropzone-icon">
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                    <polyline points="17 8 12 3 7 8" />
                    <line x1="12" y1="3" x2="12" y2="15" />
                  </svg>
                </div>
                <p>{uploadedFile ? uploadedFile.name : "Click to select or drop a PDF here"}</p>
                <span>Maximum file size: 50MB</span>
              </div>
            </div>
          )}

          {/* Merge Multi-file Upload and Ordering */}
          {activeTab === "merge" && (
            <div className="pdf-form-group">
              <label className="pdf-form-label">Select PDFs to Merge (In Order):</label>
              <input
                type="file"
                ref={multiFileInputRef}
                style={{ display: "none" }}
                accept=".pdf"
                multiple
                onChange={handleMultipleFilesUpload}
              />
              <div className="pdf-dropzone" onClick={() => multiFileInputRef.current?.click()}>
                <div className="pdf-dropzone-icon">
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M12 5v14M5 12h14" />
                  </svg>
                </div>
                <p>Click to add PDF files to merge</p>
                <span>Select 2 or more files and arrange their order below</span>
              </div>

              {multipleFiles.length > 0 && (
                <div className="pdf-files-order-list">
                  {multipleFiles.map((f, i) => (
                    <div key={i} className="pdf-file-order-row">
                      <div className="pdf-file-order-left">
                        <span className="pdf-file-order-badge">{i + 1}</span>
                        <span>{f.name} ({(f.size / 1024).toFixed(1)} KB)</span>
                      </div>
                      <div className="pdf-file-order-actions">
                        <button
                          className="pdf-btn-icon-sm"
                          disabled={i === 0}
                          onClick={() => moveFileOrder(i, -1)}
                          title="Move up"
                        >
                          ▲
                        </button>
                        <button
                          className="pdf-btn-icon-sm"
                          disabled={i === multipleFiles.length - 1}
                          onClick={() => moveFileOrder(i, 1)}
                          title="Move down"
                        >
                          ▼
                        </button>
                        <button
                          className="pdf-btn-icon-sm"
                          onClick={() => removeFileFromOrder(i)}
                          title="Remove"
                        >
                          ✕
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Images to PDF Multi-file Upload */}
          {activeTab === "images" && (
            <div className="pdf-form-group">
              <label className="pdf-form-label">Select Images (PNG, JPG, WEBP):</label>
              <input
                type="file"
                ref={multiFileInputRef}
                style={{ display: "none" }}
                accept=".png,.jpg,.jpeg,.webp,.bmp"
                multiple
                onChange={handleMultipleFilesUpload}
              />
              <div className="pdf-dropzone" onClick={() => multiFileInputRef.current?.click()}>
                <p>Click to add image files</p>
                <span>Images will be compiled sequentially into a single PDF</span>
              </div>

              {multipleFiles.length > 0 && (
                <div className="pdf-files-order-list">
                  {multipleFiles.map((f, i) => (
                    <div key={i} className="pdf-file-order-row">
                      <div className="pdf-file-order-left">
                        <span className="pdf-file-order-badge">{i + 1}</span>
                        <span>{f.name}</span>
                      </div>
                      <div className="pdf-file-order-actions">
                        <button
                          className="pdf-btn-icon-sm"
                          onClick={() => removeFileFromOrder(i)}
                        >
                          ✕
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Operation-specific fields */}
          {activeTab === "split" && (
            <div className="pdf-form-group">
              <label className="pdf-form-label">Page Ranges (e.g. 1-3, 4-6):</label>
              <input
                type="text"
                className="pdf-form-input"
                value={splitRanges}
                onChange={(e) => setSplitRanges(e.target.value)}
                placeholder="1-3, 4-6"
              />
              <span className="pdf-form-hint">
                Enter comma-separated ranges. Each range will be extracted into a separate PDF.
              </span>
            </div>
          )}

          {activeTab === "extract" && (
            <div className="pdf-form-group">
              <label className="pdf-form-label">Select Pages (e.g. 1, 3, 5-8):</label>
              <input
                type="text"
                className="pdf-form-input"
                value={pageSpec}
                onChange={(e) => setPageSpec(e.target.value)}
                placeholder="1, 3, 5-8 or 'odd', 'even'"
              />
              <span className="pdf-form-hint">
                Supports comma-separated page numbers, ranges, "odd", or "even".
              </span>
            </div>
          )}

          {activeTab === "rotate" && (
            <>
              <div className="pdf-form-group">
                <label className="pdf-form-label">Rotation Angle:</label>
                <select
                  className="pdf-form-select"
                  value={rotateAngle}
                  onChange={(e) => setRotateAngle(Number(e.target.value))}
                >
                  <option value={90}>90° Clockwise</option>
                  <option value={180}>180° Flip</option>
                  <option value={270}>270° (90° Counter-clockwise)</option>
                </select>
              </div>
              <div className="pdf-form-group">
                <label className="pdf-form-label">Target Pages:</label>
                <input
                  type="text"
                  className="pdf-form-input"
                  value={rotatePageSpec}
                  onChange={(e) => setRotatePageSpec(e.target.value)}
                  placeholder="all or 1, 3"
                />
              </div>
            </>
          )}

          {activeTab === "compress" && (
            <div className="pdf-form-group">
              <label className="pdf-form-label">Compression Level:</label>
              <select
                className="pdf-form-select"
                value={compressLevel}
                onChange={(e) => setCompressLevel(e.target.value)}
              >
                <option value="light">Light (Fast, lossless stream deflation)</option>
                <option value="medium">Medium (Deflate + garbage collection, recommended)</option>
                <option value="strong">Strong (Maximum object compacting & image downsample)</option>
              </select>
              <span className="pdf-form-hint">
                Note: Compression results depend on the PDF's content streams (vector, fonts, images). Readability is preserved.
              </span>
            </div>
          )}

          {activeTab === "text" && (
            <div className="pdf-form-group">
              <label className="pdf-form-label">Output Format:</label>
              <select
                className="pdf-form-select"
                value={textFormat}
                onChange={(e) => setTextFormat(e.target.value)}
              >
                <option value="markdown">Markdown (.md) - with clean heading structure</option>
                <option value="text">Plain Text (.txt) - with page boundaries</option>
              </select>
            </div>
          )}

          {activeTab === "tables" && (
            <div className="pdf-form-group">
              <label className="pdf-form-label">Output Format:</label>
              <select
                className="pdf-form-select"
                value={tableFormat}
                onChange={(e) => setTableFormat(e.target.value)}
              >
                <option value="xlsx">Excel Workbook (.xlsx) - Styled table sheets</option>
                <option value="csv">CSV (.csv) - Comma-separated values</option>
              </select>
              <span className="pdf-form-hint">
                Detects structured PDF tables and exports clean cells with formula injection protection.
              </span>
            </div>
          )}

          {activeTab === "watermark" && (
            <>
              <div className="pdf-form-group">
                <label className="pdf-form-label">Watermark Text:</label>
                <input
                  type="text"
                  className="pdf-form-input"
                  value={watermarkText}
                  onChange={(e) => setWatermarkText(e.target.value)}
                  placeholder="CONFIDENTIAL"
                />
              </div>
              <div className="pdf-form-group">
                <label className="pdf-form-label">Target Pages:</label>
                <input
                  type="text"
                  className="pdf-form-input"
                  value={watermarkPageSpec}
                  onChange={(e) => setWatermarkPageSpec(e.target.value)}
                  placeholder="all or 1, 2-5"
                />
              </div>
            </>
          )}

          {activeTab === "numbers" && (
            <>
              <div className="pdf-form-group">
                <label className="pdf-form-label">Position:</label>
                <select
                  className="pdf-form-select"
                  value={pageNumberPosition}
                  onChange={(e) => setPageNumberPosition(e.target.value)}
                >
                  <option value="bottom-center">Bottom Center</option>
                  <option value="bottom-right">Bottom Right</option>
                  <option value="top-right">Top Right</option>
                </select>
              </div>
              <div className="pdf-form-group">
                <label className="pdf-form-label">Format Template:</label>
                <input
                  type="text"
                  className="pdf-form-input"
                  value={pageNumberFormat}
                  onChange={(e) => setPageNumberFormat(e.target.value)}
                  placeholder="Page {page} of {total}"
                />
              </div>
            </>
          )}

          {/* Error Message */}
          {errorMsg && (
            <div className="pdf-error-banner">
              <span>⚠️</span>
              <span>{errorMsg}</span>
            </div>
          )}

          {/* Result Artifact Card */}
          {resultArtifact && (
            <div className="pdf-result-card">
              <div className="pdf-result-header">
                <div className="pdf-result-title">
                  <span>✓</span>
                  <span>{resultArtifact.filename}</span>
                </div>
                <div className="pdf-result-actions">
                  <button className="pdf-btn-primary" onClick={handleDownloadResult}>
                    Download
                  </button>
                  {resultArtifact.filename.toLowerCase().endsWith(".pdf") && (
                    <button className="pdf-btn-secondary" onClick={handlePreviewResult}>
                      Preview in Viewer
                    </button>
                  )}
                </div>
              </div>
              <div className="pdf-card-meta-chips">
                <span className="pdf-meta-chip">
                  📦 {(resultArtifact.file_size ? (resultArtifact.file_size / 1024).toFixed(1) : "Ready")} KB
                </span>
                {resultArtifact.page_count && (
                  <span className="pdf-meta-chip">
                    📄 {resultArtifact.page_count} pages
                  </span>
                )}
                {resultArtifact.reduction_percent !== undefined && (
                  <span className="pdf-meta-chip highlight">
                    ⚡ {resultArtifact.reduction_percent > 0 ? `-${resultArtifact.reduction_percent}% reduction` : "Optimized"}
                  </span>
                )}
              </div>
              {resultArtifact.disclaimer && (
                <div className="pdf-card-callout info">
                  <span>ℹ️</span>
                  <span>{resultArtifact.disclaimer}</span>
                </div>
              )}
            </div>
          )}

          {/* PDF Info Result Display */}
          {infoResult && (
            <div className="pdf-result-card">
              <div className="pdf-result-header">
                <div className="pdf-result-title">
                  <span>ℹ️</span>
                  <span>{infoResult.filename} Metadata</span>
                </div>
              </div>
              <div className="pdf-card-meta-chips" style={{ marginTop: "6px" }}>
                <span className="pdf-meta-chip">Pages: {infoResult.page_count}</span>
                <span className="pdf-meta-chip">Size: {infoResult.file_size_formatted}</span>
                <span className="pdf-meta-chip">Paper: {infoResult.dimensions?.paper_size || "Standard"}</span>
                <span className="pdf-meta-chip">Encrypted: {infoResult.is_encrypted ? "Yes" : "No"}</span>
              </div>
              {infoResult.metadata && Object.keys(infoResult.metadata).length > 0 && (
                <div style={{ marginTop: "8px", fontSize: "12px", color: "#475569" }}>
                  {Object.entries(infoResult.metadata).map(([k, v]) => (
                    <div key={k}>
                      <strong>{k}:</strong> {String(v)}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="pdf-modal-footer">
          <button className="pdf-btn-cancel" onClick={onClose} disabled={isProcessing}>
            Cancel
          </button>
          <button className="pdf-btn-submit" onClick={handleSubmit} disabled={isProcessing}>
            {isProcessing ? (
              <>
                <span>Processing...</span>
              </>
            ) : (
              <>
                <span>Run {OPERATIONS.find((o) => o.id === activeTab)?.label}</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
