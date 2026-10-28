import React from "react";

export default function Navbar({
  activeDoc,
  onDeselectDoc,
  viewMode = "split",
  onToggleSplitView,
  currentUser,
  onRequestAdminMode,
  onSwitchToUserMode,
  onOpenPdfTools
}) {
  const isAdmin = (currentUser?.role || "").toLowerCase().includes("admin");

  return (
    <header className="chatgpt-navbar">
      {/* Left: Active Document Pill */}
      <div className="navbar-left-doc-slot">
        {activeDoc ? (
          <div className="active-doc-tab-chip">
            <span className="doc-pdf-icon-badge">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
              </svg>
            </span>
            <div className="doc-chip-meta">
              <span className="doc-chip-title" title={activeDoc.filename}>
                {activeDoc.filename}
              </span>
              <span className="doc-chip-pages">
                {activeDoc.page_count ? `${activeDoc.page_count} pages` : "PDF"}
              </span>
            </div>
            {onDeselectDoc && (
              <button
                className="btn-doc-chip-close"
                onClick={onDeselectDoc}
                title="Deselect active document"
              >
                ✕
              </button>
            )}
          </div>
        ) : (
          <div className="no-active-doc-hint">
            <span>DocuChat Assistant</span>
          </div>
        )}
      </div>

      {/* Center: Split View Toggle & PDF Tools Workstation */}
      <div className="navbar-center-slot">
        <button
          className={`btn-split-toggle-pill ${viewMode === "split" ? "active" : ""}`}
          onClick={onToggleSplitView}
          title="Toggle Split View / Full Chat"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
            <line x1="12" y1="3" x2="12" y2="21" />
          </svg>
          <span>Split View</span>
        </button>

        <button
          className="btn-pdf-tools-pill"
          onClick={onOpenPdfTools}
          title="Open PDF Tools Workstation (Merge, Split, Rotate, Compress, Tables, etc.)"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
          </svg>
          <span>PDF Tools</span>
        </button>
      </div>

      {/* Right Controls: Exactly one button for User Mode or Admin Mode (no settings icon, no AM icon) */}
      <div className="navbar-right-slot">
        {!isAdmin ? (
          <button
            className="btn-single-mode-toggle user-mode"
            onClick={onRequestAdminMode}
            title="User Mode is active. Click to unlock Admin Mode (Password protected)"
          >
            <span className="mode-icon-symbol">👤</span>
            <span className="mode-status-dot">●</span>
            <span className="mode-label-text">User Mode</span>
          </button>
        ) : (
          <button
            className="btn-single-mode-toggle admin-mode"
            onClick={onSwitchToUserMode}
            title="Admin Mode is active. Click to switch to User Mode"
          >
            <span className="mode-icon-symbol">⚡</span>
            <span className="mode-status-dot">●</span>
            <span className="mode-label-text">Admin Mode</span>
          </button>
        )}
      </div>
    </header>
  );
}
