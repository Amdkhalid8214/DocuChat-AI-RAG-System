import React, { useEffect, useRef } from "react";

export default function ToolsPopover({
  isOpen,
  onClose,
  onSelectTool
}) {
  const popoverRef = useRef(null);

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    };
    const handleClickOutside = (e) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target)) {
        onClose();
      }
    };

    if (isOpen) {
      window.addEventListener("keydown", handleKeyDown);
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const toolsList = [
    {
      id: "web_search",
      title: "Web search",
      colorClass: "tool-cyan",
      icon: (
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="10" />
          <line x1="2" y1="12" x2="22" y2="12" />
          <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10z" />
        </svg>
      )
    },
    {
      id: "create_document",
      title: "Create document",
      colorClass: "tool-blue-light",
      icon: (
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
          <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
        </svg>
      )
    },
    {
      id: "pdf_tools",
      title: "PDF Tools",
      colorClass: "tool-red",
      icon: (
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="16" y1="13" x2="8" y2="13" />
          <line x1="16" y1="17" x2="8" y2="17" />
        </svg>
      )
    }
  ];

  return (
    <div className="chatgpt-tools-popover" ref={popoverRef}>
      <div className="tools-popover-header">
        <h4 className="tools-popover-title">Tools</h4>
        <button className="btn-close-popover" onClick={onClose} title="Close tools menu">
          ✕
        </button>
      </div>

      <div className="tools-grid-cards">
        {toolsList.map((tool) => (
          <div
            key={tool.id}
            className="tool-grid-tile"
            onClick={() => {
              onSelectTool(tool.id);
              onClose();
            }}
          >
            <div className={`tool-tile-icon ${tool.colorClass}`}>
              {tool.icon}
            </div>
            <span className="tool-tile-name">{tool.title}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
