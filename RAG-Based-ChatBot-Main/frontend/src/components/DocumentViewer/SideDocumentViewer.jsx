import React, { useRef, useEffect, useCallback, useState } from "react";
import SpreadsheetViewer from "./SpreadsheetViewer";

const API_BASE = (typeof window !== "undefined" && window.location.hostname)
  ? `${window.location.protocol}//${window.location.hostname}:5000/api`
  : (process.env.REACT_APP_API_BASE || "http://localhost:5000/api");

function PdfDocumentViewer({
  document: doc,
  currentPage = 1,
  setCurrentPage,
  activeHighlights = [],
  focusedCitation = null,
  viewMode = "split",
  onToggleSplitView,
  onToggleMaximize,
  onCloseViewer
}) {
  const [totalPages, setTotalPages] = useState(doc?.page_count || 1);
  const [pdfDoc, setPdfDoc] = useState(null);
  const [textContent, setTextContent] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const [retryCount, setRetryCount] = useState(0);
  const [pageInput, setPageInput] = useState(currentPage);
  const [renderCycle, setRenderCycle] = useState(0);

  // Zoom State & Modes: "fit-width" (default) | "fit-page" | "actual" | "custom"
  const [zoomMode, setZoomMode] = useState("fit-width");
  const [zoomScale, setZoomScale] = useState(1.0);
  const [rotation, setRotation] = useState(0);
  const [zoomDropdownOpen, setZoomDropdownOpen] = useState(false);

  // Dimensions
  const [nativeDims, setNativeDims] = useState({ width: 612, height: 792 });
  const [renderedDims, setRenderedDims] = useState({ width: 612, height: 792 });

  // DOM Refs
  const stageRef = useRef(null);
  const canvasRef = useRef(null);
  const renderTaskRef = useRef(null);
  const evidenceRef = useRef(null);
  const zoomPickerRef = useRef(null);

  // Synchronize local page input with prop
  useEffect(() => {
    setPageInput(currentPage);
  }, [currentPage]);

  // Synchronize totalPages when doc updates
  useEffect(() => {
    if (doc?.page_count && doc.page_count > 1) {
      setTotalPages(doc.page_count);
    }
  }, [doc]);

  // Close zoom dropdown on outside click
  useEffect(() => {
    const handleOutsideClick = (e) => {
      if (zoomPickerRef.current && !zoomPickerRef.current.contains(e.target)) {
        setZoomDropdownOpen(false);
      }
    };
    if (zoomDropdownOpen) {
      window.addEventListener("mousedown", handleOutsideClick);
    }
    return () => window.removeEventListener("mousedown", handleOutsideClick);
  }, [zoomDropdownOpen]);

  // Calculate dynamic scale for fit-width or fit-page based on available container dimensions
  const calculateScale = useCallback(
    (mode, nativeW, nativeH) => {
      if (!stageRef.current) return 1.0;
      const stage = stageRef.current;
      // Padding: 40px horizontal margin total, 32px vertical
      const availableWidth = Math.max(300, stage.clientWidth - 48);
      const availableHeight = Math.max(300, stage.clientHeight - 48);

      const targetW = rotation % 180 === 0 ? nativeW : nativeH;
      const targetH = rotation % 180 === 0 ? nativeH : nativeW;

      if (mode === "fit-width") {
        return Math.max(0.35, Math.min(3.0, availableWidth / targetW));
      } else if (mode === "fit-page") {
        const scaleW = availableWidth / targetW;
        const scaleH = availableHeight / targetH;
        return Math.max(0.35, Math.min(3.0, Math.min(scaleW, scaleH)));
      } else if (mode === "actual") {
        return 1.0;
      }
      return zoomScale;
    },
    [rotation, zoomScale]
  );

  // Effective scale to use
  const getEffectiveScale = useCallback(
    (mode, scaleVal, nativeW, nativeH) => {
      if (mode === "custom") return scaleVal;
      return calculateScale(mode, nativeW, nativeH);
    },
    [calculateScale]
  );

  // Load PDF / Document via fetch + PDF.js
  useEffect(() => {
    let isCancelled = false;
    setIsLoading(true);
    setErrorMsg(null);
    setTextContent(null);
    setPdfDoc(null);

    const loadDocument = async () => {
      if (!doc?.id) {
        setIsLoading(false);
        return;
      }

      const ext = (doc.file_type || doc.filename?.split(".").pop() || "").toLowerCase();
      const isTextFile = ["txt", "md", "html", "htm", "json"].includes(ext);

      // If document is currently in ingestion / conversion / parsing pipeline, display status without premature PDF parse errors
      if (doc.status && doc.status !== "ready" && !isTextFile) {
        if (doc.status === "failed") {
          setIsLoading(false);
          setErrorMsg(doc.status_message || "Document processing failed. Please retry ingestion.");
          return;
        }
        setIsLoading(true);
        setErrorMsg(null);
        return;
      }

      try {
        const token = localStorage.getItem("docuchat_token");
        const authHeaders = {};
        if (token) {
          authHeaders["Authorization"] = `Bearer ${token}`;
        }

        const primaryUrl = `${API_BASE}/documents/${doc.id}/file`;
        const res = await fetch(primaryUrl, {
          headers: authHeaders,
        });

        if (!res.ok) {
          if (res.status === 404) {
            throw new Error("Document file was not found on server.");
          } else if (res.status === 401 || res.status === 403) {
            throw new Error("Access denied: You do not have permission to view this document.");
          } else {
            throw new Error(`Server returned HTTP ${res.status}: ${res.statusText}`);
          }
        }

        if (isTextFile) {
          const text = await res.text();
          if (!isCancelled) {
            setTextContent(text);
            setTotalPages(1);
            setIsLoading(false);
          }
          return;
        }

        // Handle PDF
        const arrayBuffer = await res.arrayBuffer();
        if (isCancelled) return;

        // Ensure PDF.js is ready (retry up to 30 times x 100ms if CDN script is still downloading)
        let pdfjs = window.pdfjsLib;
        if (!pdfjs) {
          for (let i = 0; i < 30; i++) {
            await new Promise((r) => setTimeout(r, 100));
            if (window.pdfjsLib) {
              pdfjs = window.pdfjsLib;
              break;
            }
          }
        }

        if (!pdfjs) {
          throw new Error("PDF rendering engine is unavailable. Please check your network connection.");
        }

        if (!pdfjs.GlobalWorkerOptions.workerSrc) {
          pdfjs.GlobalWorkerOptions.workerSrc =
            "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
        }

        const loadingTask = pdfjs.getDocument({
          data: new Uint8Array(arrayBuffer),
          cMapUrl: "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/cmaps/",
          cMapPacked: true,
        });

        const loaded = await loadingTask.promise;
        if (!isCancelled) {
          setPdfDoc(loaded);
          setTotalPages(loaded.numPages);
          setIsLoading(false);
          setErrorMsg(null);
        }
      } catch (err) {
        console.error("Document load error:", err);
        if (!isCancelled) {
          setErrorMsg(err.message || "Could not load document preview from server.");
          setIsLoading(false);
        }
      }
    };

    loadDocument();
    return () => {
      isCancelled = true;
    };
  }, [doc?.id, doc?.status, retryCount]);

  // Render Page on Canvas with High-DPI (Device Pixel Ratio)
  const renderPage = useCallback(
    async (pdf, pageNum, mode, manualScale, rot) => {
      if (!pdf || !canvasRef.current) return;

      // Cancel any ongoing render task to eliminate race conditions
      if (renderTaskRef.current) {
        try {
          renderTaskRef.current.cancel();
        } catch { }
      }

      try {
        const page = await pdf.getPage(pageNum);
        const canvas = canvasRef.current;
        if (!canvas) return;

        // Obtain native unscaled page dimensions
        const unscaledViewport = page.getViewport({ scale: 1.0, rotation: rot });
        const nW = unscaledViewport.width;
        const nH = unscaledViewport.height;
        setNativeDims({ width: nW, height: nH });

        // Calculate responsive scale
        const effScale = getEffectiveScale(mode, manualScale, nW, nH);

        const viewport = page.getViewport({ scale: effScale, rotation: rot });
        const dpr = window.devicePixelRatio || 1;

        const cssWidth = Math.floor(viewport.width);
        const cssHeight = Math.floor(viewport.height);

        setRenderedDims({ width: cssWidth, height: cssHeight });

        // Backing-store resolution scaled by DPR for razor-sharp text & math formulas
        canvas.width = Math.floor(cssWidth * dpr);
        canvas.height = Math.floor(cssHeight * dpr);

        // CSS display size in exact layout pixels
        canvas.style.width = `${cssWidth}px`;
        canvas.style.height = `${cssHeight}px`;

        const ctx = canvas.getContext("2d", { alpha: false });
        if (!ctx) return;

        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = "high";

        // Reset transform & paint pure white document backing
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        const renderContext = {
          canvasContext: ctx,
          viewport: viewport,
          transform: [dpr, 0, 0, dpr, 0, 0] // High-DPI backing-store scaling
        };

        const task = page.render(renderContext);
        renderTaskRef.current = task;
        await task.promise;
        renderTaskRef.current = null;
        setRenderCycle((c) => c + 1);
      } catch (err) {
        if (err?.name !== "RenderingCancelledException") {
          console.error("PDF render error:", err);
        }
      }
    },
    [getEffectiveScale]
  );

  // Render on document/page/zoom/rotation change
  useEffect(() => {
    if (pdfDoc) {
      renderPage(pdfDoc, currentPage, zoomMode, zoomScale, rotation);
    }
  }, [pdfDoc, currentPage, zoomMode, zoomScale, rotation, renderPage]);

  // Responsive ResizeObserver to recalculate Fit-to-Width and Fit-to-Page on window/panel resize
  useEffect(() => {
    if (!stageRef.current) return;
    const observer = new ResizeObserver(() => {
      if (pdfDoc && (zoomMode === "fit-width" || zoomMode === "fit-page")) {
        renderPage(pdfDoc, currentPage, zoomMode, zoomScale, rotation);
      }
    });

    observer.observe(stageRef.current);
    return () => observer.disconnect();
  }, [pdfDoc, currentPage, zoomMode, zoomScale, rotation, renderPage]);

  // Smooth scroll to evidence highlight when focusedCitation or page renders
  useEffect(() => {
    if (focusedCitation) {
      const timer = setTimeout(() => {
        if (evidenceRef.current) {
          evidenceRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      }, 60);
      return () => clearTimeout(timer);
    }
  }, [focusedCitation, currentPage, renderCycle, renderedDims]);

  // Keyboard navigation shortcuts
  useEffect(() => {
    const handleKeyDown = (e) => {
      // Ignore if focus is in an input field
      if (["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) return;

      if (e.key === "ArrowLeft") {
        if (currentPage > 1) setCurrentPage((p) => Math.max(1, p - 1));
      } else if (e.key === "ArrowRight") {
        if (currentPage < totalPages) setCurrentPage((p) => Math.min(totalPages, p + 1));
      } else if (e.key === "+" || e.key === "=") {
        handleZoomIn();
      } else if (e.key === "-") {
        handleZoomOut();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  });

  const handlePageChange = (newPage) => {
    const valid = Math.max(1, Math.min(totalPages, newPage));
    setCurrentPage(valid);
  };

  const handlePageInputSubmit = (e) => {
    if (e.key === "Enter") {
      const p = parseInt(pageInput, 10);
      if (!isNaN(p)) {
        handlePageChange(p);
      } else {
        setPageInput(currentPage);
      }
    }
  };

  const currentEffectiveScale = getEffectiveScale(zoomMode, zoomScale, nativeDims.width, nativeDims.height);

  const handleZoomIn = () => {
    const nextScale = Math.min(3.0, currentEffectiveScale + 0.15);
    setZoomMode("custom");
    setZoomScale(nextScale);
  };

  const handleZoomOut = () => {
    const nextScale = Math.max(0.35, currentEffectiveScale - 0.15);
    setZoomMode("custom");
    setZoomScale(nextScale);
  };

  const handleSelectZoomPreset = (mode) => {
    setZoomMode(mode);
    setZoomDropdownOpen(false);
  };

  const handleSelectZoomScale = (scaleVal) => {
    setZoomMode("custom");
    setZoomScale(scaleVal);
    setZoomDropdownOpen(false);
  };

  const handleRotateClockwise = () => {
    setRotation((r) => (r + 90) % 360);
  };

  const docTitle = doc?.filename || "Document";

  return (
    <aside className="chatgpt-side-document-panel">
      {/* Top Professional Document Toolbar */}
      <div className="doc-viewer-top-toolbar">
        {/* Left: Document icon + Title + Page subtitle */}
        <div className="doc-toolbar-left-meta">
          <div className="doc-file-type-icon" title="PDF Document">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
            </svg>
          </div>
          <div className="doc-title-stack">
            <span className="doc-toolbar-filename" title={docTitle}>
              {docTitle}
            </span>
            <span className="doc-toolbar-pagesub">
              Page {currentPage} of {totalPages}
            </span>
          </div>
        </div>

        {/* Center: Page Controls & Complete Zoom Suite */}
        <div className="doc-toolbar-center-controls">
          {/* Page Navigation */}
          <div className="toolbar-btn-group">
            <button
              className="btn-toolbar-icon"
              onClick={() => handlePageChange(currentPage - 1)}
              disabled={currentPage <= 1}
              title="Previous Page (Left Arrow)"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <polyline points="15 18 9 12 15 6" />
              </svg>
            </button>

            <div className="toolbar-page-input-box">
              <input
                type="text"
                className="page-number-box-input"
                value={pageInput}
                onChange={(e) => setPageInput(e.target.value)}
                onKeyDown={handlePageInputSubmit}
                onBlur={() => {
                  const p = parseInt(pageInput, 10);
                  if (!isNaN(p)) handlePageChange(p);
                  else setPageInput(currentPage);
                }}
                title="Jump to page"
              />
              <span className="page-total-label">/ {totalPages}</span>
            </div>

            <button
              className="btn-toolbar-icon"
              onClick={() => handlePageChange(currentPage + 1)}
              disabled={currentPage >= totalPages}
              title="Next Page (Right Arrow)"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <polyline points="9 18 15 12 9 6" />
              </svg>
            </button>
          </div>

          <div className="toolbar-divider-v" />

          {/* Zoom Controls */}
          <div className="toolbar-btn-group">
            <button
              className="btn-toolbar-icon"
              onClick={handleZoomOut}
              disabled={currentEffectiveScale <= 0.4}
              title="Zoom Out (−)"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
                <line x1="8" y1="11" x2="14" y2="11" />
              </svg>
            </button>

            {/* Zoom Percentage Dropdown */}
            <div className="zoom-preset-picker-container" ref={zoomPickerRef}>
              <button
                className="btn-zoom-preset-trigger"
                onClick={() => setZoomDropdownOpen((prev) => !prev)}
                title="Zoom Presets"
              >
                <span>{Math.round(currentEffectiveScale * 100)}%</span>
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <polyline points="6 9 12 15 18 9" />
                </svg>
              </button>

              {zoomDropdownOpen && (
                <div className="zoom-presets-dropdown-menu">
                  <div className="zoom-menu-section-label">Page Sizing</div>
                  <button
                    className={`zoom-preset-item ${zoomMode === "fit-width" ? "active" : ""}`}
                    onClick={() => handleSelectZoomPreset("fit-width")}
                  >
                    <span>Fit to Width</span>
                    <span className="zoom-preset-shortcut">↔</span>
                  </button>
                  <button
                    className={`zoom-preset-item ${zoomMode === "fit-page" ? "active" : ""}`}
                    onClick={() => handleSelectZoomPreset("fit-page")}
                  >
                    <span>Fit to Page</span>
                    <span className="zoom-preset-shortcut">⤢</span>
                  </button>
                  <button
                    className={`zoom-preset-item ${zoomMode === "actual" ? "active" : ""}`}
                    onClick={() => handleSelectZoomPreset("actual")}
                  >
                    <span>Actual Size (100%)</span>
                    <span className="zoom-preset-shortcut">100%</span>
                  </button>

                  <div className="zoom-menu-divider" />
                  <div className="zoom-menu-section-label">Zoom Scale</div>
                  {[50, 75, 100, 125, 150, 200, 250].map((pct) => (
                    <button
                      key={pct}
                      className={`zoom-preset-item ${zoomMode === "custom" && Math.round(zoomScale * 100) === pct ? "active" : ""}`}
                      onClick={() => handleSelectZoomScale(pct / 100)}
                    >
                      <span>{pct}%</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <button
              className="btn-toolbar-icon"
              onClick={handleZoomIn}
              disabled={currentEffectiveScale >= 2.5}
              title="Zoom In (+)"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
                <line x1="11" y1="8" x2="11" y2="14" />
                <line x1="8" y1="11" x2="14" y2="11" />
              </svg>
            </button>

            {/* Quick Fit-to-Width Button */}
            <button
              className={`btn-toolbar-icon ${zoomMode === "fit-width" ? "btn-active" : ""}`}
              onClick={() => setZoomMode("fit-width")}
              title="Fit to Width"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="7 8 3 12 7 16" />
                <polyline points="17 8 21 12 17 16" />
                <line x1="3" y1="12" x2="21" y2="12" />
              </svg>
            </button>

            {/* Quick Fit-to-Page Button */}
            <button
              className={`btn-toolbar-icon ${zoomMode === "fit-page" ? "btn-active" : ""}`}
              onClick={() => setZoomMode("fit-page")}
              title="Fit to Page"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                <line x1="3" y1="9" x2="21" y2="9" />
                <line x1="9" y1="21" x2="9" y2="9" />
              </svg>
            </button>

            {/* Rotate Button */}
            <button
              className="btn-toolbar-icon"
              onClick={handleRotateClockwise}
              title="Rotate Page 90° Clockwise"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21.5 2v6h-6" />
                <path d="M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67" />
              </svg>
            </button>
          </div>
        </div>

        {/* Right: Maximize / Reader Mode & Close Controls */}
        <div className="doc-toolbar-right-controls">
          <button
            className={`btn-toolbar-icon ${viewMode === "document" ? "btn-active" : ""}`}
            onClick={onToggleMaximize}
            title={viewMode === "document" ? "Restore Split View" : "Maximize Document Viewer (Reader Mode)"}
          >
            {viewMode === "document" ? (
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="4 14 10 14 10 20" />
                <polyline points="20 10 14 10 14 4" />
                <line x1="14" y1="10" x2="21" y2="3" />
                <line x1="3" y1="21" x2="10" y2="14" />
              </svg>
            ) : (
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="15 3 21 3 21 9" />
                <polyline points="9 21 3 21 3 15" />
                <line x1="21" y1="3" x2="14" y2="10" />
                <line x1="3" y1="21" x2="10" y2="14" />
              </svg>
            )}
          </button>

          <button
            className="btn-toolbar-icon btn-toolbar-close"
            onClick={onCloseViewer || onToggleSplitView}
            title="Close Document Viewer"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      </div>

      {/* Document View Canvas Stage */}
      <div className="doc-viewer-scrollable-stage" ref={stageRef}>
        {isLoading && (
          <div className="doc-loading-overlay">
            <div className="doc-spinner" />
            <span>Rendering high-resolution document page...</span>
          </div>
        )}

        {/* Clean Document Page Paper Sheet */}
        <div
          className="rendered-pdf-page-sheet"
          style={{
            width: pdfDoc ? `${renderedDims.width}px` : "100%",
            maxWidth: pdfDoc ? `${renderedDims.width}px` : "800px",
            minHeight: pdfDoc ? `${renderedDims.height}px` : "460px"
          }}
        >
          {/* Canvas always mounted to eliminate ref timing race conditions */}
          <div
            className="canvas-wrapper-sheet"
            style={{ display: pdfDoc ? "block" : "none" }}
          >
            <canvas ref={canvasRef} className="native-pdf-canvas" />

            {/* Exact Coordinate Citation Evidence Overlays */}
            <div className="canvas-highlights-overlay">
              {(() => {
                const rawBoxes = ((activeHighlights && activeHighlights.length > 0)
                  ? activeHighlights
                  : (focusedCitation?.bboxes || [])
                ).filter((b) => {
                  if (b.doc_id && doc?.id && b.doc_id !== doc.id) return false;
                  return Number(b.page || focusedCitation?.page || currentPage) === Number(currentPage);
                });

                // Merge contiguous lines on the current page into unified whole boxes like Image 1 (not sentence-wise)
                const sortedBoxes = [...rawBoxes].sort((a, b) => (a.y0 || 0) - (b.y0 || 0));
                const wholeBoxes = [];
                for (const b of sortedBoxes) {
                  if (wholeBoxes.length === 0) {
                    wholeBoxes.push({ ...b });
                  } else {
                    const last = wholeBoxes[wholeBoxes.length - 1];
                    const gap = (b.y0 || 0) - (last.y1 || 0);
                    // Merge if lines are part of the same contiguous paragraph or line block (vertical gap <= 18)
                    if (gap <= 18 && gap >= -15) {
                      last.x0 = Math.min(last.x0, b.x0);
                      last.y0 = Math.min(last.y0, b.y0);
                      last.x1 = Math.max(last.x1, b.x1);
                      last.y1 = Math.max(last.y1, b.y1);
                      if (b.source_index) last.source_index = b.source_index;
                    } else {
                      wholeBoxes.push({ ...b });
                    }
                  }
                }

                const focusedIndex = wholeBoxes.findIndex(
                  (b) => focusedCitation && Number(b.source_index) === Number(focusedCitation.source_index)
                );
                const refIndex = focusedIndex >= 0 ? focusedIndex : 0;

                return wholeBoxes.map((box, idx) => {
                  const pWidth = box.page_width || nativeDims.width || 612;
                  const pHeight = box.page_height || nativeDims.height || 792;
                  const scaleX = renderedDims.width / pWidth;
                  const scaleY = renderedDims.height / pHeight;

                  const isBottomLeft = box.coord_origin === "BOTTOMLEFT";
                  const top = isBottomLeft
                    ? (pHeight - box.y1) * scaleY
                    : (box.y0 || 0) * scaleY;
                  const height = Math.max(16, Math.abs((box.y1 || 20) - (box.y0 || 0)) * scaleY);
                  const left = (box.x0 || 0) * scaleX;
                  const width = Math.max(20, Math.abs((box.x1 || 100) - (box.x0 || 0)) * scaleX);

                  const isFocused = focusedCitation && Number(box.source_index) === Number(focusedCitation.source_index);

                  return (
                    <div
                      key={idx}
                      ref={idx === refIndex ? evidenceRef : null}
                      className={`canvas-highlight-rect ${isFocused ? "highlight-pulsing" : ""}`}
                      style={{
                        top: `${top}px`,
                        left: `${left}px`,
                        width: `${width}px`,
                        height: `${height}px`
                      }}
                      title={`Page ${currentPage} source highlight`}
                    />
                  );
                });
              })()}
            </div>
          </div>

          {/* Text/Markdown preview if document is a plain text file */}
          {textContent !== null && !pdfDoc && (
            <div className="doc-text-preview-container">
              <pre className="doc-text-pre">{textContent}</pre>
            </div>
          )}

          {/* Clear, helpful status view when preview is loading or error occurs */}
          {!pdfDoc && textContent === null && (
            <div className="doc-empty-state-card">
              {isLoading ? (
                <div className="doc-loading-block">
                  <div className="doc-spinner" />
                  <p className="doc-loading-text">
                    {doc?.status && doc.status !== "ready"
                      ? `Processing document (${doc.status_message || doc.status})...`
                      : "Loading document preview..."}
                  </p>
                  {doc?.status && doc.status !== "ready" && (
                    <div style={{ marginTop: "8px" }}>
                      <span className="doc-meta-val status-badge-inline" style={{ textTransform: "capitalize" }}>
                        Status: {doc.status}
                      </span>
                    </div>
                  )}
                </div>
              ) : errorMsg ? (
                <div className="doc-error-block">
                  <div className="doc-error-icon">
                    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#ef4444" strokeWidth="2">
                      <circle cx="12" cy="12" r="10" />
                      <line x1="12" y1="8" x2="12" y2="12" />
                      <line x1="12" y1="16" x2="12.01" y2="16" />
                    </svg>
                  </div>
                  <h4 className="doc-error-title">Could not display document preview</h4>
                  <p className="doc-error-desc">{errorMsg}</p>

                  <div className="doc-error-meta-box">
                    <div className="doc-meta-row">
                      <span className="doc-meta-label">File:</span>
                      <span className="doc-meta-val">{docTitle}</span>
                    </div>
                    {doc?.file_type && (
                      <div className="doc-meta-row">
                        <span className="doc-meta-label">Format:</span>
                        <span className="doc-meta-val">{doc.file_type.toUpperCase()}</span>
                      </div>
                    )}
                    {doc?.status && (
                      <div className="doc-meta-row">
                        <span className="doc-meta-label">Status:</span>
                        <span className="doc-meta-val status-badge-inline">{doc.status}</span>
                      </div>
                    )}
                  </div>

                  <div className="doc-error-actions">
                    <button
                      className="btn-retry-doc"
                      onClick={() => setRetryCount((c) => c + 1)}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <polyline points="23 4 23 10 17 10" />
                        <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
                      </svg>
                      Try Again
                    </button>
                    {doc?.id && (
                      <a
                        href={`${API_BASE}/documents/${doc.id}/file`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="btn-download-doc"
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                          <polyline points="7 10 12 15 17 10" />
                          <line x1="12" y1="15" x2="12" y2="3" />
                        </svg>
                        Download Original
                      </a>
                    )}
                  </div>
                </div>
              ) : (
                <div className="doc-placeholder-block">
                  <div className="doc-file-big-icon">
                    <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                      <polyline points="14 2 14 8 20 8" />
                    </svg>
                  </div>
                  <h4>{docTitle}</h4>
                  <p className="doc-placeholder-sub">Select a document from the sidebar to preview.</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}

function UnsupportedViewer({
  document: doc,
  ext,
  viewMode,
  onToggleMaximize,
  onCloseViewer,
  onToggleSplitView
}) {
  const docTitle = doc?.filename || "Document";
  const docId = doc?.id;

  const handleDownloadOriginal = () => {
    if (!docId) return;
    const token = localStorage.getItem("docuchat_token");
    const authQuery = token ? `?token=${encodeURIComponent(token)}` : "";
    window.open(`${API_BASE}/documents/${docId}/file${authQuery}`, "_blank");
  };

  return (
    <aside className="chatgpt-side-document-panel">
      <div className="doc-viewer-top-toolbar">
        <div className="doc-toolbar-left-meta">
          <div className="doc-file-type-icon" title="Unsupported file">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
            </svg>
          </div>
          <div className="doc-title-stack">
            <span className="doc-toolbar-filename" title={docTitle}>
              {docTitle}
            </span>
            <span className="doc-toolbar-pagesub">Unsupported format</span>
          </div>
        </div>

        <div className="doc-toolbar-right-controls">
          <button
            className={`btn-toolbar-icon ${viewMode === "document" ? "btn-active" : ""}`}
            onClick={onToggleMaximize}
            title={viewMode === "document" ? "Restore Split View" : "Maximize Document Viewer"}
          >
            {viewMode === "document" ? (
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="4 14 10 14 10 20" />
                <polyline points="20 10 14 10 14 4" />
                <line x1="14" y1="10" x2="21" y2="3" />
                <line x1="3" y1="21" x2="10" y2="14" />
              </svg>
            ) : (
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="15 3 21 3 21 9" />
                <polyline points="9 21 3 21 3 15" />
                <line x1="21" y1="3" x2="14" y2="10" />
                <line x1="3" y1="21" x2="10" y2="14" />
              </svg>
            )}
          </button>
          <button
            className="btn-toolbar-icon btn-toolbar-close"
            onClick={onCloseViewer || onToggleSplitView}
            title="Close Document Viewer"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      </div>

      <div className="doc-viewer-scrollable-stage">
        <div className="doc-empty-state-card">
          <div className="doc-error-block">
            <div className="doc-error-icon">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="2">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
            </div>
            <h4 className="doc-error-title">Preview not available for this file type</h4>
            <p className="doc-error-desc">
              Visual preview is not supported for <strong>.{ext || "unknown"}</strong> files. You can still ask questions about its content in chat, or download the original file to view it locally.
            </p>
            <div className="doc-error-meta-box">
              <div className="doc-meta-row">
                <span className="doc-meta-label">File:</span>
                <span className="doc-meta-val">{docTitle}</span>
              </div>
              <div className="doc-meta-row">
                <span className="doc-meta-label">Format:</span>
                <span className="doc-meta-val">{(ext || "unknown").toUpperCase()}</span>
              </div>
              {doc?.status && (
                <div className="doc-meta-row">
                  <span className="doc-meta-label">Status:</span>
                  <span className="doc-meta-val status-badge-inline">{doc.status}</span>
                </div>
              )}
            </div>
            <div className="doc-error-actions">
              <button className="btn-download-orig" onClick={handleDownloadOriginal}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="7 10 12 15 17 10" />
                  <line x1="12" y1="15" x2="12" y2="3" />
                </svg>
                Download Original File
              </button>
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
}

const SUPPORTED_SPREADSHEET_EXTS = ["xlsx", "xls", "csv"];
const SUPPORTED_TEXT_EXTS = ["txt", "md", "html", "htm", "json", "py", "js", "log", "xml", "yaml", "yml"];

export default function SideDocumentViewer(props) {
  const { document: doc } = props;
  const ext = (doc?.file_type || doc?.filename?.split(".").pop() || "").toLowerCase();

  // Route 1: Spreadsheets (Excel .xlsx, .xls, .csv)
  if (SUPPORTED_SPREADSHEET_EXTS.includes(ext)) {
    return <SpreadsheetViewer {...props} />;
  }

  // Route 2: PDF or plain text
  const isPdf = ext === "pdf" || (!ext && !SUPPORTED_TEXT_EXTS.includes(ext));
  const isText = SUPPORTED_TEXT_EXTS.includes(ext);

  if (isPdf || isText) {
    return <PdfDocumentViewer {...props} />;
  }

  // Route 3: Unsupported format notice
  return <UnsupportedViewer {...props} ext={ext} />;
}
