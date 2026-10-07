import React, { useState, useEffect, useRef, useCallback } from "react";
import "./App.css";

const API_BASE = "http://localhost:5000/api";

// Helper: Parse inline citations [1], [2] into interactive clickable tags
function renderMarkdownWithCitations(content, citations, onCitationClick) {
  if (!content) return null;
  const lines = content.split("\n");

  return (
    <div className="markdown-content">
      {lines.map((line, lineIdx) => {
        // Table row detection
        if (line.trim().startsWith("|") && line.trim().endsWith("|")) {
          return (
            <div
              key={lineIdx}
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: "12.5px",
                background: "var(--card-bg)",
                padding: "3px 8px",
                borderRadius: "4px",
                margin: "2px 0",
              }}
            >
              {line}
            </div>
          );
        }

        // Code block separator
        if (line.trim().startsWith("```")) {
          return (
            <div
              key={lineIdx}
              style={{
                borderTop: "1px dashed var(--toolbar-border)",
                margin: "8px 0",
              }}
            />
          );
        }

        // Parse citation tags like [1], [2], [1, 2]
        const parts = line.split(/(\[\d+(?:,\s*\d+)*\])/g);

        return (
          <p
            key={lineIdx}
            style={{
              minHeight: line.trim() ? "auto" : "8px",
              margin: "6px 0",
              lineHeight: 1.6,
            }}
          >
            {parts.map((part, pIdx) => {
              const citeMatch = part.match(/^\[(\d+(?:,\s*\d+)*)\]$/);
              if (citeMatch) {
                const numbers = citeMatch[1]
                  .split(",")
                  .map((n) => parseInt(n.trim(), 10));
                return (
                  <span key={pIdx}>
                    {numbers.map((num) => {
                      const matchedCitation = citations?.find(
                        (c) => c.source_index === num
                      );
                      return (
                        <button
                          key={num}
                          className="citation-pill"
                          title={
                            matchedCitation
                              ? `Page ${matchedCitation.page}: ${matchedCitation.snippet?.slice(0, 100)}...`
                              : `Citation [${num}]`
                          }
                          onClick={() =>
                            onCitationClick &&
                            onCitationClick(num, matchedCitation)
                          }
                        >
                          [{num}]
                        </button>
                      );
                    })}
                  </span>
                );
              }

              // Bold text parsing
              const subParts = part.split(/(\*\*.*?\*\*)/g);
              return subParts.map((sub, sIdx) => {
                if (sub.startsWith("**") && sub.endsWith("**")) {
                  return (
                    <strong key={sIdx} style={{ fontWeight: 650 }}>
                      {sub.slice(2, -2)}
                    </strong>
                  );
                }
                return sub;
              });
            })}
          </p>
        );
      })}
    </div>
  );
}

export default function App() {
  // Theme State: "dark" or "light"
  const [theme, setTheme] = useState(() => localStorage.getItem("docuchat_theme") || "dark");
  const toggleTheme = () => {
    const nextTheme = theme === "dark" ? "light" : "dark";
    setTheme(nextTheme);
    localStorage.setItem("docuchat_theme", nextTheme);
  };

  // ChatGPT 3-Lines Top-Right Menu State
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef(null);

  // Close menu on click outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Navigation & Tabs
  const [navTab, setNavTab] = useState("chat"); // "chat" | "ask"

  // User Authentication State
  const [authToken, setAuthToken] = useState(() => localStorage.getItem("docuchat_token") || "");
  const [currentUser, setCurrentUser] = useState(() => {
    try {
      const saved = localStorage.getItem("docuchat_user");
      return saved ? JSON.parse(saved) : null;
    } catch {
      return null;
    }
  });
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [authTab, setAuthTab] = useState("login"); // "login" | "register"
  const [authUsername, setAuthUsername] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authEmail, setAuthEmail] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [authError, setAuthError] = useState("");
  const [authLoading, setAuthLoading] = useState(false);

  // Conversations & Messages
  const [conversations, setConversations] = useState([]);
  const [activeConvId, setActiveConvId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [abortController, setAbortController] = useState(null);

  // Ask a Question Tab State (Single-Turn Q&A)
  const [askQuery, setAskQuery] = useState("");
  const [askAnswer, setAskAnswer] = useState("");
  const [askCitations, setAskCitations] = useState([]);
  const [isAsking, setIsAsking] = useState(false);

  // Documents & Scope
  const [documents, setDocuments] = useState([]);
  const [selectedDocScope, setSelectedDocScope] = useState("all");
  const [uploading, setUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState("");

  // Developer Settings Drawer
  const [devSettingsOpen, setDevSettingsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState("rag"); // "rag" | "docs" | "history"
  const [topK, setTopK] = useState(5);
  const [scoreThreshold, setScoreThreshold] = useState(0.25);
  const [fusionMethod, setFusionMethod] = useState("rrf");
  const [fusionAlpha, setFusionAlpha] = useState(0.5);
  const [routerMode, setRouterMode] = useState("hybrid");
  const [temperature, setTemperature] = useState(0.1);

  // PDF Viewer Drawer
  const [viewerOpen, setViewerOpen] = useState(false);
  const [viewerDoc, setViewerDoc] = useState(null);
  const [viewerPdf, setViewerPdf] = useState(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [zoomScale, setZoomScale] = useState(1.0);
  const [activeHighlights, setActiveHighlights] = useState([]);
  const [focusedCitationIndex, setFocusedCitationIndex] = useState(null);

  // Refs
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);
  const canvasRef = useRef(null);

  // Helper for auth headers
  const getAuthHeaders = useCallback(() => {
    const headers = { "Content-Type": "application/json" };
    if (authToken) {
      headers["Authorization"] = `Bearer ${authToken}`;
    }
    return headers;
  }, [authToken]);

  // Scroll to bottom of message list
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };
  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Load initial conversations & documents
  useEffect(() => {
    fetchConversations();
    fetchDocuments();
    if (authToken) {
      verifyCurrentUser();
    }
  }, []);

  // Poll processing documents
  useEffect(() => {
    const hasProcessing = documents.some((d) => d.status === "processing");
    if (!hasProcessing) return;
    const interval = setInterval(fetchDocuments, 3000);
    return () => clearInterval(interval);
  }, [documents]);

  // Verify current user session
  const verifyCurrentUser = async () => {
    if (!authToken) return;
    try {
      const res = await fetch(`${API_BASE}/auth/me`, {
        headers: getAuthHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        setCurrentUser(data.user);
        localStorage.setItem("docuchat_user", JSON.stringify(data.user));
      } else {
        handleLogout();
      }
    } catch (e) {
      console.error("Error verifying user session:", e);
    }
  };

  // Auth: Login / Register
  const handleAuthSubmit = async (e) => {
    if (e) e.preventDefault();
    setAuthError("");
    setAuthLoading(true);

    const endpoint = authTab === "login" ? `${API_BASE}/auth/login` : `${API_BASE}/auth/register`;
    const payload =
      authTab === "login"
        ? { username: authUsername.trim(), password: authPassword }
        : { username: authUsername.trim(), password: authPassword, email: authEmail.trim() || null };

    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Authentication failed");
      }

      setAuthToken(data.token);
      setCurrentUser(data.user);
      localStorage.setItem("docuchat_token", data.token);
      localStorage.setItem("docuchat_user", JSON.stringify(data.user));
      setAuthModalOpen(false);
      setAuthPassword("");
      setAuthError("");
    } catch (err) {
      setAuthError(err.message || "Failed to authenticate");
    } finally {
      setAuthLoading(false);
    }
  };

  // Quick 1-click Demo Login
  const handleDemoLogin = async () => {
    setAuthUsername("admin");
    setAuthPassword("admin123");
    setAuthError("");
    setAuthLoading(true);

    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: "admin", password: "admin123" }),
      });
      const data = await res.json();
      if (res.ok) {
        setAuthToken(data.token);
        setCurrentUser(data.user);
        localStorage.setItem("docuchat_token", data.token);
        localStorage.setItem("docuchat_user", JSON.stringify(data.user));
        setAuthModalOpen(false);
      } else {
        setAuthError(data.detail || "Demo login failed");
      }
    } catch (err) {
      setAuthError(err.message || "Demo login network error");
    } finally {
      setAuthLoading(false);
    }
  };

  // Logout
  const handleLogout = async () => {
    if (authToken) {
      try {
        await fetch(`${API_BASE}/auth/logout`, {
          method: "POST",
          headers: getAuthHeaders(),
        });
      } catch (e) {
        console.error("Logout error:", e);
      }
    }
    setAuthToken("");
    setCurrentUser(null);
    localStorage.removeItem("docuchat_token");
    localStorage.removeItem("docuchat_user");
  };

  // Conversations API
  const fetchConversations = async () => {
    try {
      const res = await fetch(`${API_BASE}/conversations`, {
        headers: getAuthHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        setConversations(data);
        if (data.length > 0 && !activeConvId) {
          selectConversation(data[0].id);
        }
      }
    } catch (e) {
      console.error("Error fetching conversations:", e);
    }
  };

  const selectConversation = async (convId) => {
    setActiveConvId(convId);
    try {
      const res = await fetch(`${API_BASE}/conversations/${convId}`, {
        headers: getAuthHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        setMessages(data.messages || []);
      }
    } catch (e) {
      console.error("Error loading conversation:", e);
    }
  };

  const handleNewChat = async () => {
    if (abortController) {
      abortController.abort();
      setIsGenerating(false);
      setAbortController(null);
    }
    setNavTab("chat");
    try {
      const res = await fetch(`${API_BASE}/conversations`, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({ title: "New Chat" }),
      });
      if (res.ok) {
        const newConv = await res.json();
        setConversations((prev) => [newConv, ...prev]);
        setActiveConvId(newConv.id);
        setMessages([]);
      } else {
        setActiveConvId(null);
        setMessages([]);
      }
    } catch (e) {
      console.error("Error creating new chat:", e);
      setActiveConvId(null);
      setMessages([]);
    }
  };

  const handleClearChat = () => {
    setMessages([]);
  };

  const deleteConversation = async (convId, e) => {
    if (e) e.stopPropagation();
    if (!window.confirm("Delete this conversation?")) return;
    try {
      await fetch(`${API_BASE}/conversations/${convId}`, {
        method: "DELETE",
        headers: getAuthHeaders(),
      });
      setConversations((prev) => prev.filter((c) => c.id !== convId));
      if (activeConvId === convId) {
        const remaining = conversations.filter((c) => c.id !== convId);
        if (remaining.length > 0) {
          selectConversation(remaining[0].id);
        } else {
          setActiveConvId(null);
          setMessages([]);
        }
      }
    } catch (e) {
      console.error("Error deleting conversation:", e);
    }
  };

  // Documents API
  const fetchDocuments = async () => {
    try {
      const res = await fetch(`${API_BASE}/documents`, {
        headers: getAuthHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        setDocuments(data);
        if (data.length === 0) {
          setSelectedDocScope("none");
        } else if (selectedDocScope === "none") {
          setSelectedDocScope("all");
        }
      }
    } catch (e) {
      console.error("Error fetching documents:", e);
    }
  };

  const deleteDocument = async (docId, e) => {
    if (e) e.stopPropagation();
    if (!window.confirm("Delete this document and all its indexed chunks?")) return;
    try {
      await fetch(`${API_BASE}/documents/${docId}`, {
        method: "DELETE",
        headers: getAuthHeaders(),
      });
      setDocuments((prev) => prev.filter((d) => d.id !== docId));
      if (viewerDoc?.id === docId) {
        setViewerOpen(false);
        setViewerDoc(null);
      }
    } catch (e) {
      console.error("Error deleting document:", e);
    }
  };

  const handleFileUpload = async (file) => {
    if (!file) return;
    setUploading(true);
    setUploadStatus(`Uploading ${file.name}...`);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch(`${API_BASE}/documents`, {
        method: "POST",
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
        body: formData,
      });
      if (res.ok) {
        const docData = await res.json();
        setDocuments((prev) => [docData, ...prev]);
        setSelectedDocScope(docData.id);
        setViewerDoc(docData);
        setViewerOpen(true);
        setCurrentPage(1);
        setActiveHighlights([]);
        setUploadStatus("Processing with Docling & indexing in Qdrant...");
        setTimeout(fetchDocuments, 2000);
      } else {
        const err = await res.json();
        alert(`Upload error: ${err.detail || "Upload failed"}`);
      }
    } catch (e) {
      alert(`Network error during upload: ${e.message}`);
    } finally {
      setTimeout(() => {
        setUploading(false);
        setUploadStatus("");
      }, 3000);
    }
  };

  // Streaming Chat Send Handler
  const handleSendMessage = async (textToSend) => {
    const query = textToSend || inputMessage;
    if (!query.trim() || isGenerating) return;

    if (!currentUser) {
      setAuthModalOpen(true);
      return;
    }

    const userMsg = {
      id: "temp_user_" + Date.now(),
      role: "user",
      content: query,
      created_at: new Date().toISOString(),
    };

    const tempAsstId = "temp_asst_" + Date.now();
    const assistantMsg = {
      id: tempAsstId,
      role: "assistant",
      content: "",
      router_badge: "Analyzing...",
      citations: [],
      queries: [],
    };

    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setInputMessage("");
    setIsGenerating(true);

    const controller = new AbortController();
    setAbortController(controller);

    try {
      const docScopeIds =
        selectedDocScope === "all"
          ? null
          : selectedDocScope === "none"
            ? []
            : [selectedDocScope];

      const res = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: getAuthHeaders(),
        signal: controller.signal,
        body: JSON.stringify({
          conversation_id: activeConvId,
          message: query,
          document_ids: docScopeIds,
          top_k: topK,
          score_threshold: scoreThreshold,
          fusion_method: fusionMethod,
          alpha: fusionAlpha,
          router_mode: routerMode,
        }),
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() || "";

        for (const evt of events) {
          if (!evt.trim()) continue;
          const lines = evt.split("\n");
          let eventType = "";
          let dataStr = "";

          for (const line of lines) {
            if (line.startsWith("event:")) {
              eventType = line.replace("event:", "").trim();
            } else if (line.startsWith("data:")) {
              dataStr = line.replace("data:", "").trim();
            }
          }

          if (dataStr) {
            try {
              const parsed = JSON.parse(dataStr);
              if (eventType === "meta") {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === tempAsstId
                      ? { ...m, router_badge: parsed.badge, queries: parsed.queries }
                      : m
                  )
                );
              } else if (eventType === "token") {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === tempAsstId ? { ...m, content: m.content + parsed.content } : m
                  )
                );
              } else if (eventType === "citations") {
                const citationsList = parsed.citations || [];
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === tempAsstId ? { ...m, citations: citationsList } : m
                  )
                );

                if (citationsList.length > 0) {
                  const topCitation =
                    citationsList.find((c) => c.bboxes && c.bboxes.length > 0) ||
                    citationsList[0];
                  openCitationInViewer(topCitation.source_index || 1, topCitation);
                }
              }
            } catch (err) {
              console.error("Error parsing SSE data chunk:", err);
            }
          }
        }
      }
    } catch (e) {
      if (e.name !== "AbortError") {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === tempAsstId
              ? { ...m, content: m.content + `\n\n*[Request error: ${e.message}]*` }
              : m
          )
        );
      }
    } finally {
      setIsGenerating(false);
      setAbortController(null);
      fetchConversations();
    }
  };

  const handleStopGenerating = () => {
    if (abortController) {
      abortController.abort();
      setIsGenerating(false);
      setAbortController(null);
    }
  };

  // Ask a Question Mode (Single Turn)
  const handleAskQuestionSubmit = async () => {
    if (!askQuery.trim() || isAsking) return;

    if (!currentUser) {
      setAuthModalOpen(true);
      return;
    }

    setIsAsking(true);
    setAskAnswer("");
    setAskCitations([]);

    try {
      const docScopeIds =
        selectedDocScope === "all"
          ? null
          : selectedDocScope === "none"
            ? []
            : [selectedDocScope];

      const res = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({
          conversation_id: null,
          message: askQuery,
          document_ids: docScopeIds,
          top_k: topK,
          score_threshold: scoreThreshold,
          fusion_method: fusionMethod,
          alpha: fusionAlpha,
          router_mode: routerMode,
        }),
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() || "";

        for (const evt of events) {
          if (!evt.trim()) continue;
          const lines = evt.split("\n");
          let eventType = "";
          let dataStr = "";

          for (const line of lines) {
            if (line.startsWith("event:")) {
              eventType = line.replace("event:", "").trim();
            } else if (line.startsWith("data:")) {
              dataStr = line.replace("data:", "").trim();
            }
          }

          if (dataStr) {
            try {
              const parsed = JSON.parse(dataStr);
              if (eventType === "token") {
                setAskAnswer((prev) => prev + parsed.content);
              } else if (eventType === "citations") {
                setAskCitations(parsed.citations || []);
              }
            } catch (err) {
              console.error("Error parsing ask SSE chunk:", err);
            }
          }
        }
      }
    } catch (e) {
      setAskAnswer((prev) => prev + `\n\n*[Request error: ${e.message}]*`);
    } finally {
      setIsAsking(false);
    }
  };

  // PDF Viewer & Bounding Box Logic
  const openCitationInViewer = async (sourceIndex, citation, answerContext = "") => {
    if (!citation) return;
    setFocusedCitationIndex(sourceIndex);
    setViewerOpen(true);

    let doc = documents.find((d) => d.id === citation.doc_id);
    if (!doc && citation.doc_id) {
      try {
        const res = await fetch(`${API_BASE}/documents/${citation.doc_id}`, {
          headers: getAuthHeaders(),
        });
        if (res.ok) {
          doc = await res.json();
        }
      } catch (e) {
        console.error("Error fetching cited doc:", e);
      }
    }
    if (doc) {
      setViewerDoc(doc);
    }

    setCurrentPage(citation.page || 1);

    const allBoxes = citation.bboxes || [];
    let focusedBoxes = allBoxes.slice(0, 1);

    if (allBoxes.length > 1 && answerContext) {
      const stopWords = new Set([
        "what", "is", "the", "in", "my", "of", "and", "a", "an", "to", "for", "with",
        "on", "at", "by", "from", "this", "that", "are", "was", "were", "tell", "give",
      ]);
      const words = answerContext.toLowerCase().match(/[a-z0-9%]+/g) || [];
      const keywords = words.filter((w) => w.length > 1 && !stopWords.has(w));

      if (keywords.length > 0) {
        const matchingBoxes = allBoxes.filter((box) => {
          const bText = (box.text || "").toLowerCase();
          return keywords.some((kw) => bText.includes(kw));
        });
        if (matchingBoxes.length > 0) {
          focusedBoxes = matchingBoxes.slice(0, 1);
        }
      }
    }

    setActiveHighlights(focusedBoxes);
  };

  // Render PDF Page onto HTML5 Canvas
  const renderPdfPage = useCallback(
    async (pdf, pageNumber) => {
      if (!pdf || !canvasRef.current) return;
      try {
        const page = await pdf.getPage(pageNumber);
        const canvas = canvasRef.current;
        const ctx = canvas.getContext("2d");

        const viewport = page.getViewport({ scale: zoomScale });
        canvas.width = viewport.width;
        canvas.height = viewport.height;

        const renderContext = {
          canvasContext: ctx,
          viewport: viewport,
        };
        await page.render(renderContext).promise;
      } catch (e) {
        console.error("PDF page render error:", e);
      }
    },
    [zoomScale]
  );

  // Load PDF document into viewer
  useEffect(() => {
    if (!viewerDoc || !viewerOpen) return;
    let isCancelled = false;

    const loadPdfDoc = async () => {
      if (!window.pdfjsLib) {
        console.warn("PDF.js library not yet loaded in window.");
        return;
      }

      try {
        const pdfUrl = `${API_BASE}/documents/${viewerDoc.id}/file`;
        const loadingTask = window.pdfjsLib.getDocument(pdfUrl);
        const pdf = await loadingTask.promise;
        if (!isCancelled) {
          setViewerPdf(pdf);
          setTotalPages(pdf.numPages);
          renderPdfPage(pdf, currentPage);
        }
      } catch (e) {
        console.error("Failed to load PDF:", e);
      }
    };

    loadPdfDoc();
    return () => {
      isCancelled = true;
    };
  }, [viewerDoc, viewerOpen, renderPdfPage, currentPage]);

  // Re-render on page or zoom change
  useEffect(() => {
    if (viewerPdf) {
      renderPdfPage(viewerPdf, currentPage);
    }
  }, [viewerPdf, currentPage, zoomScale, renderPdfPage]);

  return (
    <div className="azure-app" data-theme={theme}>
      {/* ================= 1. TOP NAVIGATION BAR ================= */}
      <header className="azure-nav-bar">
        <div className="nav-left">
          {/* ChatGPT Style 3-Lines Hamburger Menu Button */}
          <div style={{ position: "relative" }} ref={menuRef}>
            <button
              className={`hamburger-menu-btn ${menuOpen ? "active" : ""}`}
              onClick={() => setMenuOpen(!menuOpen)}
              title="Settings & Menu"
              aria-label="Settings and Menu"
            >
              <svg
                width="20"
                height="20"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <line x1="3" y1="6" x2="21" y2="6" />
                <line x1="3" y1="12" x2="21" y2="12" />
                <line x1="3" y1="18" x2="21" y2="18" />
              </svg>
            </button>

            {menuOpen && (
              <div className="chatgpt-menu-popover">
                <div className="menu-section-label">Chat</div>
                <button
                  className="menu-item-row"
                  onClick={() => {
                    handleNewChat();
                    setMenuOpen(false);
                  }}
                >
                  <div className="menu-item-left">
                    <svg
                      width="15"
                      height="15"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2.2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <line x1="12" y1="5" x2="12" y2="19" />
                      <line x1="5" y1="12" x2="19" y2="12" />
                    </svg>
                    <span style={{ fontWeight: 600 }}>New chat</span>
                  </div>
                  <span className="menu-badge-new">+ New</span>
                </button>

                <div className="menu-divider" />
                <div className="menu-section-label">Theme Mode</div>
                <div className="menu-item-row" style={{ cursor: "default" }}>
                  <div className="menu-item-left">
                    <span>{theme === "dark" ? "🌙 Dark" : "☀️ Light"}</span>
                  </div>
                  <div className="menu-theme-switcher">
                    <button
                      className={`menu-theme-pill ${theme === "dark" ? "active" : ""}`}
                      onClick={() => {
                        setTheme("dark");
                        localStorage.setItem("docuchat_theme", "dark");
                      }}
                    >
                      Dark
                    </button>
                    <button
                      className={`menu-theme-pill ${theme === "light" ? "active" : ""}`}
                      onClick={() => {
                        setTheme("light");
                        localStorage.setItem("docuchat_theme", "light");
                      }}
                    >
                      Light
                    </button>
                  </div>
                </div>

                <div className="menu-divider" />
                <div className="menu-section-label">Settings & Tools</div>

                <button
                  className="menu-item-row"
                  onClick={() => {
                    setDevSettingsOpen(true);
                    setSettingsTab("rag");
                    setMenuOpen(false);
                  }}
                >
                  <div className="menu-item-left">
                    <span>⚙️ Model & RAG Settings</span>
                  </div>
                  <span style={{ fontSize: "12px", color: "var(--text-secondary)" }}>❯</span>
                </button>

                <button
                  className="menu-item-row"
                  onClick={() => {
                    setDevSettingsOpen(true);
                    setSettingsTab("docs");
                    setMenuOpen(false);
                  }}
                >
                  <div className="menu-item-left">
                    <span>📄 Documents & Uploads ({documents.length})</span>
                  </div>
                  <span style={{ fontSize: "12px", color: "var(--text-secondary)" }}>❯</span>
                </button>

                <button
                  className="menu-item-row"
                  onClick={() => {
                    setDevSettingsOpen(true);
                    setSettingsTab("history");
                    setMenuOpen(false);
                  }}
                >
                  <div className="menu-item-left">
                    <span>💬 Chat History ({conversations.length})</span>
                  </div>
                  <span style={{ fontSize: "12px", color: "var(--text-secondary)" }}>❯</span>
                </button>

                <button
                  className="menu-item-row"
                  onClick={() => {
                    handleClearChat();
                    setMenuOpen(false);
                  }}
                >
                  <div className="menu-item-left">
                    <span>🗑️ Clear Active Chat</span>
                  </div>
                </button>

                <div className="menu-divider" />
                <div className="menu-section-label">Account</div>

                {currentUser ? (
                  <div className="menu-item-row" style={{ cursor: "default" }}>
                    <div className="menu-item-left">
                      <div
                        className="auth-user-avatar"
                        style={{ width: 20, height: 20, fontSize: 10 }}
                      >
                        {currentUser.username[0].toUpperCase()}
                      </div>
                      <span style={{ fontWeight: 600 }}>{currentUser.username}</span>
                    </div>
                    <button
                      className="auth-btn-ghost"
                      style={{ padding: "2px 8px", fontSize: "11px" }}
                      onClick={() => {
                        handleLogout();
                        setMenuOpen(false);
                      }}
                    >
                      Sign Out
                    </button>
                  </div>
                ) : (
                  <button
                    className="menu-item-row"
                    onClick={() => {
                      setAuthModalOpen(true);
                      setMenuOpen(false);
                    }}
                  >
                    <div className="menu-item-left">
                      <span>👤 Sign In / Register</span>
                    </div>
                    <span
                      style={{
                        fontSize: "12px",
                        color: "var(--accent-purple)",
                        fontWeight: 600,
                      }}
                    >
                      Sign In
                    </span>
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Top Nav New Chat Button */}
          <button
            className="nav-new-chat-btn"
            onClick={handleNewChat}
            title="Start a new chat"
            aria-label="New chat"
          >
            <svg
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            <span className="nav-new-chat-text">New chat</span>
          </button>

          <div className="brand-title" onClick={() => setNavTab("chat")}>
            <div className="brand-dot" />
            <span>DocuChat-AI</span>
          </div>
        </div>

        <nav className="nav-center-tabs">
          <button
            className={`nav-tab-btn ${navTab === "chat" ? "active" : ""}`}
            onClick={() => setNavTab("chat")}
          >
            Chat
          </button>
          <button
            className={`nav-tab-btn ${navTab === "ask" ? "active" : ""}`}
            onClick={() => setNavTab("ask")}
          >
            Ask a question
          </button>
          <a
            href="https://github.com/Azure-Samples/azure-search-openai-demo"
            target="_blank"
            rel="noreferrer"
            className="nav-github-link"
            title="GitHub Repository"
          >
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="currentColor"
            >
              <path
                fillRule="evenodd"
                clipRule="evenodd"
                d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
              />
            </svg>
          </a>
        </nav>

        <div className="nav-right">
          <span className="azure-service-tag">Azure OpenAI + AI Search</span>

          {/* Quick theme toggle */}
          <button
            className="theme-toggle-btn"
            onClick={toggleTheme}
            title={`Switch to ${theme === "dark" ? "Light" : "Dark"} Mode`}
          >
            {theme === "dark" ? "☀️" : "🌙"}
          </button>

          {/* User auth status */}
          {currentUser ? (
            <div className="auth-user-pill">
              <div className="auth-user-avatar">
                {currentUser.username[0].toUpperCase()}
              </div>
              <span>{currentUser.username}</span>
              <button
                className="auth-btn-ghost"
                onClick={handleLogout}
                title="Sign out"
              >
                Sign out
              </button>
            </div>
          ) : (
            <button
              className="auth-btn-primary"
              onClick={() => {
                setAuthError("");
                setAuthModalOpen(true);
              }}
            >
              Sign In
            </button>
          )}
        </div>
      </header>

      {/* ================= 2. SUB-HEADER TOOLBAR ================= */}
      <div className="azure-sub-toolbar">
        <button
          className="toolbar-action-btn toolbar-new-chat-btn"
          onClick={handleNewChat}
          title="Start a new chat"
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.4"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          <span>New chat</span>
        </button>

        <button
          className="toolbar-action-btn"
          onClick={handleClearChat}
          title="Clear current view"
        >
          <svg
            width="15"
            height="15"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
          </svg>
          <span>Clear chat</span>
        </button>

        <button
          className="toolbar-action-btn"
          onClick={() => setDevSettingsOpen(true)}
          title="Developer settings"
        >
          <svg
            width="15"
            height="15"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
          <span>Developer settings</span>
        </button>
      </div>

      {/* ================= 3. MAIN WORKSPACE ================= */}
      <div className="azure-workspace">
        <main className="azure-main-panel">
          {navTab === "chat" ? (
            /* Mode 1: Multi-Turn Grounded Chat */
            messages.length === 0 ? (
              /* Center Hero Empty State (Exact match to reference image) */
              <div className="hero-scroll-area">
                <div className="hero-container">
                  <div className="sparkle-icon-wrap">
                    <svg
                      width="66"
                      height="66"
                      viewBox="0 0 66 66"
                      fill="none"
                      xmlns="http://www.w3.org/2000/svg"
                    >
                      {/* Large star rotated */}
                      <path
                        d="M28 6 C28 18 20 26 8 26 C20 26 28 34 28 46 C28 34 36 26 48 26 C36 26 28 18 28 6 Z"
                        fill="url(#sparkleGradient)"
                        transform="rotate(16 28 26)"
                      />
                      {/* Small star tilted */}
                      <path
                        d="M50 36 C50 42 45 46 39 46 C45 46 50 50 50 56 C50 50 55 46 61 46 C55 46 50 42 50 36 Z"
                        fill="url(#sparkleGradient)"
                        transform="rotate(-12 50 46)"
                      />
                      <defs>
                        <linearGradient
                          id="sparkleGradient"
                          x1="0"
                          y1="0"
                          x2="66"
                          y2="66"
                          gradientUnits="userSpaceOnUse"
                        >
                          <stop offset="0%" stopColor="#8b5cf6" />
                          <stop offset="100%" stopColor="#a78bfa" />
                        </linearGradient>
                      </defs>
                    </svg>
                  </div>

                  <h1 className="hero-title">Chat with your data</h1>
                  <p className="hero-subtitle">Ask anything or try an example</p>

                  <div className="starter-cards-row">
                    <div
                      className="starter-card"
                      onClick={() =>
                        handleSendMessage(
                          "What is included in my Northwind Health Plus plan that is not in standard?"
                        )
                      }
                    >
                      <span>
                        What is included in my Northwind Health Plus plan that is not in standard?
                      </span>
                    </div>

                    <div
                      className="starter-card"
                      onClick={() =>
                        handleSendMessage("What happens in a performance review?")
                      }
                    >
                      <span>What happens in a performance review?</span>
                    </div>

                    <div
                      className="starter-card"
                      onClick={() =>
                        handleSendMessage("What does a Product Manager do?")
                      }
                    >
                      <span>What does a Product Manager do?</span>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              /* Chat Messages Stream */
              <div className="messages-scroll-area">
                {messages.map((msg, idx) => (
                  <div
                    key={msg.id || idx}
                    className={`chat-message-row ${msg.role === "user" ? "user" : "assistant"}`}
                  >
                    {msg.role === "user" ? (
                      <div className="user-bubble">{msg.content}</div>
                    ) : (
                      <div className="assistant-bubble">
                        <div className="msg-header-row">
                          <span
                            className={`router-badge ${msg.router_badge?.includes("document") ? "document" : "general"
                              }`}
                          >
                            {msg.router_badge?.includes("document")
                              ? "📄 From document"
                              : "✨ General answer"}
                          </span>
                        </div>

                        {renderMarkdownWithCitations(
                          msg.content,
                          msg.citations,
                          (num, c) => openCitationInViewer(num, c, msg.content)
                        )}

                        {msg.content && (
                          <div className="msg-actions-row">
                            <button
                              className="msg-action-btn"
                              onClick={() => navigator.clipboard.writeText(msg.content)}
                              title="Copy response"
                            >
                              📋 Copy
                            </button>
                            <button
                              className="msg-action-btn"
                              onClick={() =>
                                handleSendMessage(messages[idx - 1]?.content)
                              }
                              title="Regenerate"
                            >
                              🔄 Regenerate
                            </button>
                            <button className="msg-action-btn" title="Helpful">
                              👍
                            </button>
                            <button className="msg-action-btn" title="Not helpful">
                              👎
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))}
                <div ref={messagesEndRef} />
              </div>
            )
          ) : (
            /* Mode 2: "Ask a question" Single-Turn View */
            <div className="ask-question-view">
              <div className="ask-box-wrap">
                <h2 style={{ fontSize: "24px", fontWeight: 700, marginBottom: "8px" }}>
                  Ask a direct question
                </h2>
                <p style={{ color: "var(--text-secondary)", fontSize: "14px", marginBottom: "16px" }}>
                  Submit a query to directly retrieve answers with grounding citations and source passages.
                </p>

                <div
                  className="input-floating-card"
                  style={{ boxShadow: "0 2px 10px rgba(0,0,0,0.06)" }}
                >
                  <textarea
                    className="input-main-textarea"
                    placeholder="Type your question here..."
                    rows={3}
                    value={askQuery}
                    onChange={(e) => setAskQuery(e.target.value)}
                  />
                  <div className="input-bottom-row">
                    <span style={{ fontSize: "12px", color: "var(--text-secondary)" }}>
                      Scope: {selectedDocScope === "all" ? "All Documents" : "Active Document"}
                    </span>
                    <button
                      className="auth-btn-primary"
                      disabled={isAsking || !askQuery.trim()}
                      onClick={handleAskQuestionSubmit}
                      style={{ padding: "8px 18px", borderRadius: "6px" }}
                    >
                      {isAsking ? "Generating answer..." : "Ask question ➔"}
                    </button>
                  </div>
                </div>

                {askAnswer && (
                  <div className="ask-card-answer">
                    <h3 style={{ fontSize: "16px", fontWeight: 700, marginBottom: "12px" }}>
                      Generated Answer
                    </h3>
                    {renderMarkdownWithCitations(askAnswer, askCitations, (num, c) =>
                      openCitationInViewer(num, c, askAnswer)
                    )}

                    {askCitations.length > 0 && (
                      <div style={{ marginTop: "24px" }}>
                        <h4 style={{ fontSize: "13px", fontWeight: 700, color: "var(--text-secondary)" }}>
                          Supporting Source Citations
                        </h4>
                        <div className="citations-cards-grid">
                          {askCitations.map((c, i) => (
                            <div
                              key={i}
                              className="citation-source-card"
                              onClick={() => openCitationInViewer(c.source_index || i + 1, c)}
                            >
                              <div style={{ fontWeight: 650, fontSize: "13px", marginBottom: "4px" }}>
                                [{c.source_index || i + 1}] Page {c.page}
                              </div>
                              <p style={{ fontSize: "12px", color: "var(--text-secondary)", lineHeight: 1.4 }}>
                                {c.snippet?.slice(0, 140)}...
                              </p>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ================= FLOATING CHAT INPUT BAR (Chat Mode) ================= */}
          {navTab === "chat" && (
            <div className="chat-input-section">
              <div className="input-floating-card">
                {uploading && (
                  <div style={{ fontSize: "12px", color: "var(--accent-purple)", marginBottom: "4px" }}>
                    ⏳ {uploadStatus}
                  </div>
                )}

                <div className="input-chips-bar">
                  {selectedDocScope === "none" ? (
                    <div className="scope-pill chatgpt-mode">
                      🌐 Real-time Web Mode
                    </div>
                  ) : selectedDocScope !== "all" ? (
                    <div className="scope-pill active-doc">
                      📄 {documents.find((d) => d.id === selectedDocScope)?.filename}
                      <span
                        style={{ cursor: "pointer", marginLeft: "4px", fontWeight: 700 }}
                        onClick={() => setSelectedDocScope("all")}
                      >
                        ✕
                      </span>
                    </div>
                  ) : (
                    documents.length > 0 && (
                      <div className="scope-pill">
                        📚 All Indexed Documents ({documents.length})
                      </div>
                    )
                  )}
                </div>

                <textarea
                  className="input-main-textarea"
                  placeholder="Type a new question (e.g. does my plan cover annual eye exams?)"
                  value={inputMessage}
                  rows={2}
                  onChange={(e) => setInputMessage(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      handleSendMessage();
                    }
                  }}
                />

                <div className="input-bottom-row">
                  <div className="input-tools-left">
                    <input
                      type="file"
                      ref={fileInputRef}
                      style={{ display: "none" }}
                      accept=".pdf,.docx,.pptx,.xlsx,.txt,.html,.md,.png,.jpg,.jpeg"
                      onChange={(e) => {
                        if (e.target.files?.[0]) handleFileUpload(e.target.files[0]);
                      }}
                    />
                    <button
                      className="tool-icon-btn"
                      onClick={() => fileInputRef.current?.click()}
                      title="Attach Document (PDF, DOCX, XLSX, TXT)"
                    >
                      <svg
                        width="18"
                        height="18"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
                      </svg>
                    </button>

                    <select
                      className="scope-select-dropdown"
                      value={selectedDocScope}
                      onChange={(e) => setSelectedDocScope(e.target.value)}
                    >
                      {documents.length > 0 && (
                        <option value="all">All Documents ({documents.length})</option>
                      )}
                      {documents.map((d) => (
                        <option key={d.id} value={d.id}>
                          📄 {d.filename}
                        </option>
                      ))}
                      <option value="none">🌐 ChatGPT Mode</option>
                    </select>
                  </div>

                  {isGenerating ? (
                    <button className="stop-gen-btn" onClick={handleStopGenerating}>
                      ⏹ Stop
                    </button>
                  ) : (
                    <button
                      className="send-action-btn"
                      disabled={!inputMessage.trim()}
                      onClick={() => handleSendMessage()}
                      title="Send query"
                    >
                      {/* Purple send arrow matching screenshot */}
                      <svg
                        width="20"
                        height="20"
                        viewBox="0 0 24 24"
                        fill="var(--accent-purple)"
                        xmlns="http://www.w3.org/2000/svg"
                      >
                        <path d="M3.4 20.4l17.45-7.48c.81-.35.81-1.49 0-1.84L3.4 3.6c-.66-.29-1.39.2-1.39.91L2 9.12c0 .5.37.93.87.99L17 12 2.87 13.89c-.5.06-.87.49-.87 1l.01 4.6c0 .72.73 1.2 1.39.91z" />
                      </svg>
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}
        </main>

        {/* ================= 4. RIGHT PDF VIEWER ================= */}
        <section className={`pdf-viewer-panel ${viewerOpen ? "" : "collapsed"}`}>
          <div className="viewer-header-bar">
            <span
              style={{
                fontSize: "13px",
                fontWeight: 600,
                maxWidth: "200px",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                color: "var(--text-main)",
              }}
            >
              {viewerDoc ? viewerDoc.filename : "No Document Selected"}
            </span>

            <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
              <button
                className="tool-icon-btn"
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={currentPage <= 1}
              >
                ◀
              </button>
              <span style={{ fontSize: "12px", color: "var(--text-secondary)" }}>
                {currentPage} / {totalPages}
              </span>
              <button
                className="tool-icon-btn"
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                disabled={currentPage >= totalPages}
              >
                ▶
              </button>
              <button
                className="tool-icon-btn"
                onClick={() => setZoomScale((z) => Math.max(0.6, z - 0.15))}
              >
                -
              </button>
              <button
                className="tool-icon-btn"
                onClick={() => setZoomScale(1.0)}
              >
                100%
              </button>
              <button
                className="tool-icon-btn"
                onClick={() => setZoomScale((z) => Math.min(2.0, z + 0.15))}
              >
                +
              </button>
              <button
                className="tool-icon-btn"
                onClick={() => setViewerOpen(false)}
                title="Close PDF view"
              >
                ✕
              </button>
            </div>
          </div>

          <div
            style={{
              flex: 1,
              overflow: "auto",
              padding: "16px",
              display: "flex",
              justifyContent: "center",
            }}
          >
            {viewerDoc ? (
              <div className="viewer-page-container">
                <canvas ref={canvasRef} />
                <div
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    height: "100%",
                    pointerEvents: "none",
                  }}
                >
                  {activeHighlights
                    .filter((b) => b.page === currentPage)
                    .map((box, bIdx) => {
                      const canvas = canvasRef.current;
                      const cWidth = canvas ? canvas.width : 600;
                      const cHeight = canvas ? canvas.height : 800;
                      const pWidth = box.page_width || 612;
                      const pHeight = box.page_height || 792;

                      const scaleX = cWidth / pWidth;
                      const scaleY = cHeight / pHeight;

                      const top =
                        box.coord_origin === "BOTTOMLEFT"
                          ? (pHeight - box.y1) * scaleY
                          : box.y0 * scaleY;
                      const height = Math.abs(box.y1 - box.y0) * scaleY;
                      const left = box.x0 * scaleX;
                      const width = Math.abs(box.x1 - box.x0) * scaleX;

                      return (
                        <div
                          key={bIdx}
                          className="highlight-rect focused"
                          style={{
                            top: `${top}px`,
                            left: `${left}px`,
                            width: `${Math.max(15, width)}px`,
                            height: `${Math.max(12, height)}px`,
                          }}
                          title={`Citation [${focusedCitationIndex || ""}]`}
                        />
                      );
                    })}
                </div>
              </div>
            ) : (
              <div
                style={{
                  margin: "auto",
                  textAlign: "center",
                  color: "var(--text-secondary)",
                  fontSize: "13px",
                }}
              >
                Select a document or click a citation [n] in chat to view page & highlights.
              </div>
            )}
          </div>
        </section>
      </div>

      {/* ================= 5. DEVELOPER SETTINGS DRAWER ================= */}
      <aside className={`dev-settings-drawer ${devSettingsOpen ? "open" : ""}`}>
        <div className="drawer-header">
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <button
              className="drawer-back-btn"
              onClick={() => setDevSettingsOpen(false)}
              title="Back"
              aria-label="Back"
            >
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.4"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <line x1="19" y1="12" x2="5" y2="12" />
                <polyline points="12 19 5 12 12 5" />
              </svg>
              <span>Back</span>
            </button>
            <h3 className="drawer-title">
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <circle cx="12" cy="12" r="3" />
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
              </svg>
              Settings
            </h3>
          </div>
          <button
            className="drawer-close-btn"
            onClick={() => setDevSettingsOpen(false)}
            title="Close"
          >
            ✕
          </button>
        </div>

        <div className="auth-modal-tabs">
          <button
            className={`auth-tab-btn ${settingsTab === "rag" ? "active" : ""}`}
            onClick={() => setSettingsTab("rag")}
          >
            RAG Tuning
          </button>
          <button
            className={`auth-tab-btn ${settingsTab === "docs" ? "active" : ""}`}
            onClick={() => setSettingsTab("docs")}
          >
            Documents ({documents.length})
          </button>
          <button
            className={`auth-tab-btn ${settingsTab === "history" ? "active" : ""}`}
            onClick={() => setSettingsTab("history")}
          >
            Chats ({conversations.length})
          </button>
        </div>

        <div className="drawer-body">
          {settingsTab === "rag" && (
            <>
              <div className="drawer-section">
                <div className="drawer-section-title">Retrieval Parameters</div>

                <div className="setting-control-row">
                  <div className="setting-label-wrap">
                    <span>Retrieve Top-K Chunks</span>
                    <strong>{topK}</strong>
                  </div>
                  <input
                    type="range"
                    min="1"
                    max="10"
                    className="setting-range-input"
                    value={topK}
                    onChange={(e) => setTopK(parseInt(e.target.value, 10))}
                  />
                </div>

                <div className="setting-control-row">
                  <div className="setting-label-wrap">
                    <span>Score Threshold</span>
                    <strong>{scoreThreshold}</strong>
                  </div>
                  <input
                    type="range"
                    min="0.0"
                    max="0.8"
                    step="0.05"
                    className="setting-range-input"
                    value={scoreThreshold}
                    onChange={(e) => setScoreThreshold(parseFloat(e.target.value))}
                  />
                </div>

                <div className="setting-control-row">
                  <span className="setting-label-wrap">Hybrid Fusion Method</span>
                  <select
                    className="setting-select-input"
                    value={fusionMethod}
                    onChange={(e) => setFusionMethod(e.target.value)}
                  >
                    <option value="rrf">Reciprocal Rank Fusion (RRF, k=60)</option>
                    <option value="weighted">Weighted Score Fusion (Vector + BM25)</option>
                  </select>
                </div>

                {fusionMethod === "weighted" && (
                  <div className="setting-control-row">
                    <div className="setting-label-wrap">
                      <span>Vector Alpha Weight</span>
                      <strong>{fusionAlpha}</strong>
                    </div>
                    <input
                      type="range"
                      min="0.0"
                      max="1.0"
                      step="0.05"
                      className="setting-range-input"
                      value={fusionAlpha}
                      onChange={(e) => setFusionAlpha(parseFloat(e.target.value))}
                    />
                  </div>
                )}
              </div>

              <div className="drawer-section">
                <div className="drawer-section-title">LLM & Generation</div>

                <div className="setting-control-row">
                  <span className="setting-label-wrap">Query Router Mode</span>
                  <select
                    className="setting-select-input"
                    value={routerMode}
                    onChange={(e) => setRouterMode(e.target.value)}
                  >
                    <option value="hybrid">Hybrid (Rules + JSON LLM Fallback)</option>
                    <option value="rule">Rule-Based Only (Fastest)</option>
                    <option value="llm">LLM Classification Only</option>
                  </select>
                </div>

                <div className="setting-control-row">
                  <div className="setting-label-wrap">
                    <span>Temperature</span>
                    <strong>{temperature}</strong>
                  </div>
                  <input
                    type="range"
                    min="0.0"
                    max="1.0"
                    step="0.05"
                    className="setting-range-input"
                    value={temperature}
                    onChange={(e) => setTemperature(parseFloat(e.target.value))}
                  />
                </div>
              </div>

              <div className="drawer-section">
                <div className="drawer-section-title">PDF Provenance Viewer</div>
                <button
                  className="auth-btn-ghost"
                  style={{ color: "var(--text-main)", borderColor: "var(--card-border)" }}
                  onClick={() => setViewerOpen(!viewerOpen)}
                >
                  {viewerOpen ? "📖 Hide PDF Canvas" : "📖 Open PDF Canvas"}
                </button>
              </div>
            </>
          )}

          {settingsTab === "docs" && (
            <div className="drawer-section">
              <div
                className="doc-upload-dropzone"
                onClick={() => fileInputRef.current?.click()}
              >
                <div style={{ fontSize: "24px", marginBottom: "6px" }}>📄</div>
                <div style={{ fontWeight: 600, fontSize: "13px", color: "var(--text-main)" }}>
                  Click to upload documents
                </div>
                <div style={{ fontSize: "11px", color: "var(--text-secondary)" }}>
                  PDF, DOCX, XLSX, TXT, MD, Images
                </div>
              </div>

              <div className="drawer-section-title" style={{ marginTop: "12px" }}>
                Indexed Files ({documents.length})
              </div>

              {documents.length === 0 ? (
                <div style={{ fontSize: "13px", color: "var(--text-secondary)", textAlign: "center" }}>
                  No documents indexed yet.
                </div>
              ) : (
                documents.map((doc) => (
                  <div key={doc.id} className="doc-list-item">
                    <div
                      style={{ cursor: "pointer" }}
                      onClick={() => {
                        setViewerDoc(doc);
                        setViewerOpen(true);
                        setCurrentPage(1);
                      }}
                    >
                      <div className="doc-info-text" style={{ fontWeight: 600, color: "var(--text-main)" }}>
                        📄 {doc.filename}
                      </div>
                      <div style={{ fontSize: "11px", color: "var(--text-secondary)" }}>
                        {doc.page_count} pages • {doc.chunk_count} chunks •{" "}
                        <span style={{ color: doc.status === "ready" ? "#10b981" : "#f59e0b" }}>
                          {doc.status}
                        </span>
                      </div>
                    </div>

                    <button
                      className="tool-icon-btn"
                      onClick={(e) => deleteDocument(doc.id, e)}
                      title="Delete document"
                    >
                      ✕
                    </button>
                  </div>
                ))
              )}
            </div>
          )}

          {settingsTab === "history" && (
            <div className="drawer-section">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                <div className="drawer-section-title" style={{ margin: 0 }}>Saved Conversations</div>
                <button
                  className="drawer-new-chat-btn"
                  onClick={() => {
                    handleNewChat();
                    setDevSettingsOpen(false);
                  }}
                  title="Start a new chat"
                >
                  <svg
                    width="12"
                    height="12"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    style={{ marginRight: "4px" }}
                  >
                    <line x1="12" y1="5" x2="12" y2="19" />
                    <line x1="5" y1="12" x2="19" y2="12" />
                  </svg>
                  <span>New chat</span>
                </button>
              </div>
              {conversations.length === 0 ? (
                <div style={{ fontSize: "13px", color: "var(--text-secondary)" }}>No chats saved yet.</div>
              ) : (
                conversations.map((conv) => (
                  <div
                    key={conv.id}
                    className="doc-list-item"
                    style={{
                      cursor: "pointer",
                      backgroundColor: conv.id === activeConvId ? "rgba(139, 92, 246, 0.2)" : "var(--card-bg)",
                    }}
                    onClick={() => selectConversation(conv.id)}
                  >
                    <span style={{ fontSize: "13px", fontWeight: 500, maxWidth: "260px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--text-main)" }}>
                      💬 {conv.title || "Untitled Chat"}
                    </span>
                    <button
                      className="tool-icon-btn"
                      onClick={(e) => deleteConversation(conv.id, e)}
                      title="Delete chat"
                    >
                      ✕
                    </button>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      </aside>

      {/* Backdrop overlay for Left Settings Drawer */}
      {devSettingsOpen && (
        <div
          className="drawer-backdrop"
          onClick={() => setDevSettingsOpen(false)}
          title="Click to go back"
        />
      )}

      {/* ================= 6. AUTHENTICATION MODAL ================= */}
      {authModalOpen && (
        <div className="auth-modal-overlay" onClick={() => setAuthModalOpen(false)}>
          <div className="auth-modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="auth-modal-header">
              <h2 className="auth-modal-title">DocuChat-AI</h2>
              <p className="auth-modal-subtitle">
                Sign in or register to access grounded enterprise search and documents.
              </p>
              <button
                className="auth-modal-close"
                onClick={() => setAuthModalOpen(false)}
              >
                ✕
              </button>
            </div>

            <div className="auth-modal-tabs">
              <button
                className={`auth-tab-btn ${authTab === "login" ? "active" : ""}`}
                onClick={() => {
                  setAuthTab("login");
                  setAuthError("");
                }}
              >
                Sign In
              </button>
              <button
                className={`auth-tab-btn ${authTab === "register" ? "active" : ""}`}
                onClick={() => {
                  setAuthTab("register");
                  setAuthError("");
                }}
              >
                Create Account
              </button>
            </div>

            <form className="auth-form-body" onSubmit={handleAuthSubmit}>
              {authError && <div className="auth-error-banner">{authError}</div>}

              <div className="form-field-group">
                <label className="form-field-label">Username</label>
                <div className="form-input-wrap">
                  <input
                    type="text"
                    className="form-input"
                    placeholder="Enter your username (e.g. admin)"
                    value={authUsername}
                    onChange={(e) => setAuthUsername(e.target.value)}
                    required
                    autoFocus
                  />
                </div>
              </div>

              {authTab === "register" && (
                <div className="form-field-group">
                  <label className="form-field-label">Email (Optional)</label>
                  <div className="form-input-wrap">
                    <input
                      type="email"
                      className="form-input"
                      placeholder="user@enterprise.ai"
                      value={authEmail}
                      onChange={(e) => setAuthEmail(e.target.value)}
                    />
                  </div>
                </div>
              )}

              <div className="form-field-group">
                <label className="form-field-label">Password</label>
                <div className="form-input-wrap">
                  <input
                    type={showPassword ? "text" : "password"}
                    className="form-input"
                    placeholder="Enter your password"
                    value={authPassword}
                    onChange={(e) => setAuthPassword(e.target.value)}
                    required
                  />
                  <button
                    type="button"
                    className="password-toggle-btn"
                    onClick={() => setShowPassword(!showPassword)}
                    title={showPassword ? "Hide password" : "Show password"}
                  >
                    {showPassword ? "👁️" : "👁️‍🗨️"}
                  </button>
                </div>
              </div>

              <button
                type="submit"
                className="auth-submit-btn"
                disabled={authLoading}
              >
                {authLoading
                  ? "Verifying credentials..."
                  : authTab === "login"
                    ? "Sign In"
                    : "Create Account"}
              </button>

              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "10px",
                  margin: "4px 0",
                }}
              >
                <div style={{ flex: 1, height: "1px", background: "var(--card-border)" }} />
                <span style={{ fontSize: "11px", color: "var(--text-secondary)" }}>OR QUICK ACCESS</span>
                <div style={{ flex: 1, height: "1px", background: "var(--card-border)" }} />
              </div>

              <button
                type="button"
                className="auth-demo-shortcut"
                onClick={handleDemoLogin}
              >
                ⚡ 1-Click Demo Login (admin / admin123)
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
