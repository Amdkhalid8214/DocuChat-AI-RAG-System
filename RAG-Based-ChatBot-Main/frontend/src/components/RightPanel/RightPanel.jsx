import React, { useState } from "react";

export default function RightPanel({
  activeTab = "tools",
  setActiveTab,
  activeDocument,
  allDocuments = [],
  onSelectTool,
  onViewDocument,
  onUploadDocument,
  onNewChat,
  onClearChat,
  onOpenSettings,
  llmModel = "Qwen 2.5 7B",
  embeddingModel = "Nomic Embed Text v1.5"
}) {
  const [currentThumbIndex, setCurrentThumbIndex] = useState(0);

  // Default active document fallback for demo if none selected yet
  const doc = activeDocument || allDocuments[0] || {
    id: "demo-doc",
    filename: "Product_Requirements.pdf",
    page_count: 5,
    chunk_count: 18,
    file_type: "pdf"
  };

  const totalPages = Math.max(doc.page_count || 5, 5);
  const visibleThumbPages = Array.from({ length: Math.min(totalPages, 5) }, (_, i) => i + 1);

  const handlePrevThumb = () => {
    setCurrentThumbIndex((prev) => Math.max(0, prev - 1));
  };

  const handleNextThumb = () => {
    setCurrentThumbIndex((prev) => Math.min(totalPages - 1, prev + 1));
  };

  return (
    <aside className="docuchat-right-panel">
      {/* Top Tabs Switcher */}
      <div className="right-panel-tabs">
        <button
          className={`panel-tab-btn ${activeTab === "tools" ? "active" : ""}`}
          onClick={() => setActiveTab && setActiveTab("tools")}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
          </svg>
          <span>Tools</span>
        </button>
        <button
          className={`panel-tab-btn ${activeTab === "knowledge" ? "active" : ""}`}
          onClick={() => setActiveTab && setActiveTab("knowledge")}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
            <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
            <line x1="12" y1="22.08" x2="12" y2="12" />
          </svg>
          <span>Knowledge Base</span>
        </button>
        <button
          className={`panel-tab-btn ${activeTab === "documents" ? "active" : ""}`}
          onClick={() => setActiveTab && setActiveTab("documents")}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
          </svg>
          <span>Documents</span>
        </button>
      </div>

      <div className="right-panel-content-scroll">
        {/* Section 1: Available Tools */}
        <div className="panel-section">
          <div className="panel-section-header">
            <div className="section-title-with-icon">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
              </svg>
              <h3>Available Tools</h3>
            </div>
            <button className="panel-action-link" onClick={() => onOpenSettings && onOpenSettings()}>
              Manage
            </button>
          </div>

          <div className="tools-list-cards">
            {/* Calculator Card */}
            <div
              className="tool-card"
              onClick={() => onSelectTool && onSelectTool("calculator", "Calculate the total cost if we buy 10 units at $49.99 each with tax.")}
              title="Click to calculate"
            >
              <div className="tool-icon-box blue">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="4" y="2" width="16" height="20" rx="2" />
                  <line x1="8" y1="6" x2="16" y2="6" />
                  <line x1="16" y1="14" x2="16" y2="18" />
                  <path d="M16 10h.01" />
                  <path d="M12 10h.01" />
                  <path d="M8 10h.01" />
                  <path d="M12 14h.01" />
                  <path d="M8 14h.01" />
                  <path d="M12 18h.01" />
                  <path d="M8 18h.01" />
                </svg>
              </div>
              <div className="tool-text-meta">
                <span className="tool-name">Calculator</span>
                <span className="tool-desc">Perform mathematical calculations, conversions, and more.</span>
              </div>
              <span className="tool-arrow">›</span>
            </div>

            {/* Web Search Card */}
            <div
              className="tool-card"
              onClick={() => onSelectTool && onSelectTool("web_search", "Search the web for recent developments in document AI.")}
              title="Click to search web"
            >
              <div className="tool-icon-box purple">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10" />
                  <line x1="2" y1="12" x2="22" y2="12" />
                  <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
                </svg>
              </div>
              <div className="tool-text-meta">
                <span className="tool-name">Web Search</span>
                <span className="tool-desc">Search the web for current information and latest updates.</span>
              </div>
              <span className="tool-arrow">›</span>
            </div>

            {/* Excel Generator Card */}
            <div
              className="tool-card"
              onClick={() => onSelectTool && onSelectTool("excel_generator", "Generate an Excel file with budget and cost breakdown.")}
              title="Click to generate Excel"
            >
              <div className="tool-icon-box green">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                  <path d="M8 13h8" />
                  <path d="M8 17h8" />
                  <path d="M10 9H8" />
                </svg>
              </div>
              <div className="tool-text-meta">
                <span className="tool-name">Excel Generator</span>
                <span className="tool-desc">Create and download Excel files with custom data and analysis.</span>
              </div>
              <span className="tool-arrow">›</span>
            </div>

            {/* PDF/Word Generator Card */}
            <div
              className="tool-card"
              onClick={() => onSelectTool && onSelectTool("doc_generator", "Generate a professional PDF executive summary report.")}
              title="Click to generate report"
            >
              <div className="tool-icon-box pink">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
                  <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
                </svg>
              </div>
              <div className="tool-text-meta">
                <span className="tool-name">PDF/Word Generator</span>
                <span className="tool-desc">Generate professional reports in PDF or Word format.</span>
              </div>
              <span className="tool-arrow">›</span>
            </div>

            {/* PDF Tools Workstation Card */}
            <div
              className="tool-card"
              onClick={() => onSelectTool && onSelectTool("pdf_tools")}
              title="Click to open PDF Tools"
            >
              <div className="tool-icon-box" style={{ background: "#fee2e2", color: "#dc2626" }}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                  <line x1="16" y1="13" x2="8" y2="13" />
                  <line x1="16" y1="17" x2="8" y2="17" />
                </svg>
              </div>
              <div className="tool-text-meta">
                <span className="tool-name">PDF Tools</span>
                <span className="tool-desc">Merge, split, extract, rotate, compress, tables, and convert.</span>
              </div>
              <span className="tool-arrow">›</span>
            </div>
          </div>
        </div>

        {/* Section 2: Document Context */}
        <div className="panel-section">
          <div className="panel-section-header">
            <div className="section-title-with-icon">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
              </svg>
              <h3>Document Context</h3>
            </div>
            <button
              className="panel-action-link"
              onClick={() => setActiveTab && setActiveTab("documents")}
            >
              View all →
            </button>
          </div>

          <div className="document-context-card">
            <div className="doc-context-top-row">
              <div className="doc-icon-red">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                  <line x1="12" y1="18" x2="12" y2="12" />
                  <line x1="9" y1="15" x2="15" y2="15" />
                </svg>
              </div>
              <div className="doc-context-title-col">
                <h4 className="doc-context-filename" title={doc.filename}>
                  {doc.filename}
                </h4>
                <span className="doc-context-sub">
                  Page 2–3 • {doc.page_count ? `${doc.page_count} pages` : "4.2 MB"}
                </span>
              </div>
              <button
                className="btn-view-doc-primary"
                onClick={() => onViewDocument && onViewDocument(doc, 2)}
              >
                View
              </button>
            </div>

            <p className="doc-context-snippet">
              This document outlines the product requirements, including key features, technical specifications, and delivery timeline.
            </p>

            {/* Page Thumbnails Carousel Strip */}
            <div className="thumbnail-carousel-strip">
              <button
                className="btn-carousel-nav left"
                onClick={handlePrevThumb}
                title="Previous page"
              >
                ‹
              </button>

              <div className="thumbnails-row">
                {visibleThumbPages.map((pgNum) => {
                  const isActive = pgNum === 2; // matches screenshot highlight
                  return (
                    <div
                      key={pgNum}
                      className={`thumbnail-card ${isActive ? "active-page" : ""}`}
                      onClick={() => onViewDocument && onViewDocument(doc, pgNum)}
                      title={`Page ${pgNum}`}
                    >
                      <div className="mini-page-lines">
                        <div className="mini-line"></div>
                        <div className="mini-line short"></div>
                        <div className="mini-line"></div>
                        <div className="mini-line half"></div>
                      </div>
                      <span className="mini-page-num">{pgNum}</span>
                    </div>
                  );
                })}
              </div>

              <button
                className="btn-carousel-nav right"
                onClick={handleNextThumb}
                title="Next page"
              >
                ›
              </button>
            </div>
          </div>
        </div>

        {/* Section 3: Quick Actions */}
        <div className="panel-section">
          <div className="panel-section-header">
            <div className="section-title-with-icon">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="3" />
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
              </svg>
              <h3>Quick Actions</h3>
            </div>
          </div>

          <div className="quick-actions-2x2-grid">
            <button className="quick-action-tile" onClick={onUploadDocument}>
              <div className="tile-icon">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="17 8 12 3 7 8" />
                  <line x1="12" y1="3" x2="12" y2="15" />
                </svg>
              </div>
              <div className="tile-info">
                <span className="tile-title">Upload Document</span>
                <span className="tile-sub">PDF, DOCX, TXT, etc.</span>
              </div>
            </button>

            <button className="quick-action-tile" onClick={onNewChat}>
              <div className="tile-icon">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                </svg>
              </div>
              <div className="tile-info">
                <span className="tile-title">New Chat</span>
                <span className="tile-sub">Start a fresh conversation</span>
              </div>
            </button>

            <button className="quick-action-tile" onClick={onClearChat}>
              <div className="tile-icon">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <polyline points="3 6 5 6 21 6" />
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                </svg>
              </div>
              <div className="tile-info">
                <span className="tile-title">Clear Chat</span>
                <span className="tile-sub">Reset current session</span>
              </div>
            </button>

            <button className="quick-action-tile" onClick={onOpenSettings}>
              <div className="tile-icon">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="3" />
                  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
                </svg>
              </div>
              <div className="tile-info">
                <span className="tile-title">Settings</span>
                <span className="tile-sub">Customize your experience</span>
              </div>
            </button>
          </div>
        </div>

        {/* Section 4: Bottom Powered by Banner */}
        <div className="panel-bottom-banner">
          <div className="banner-left-meta">
            <span className="rocket-icon">🚀</span>
            <div className="banner-text">
              <span className="banner-heading">Powered by Advanced AI</span>
              <span className="banner-models">{llmModel} &bull; {embeddingModel}</span>
            </div>
          </div>
          <div className="banner-waves-glow"></div>
        </div>
      </div>
    </aside>
  );
}
