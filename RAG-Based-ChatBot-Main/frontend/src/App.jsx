import React, { useState, useEffect, useRef } from "react";
import "./App.css";

// Modular Services
import { api } from "./services/api";
import { chatWs, subscribeDocumentProgress } from "./services/websocket";

// Modular Components
import Navbar from "./components/Header/Navbar";
import Sidebar from "./components/Sidebar/Sidebar";
import ChatArea from "./components/Chat/ChatArea";
import ChatInput from "./components/Chat/ChatInput";
import SideDocumentViewer from "./components/DocumentViewer/SideDocumentViewer";
import ToolsPopover from "./components/Tools/ToolsPopover";
import ToolExecutionModal from "./components/Tools/ToolExecutionModal";
import SettingsModal from "./components/Settings/SettingsModal";
import AuthModal from "./components/Auth/AuthModal";
import HistoryModal from "./components/Chat/HistoryModal";
import ProjectsModal from "./components/Projects/ProjectsModal";
import AdminPasswordModal from "./components/Auth/AdminPasswordModal";
import HelpModal from "./components/Help/HelpModal";
import PdfToolsModal from "./components/Tools/PdfToolsModal";

export default function App() {
  // Theme State
  const [theme, setTheme] = useState(() => localStorage.getItem("docuchat_theme") || "light");
  const toggleTheme = () => {
    const nextTheme = theme === "dark" ? "light" : "dark";
    setTheme(nextTheme);
    localStorage.setItem("docuchat_theme", nextTheme);
  };

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    document.body.setAttribute("data-theme", theme);
  }, [theme]);

  // View Modes: "split" | "chat" | "document"
  const [viewMode, setViewMode] = useState("chat");
  const [chatSplitPercent, setChatSplitPercent] = useState(50);
  const [isResizingSplit, setIsResizingSplit] = useState(false);
  const isResizingRef = useRef(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  // Drag resizer handler for flexible split-view panels
  const handleResizerMouseDown = (e) => {
    e.preventDefault();
    isResizingRef.current = true;
    setIsResizingSplit(true);
    document.body.classList.add("resizing-active");

    const onMouseMove = (moveEvent) => {
      if (!isResizingRef.current) return;
      const container = document.querySelector(".chatgpt-split-workspace-body");
      if (!container) return;
      const rect = container.getBoundingClientRect();
      const relativeX = moveEvent.clientX - rect.left;
      const newPercent = Math.max(25, Math.min(75, (relativeX / rect.width) * 100));
      setChatSplitPercent(newPercent);
    };

    const onMouseUp = () => {
      isResizingRef.current = false;
      setIsResizingSplit(false);
      document.body.classList.remove("resizing-active");
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };

    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
  };

  // Tools Popover & Execution Modals
  const [toolsOpen, setToolsOpen] = useState(false);
  const [activeToolModal, setActiveToolModal] = useState({ isOpen: false, toolId: null });

  // Drawers & Modals
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState("appearance");
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [projectsOpen, setProjectsOpen] = useState(false);
  const [adminPwdModalOpen, setAdminPwdModalOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);

  // Projects State
  const [projects, setProjects] = useState([
    {
      id: "proj-1",
      title: "Enterprise RAG & AI Intelligence",
      description: "Default workspace for deep document search, tables, and grounded QA",
      doc_count: 2,
      created_at: "Today"
    },
    {
      id: "proj-2",
      title: "Financial & Quarterly Audits",
      description: "Spreadsheets, earnings reports, and quantitative analytics",
      doc_count: 1,
      created_at: "Yesterday"
    },
    {
      id: "proj-3",
      title: "Technical Research & Papers",
      description: "Transformer architectures, attention mechanisms, and model evaluations",
      doc_count: 1,
      created_at: "3 days ago"
    }
  ]);
  const [activeProjectId, setActiveProjectId] = useState("proj-1");

  const handleOpenSettings = () => {
    setSettingsTab("appearance");
    setSettingsOpen(true);
  };

  const handleOpenDeveloperSettings = () => {
    setSettingsTab("rag_admin");
    setSettingsOpen(true);
  };

  // Real-Web Mode State
  const [webMode, setWebMode] = useState(false);

  // PDF Tools Workstation State
  const [pdfToolsOpen, setPdfToolsOpen] = useState(false);
  const [pdfToolsInitialOp, setPdfToolsInitialOp] = useState("merge");

  // User State
  const [currentUser, setCurrentUser] = useState(() => {
    try {
      const saved = localStorage.getItem("docuchat_user");
      return saved ? JSON.parse(saved) : null;
    } catch {
      return null;
    }
  });

  // Documents State
  const [documents, setDocuments] = useState([]);
  const [activeDoc, setActiveDoc] = useState(null);
  const fileInputRef = useRef(null);

  // Split-View Document State
  const [currentPage, setCurrentPage] = useState(1);
  const [activeHighlights, setActiveHighlights] = useState([]);
  const [focusedCitation, setFocusedCitation] = useState(null);

  // Conversations & Messages
  const [conversations, setConversations] = useState([]);
  const [activeConvId, setActiveConvId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);

  // RAG Engine Settings
  const [topK, setTopK] = useState(5);
  const [scoreThreshold, setScoreThreshold] = useState(0.25);
  const [fusionMethod, setFusionMethod] = useState("rrf");
  const [fusionAlpha, setFusionAlpha] = useState(0.5);
  const [routerMode, setRouterMode] = useState("hybrid");
  const [temperature, setTemperature] = useState(0.0);
  const [llmModel, setLlmModel] = useState("Qwen 2.5 3B");
  const [embeddingModel, setEmbeddingModel] = useState("nomic-embed-text:v1.5");

  // Load initial data
  useEffect(() => {
    loadUserWorkspace();
    checkHealth();
  }, []);

  // Keyboard shortcut (Cmd+K / Ctrl+K)
  useEffect(() => {
    const handleGlobalKeyDown = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        const searchInput = document.querySelector(".sidebar-search-field");
        if (searchInput) searchInput.focus();
      }
    };
    window.addEventListener("keydown", handleGlobalKeyDown);
    return () => window.removeEventListener("keydown", handleGlobalKeyDown);
  }, []);

  // Connect WebSocket chat stream
  useEffect(() => {
    const token = localStorage.getItem("docuchat_token");
    chatWs.connect(token);

    const unregGlobalRename = chatWs.on("conversation_renamed", (data) => {
      if (data?.conversation_id && data?.title) {
        setConversations((prev) =>
          prev.map((c) =>
            c.id === data.conversation_id ? { ...c, title: data.title } : c
          )
        );
      }
    });

    return () => {
      unregGlobalRename();
      chatWs.disconnect();
    };
  }, [currentUser]);

  const checkHealth = async () => {
    try {
      const data = await api.getHealth();
      if (data.llm_model) {
        setLlmModel(data.llm_model.includes("7b") ? "Qwen 2.5 7B" : "Qwen 2.5 3B");
      }
      if (data.embedding_model) {
        setEmbeddingModel(data.embedding_model);
      }
    } catch {}
  };

  const loadUserWorkspace = async () => {
    try {
      // 1. Fetch conversations for current user
      const convs = await api.listConversations();
      if (convs && convs.length > 0) {
        setConversations(convs);
        const mostRecent = convs[0];
        setActiveConvId(mostRecent.id);
        try {
          const detail = await api.getConversation(mostRecent.id);
          const msgs = detail?.messages || [];
          setMessages(msgs);
          const lastAsst = [...msgs].reverse().find(m => m.role === "assistant" && m.citations && m.citations.length > 0);
          if (lastAsst) {
            const allBoxes = lastAsst.citations.flatMap(c => (c.bboxes || []).map(b => ({
              ...b,
              page: Number(b.page || c.page || 1),
              source_index: b.source_index || c.source_index
            })));
            setActiveHighlights(allBoxes);
            const topCite = lastAsst.citations[0];
            setFocusedCitation(topCite);
            if (topCite?.page) setCurrentPage(Number(topCite.page));
          } else {
            setActiveHighlights([]);
            setFocusedCitation(null);
          }
        } catch {
          setMessages([]);
          setActiveHighlights([]);
          setFocusedCitation(null);
        }
      } else {
        setConversations([]);
        setActiveConvId(null);
        setMessages([]);
        setActiveHighlights([]);
        setFocusedCitation(null);
      }
    } catch (e) {
      console.warn("Could not load conversations:", e);
      setConversations([]);
      setActiveConvId(null);
      setMessages([]);
      setActiveHighlights([]);
      setFocusedCitation(null);
    }

    try {
      // 2. Fetch documents for current user
      const docs = await api.listDocuments();
      if (docs && docs.length > 0) {
        setDocuments(docs);
        setActiveDoc(docs[0]);
        setViewMode("split");
      } else {
        setDocuments([]);
        setActiveDoc(null);
        setViewMode("chat");
      }
    } catch (e) {
      console.warn("Could not load documents:", e);
      setDocuments([]);
      setActiveDoc(null);
      setViewMode("chat");
    }
  };

  const loadDocuments = async () => {
    try {
      const docs = await api.listDocuments();
      if (docs && docs.length > 0) {
        setDocuments(docs);
        setActiveDoc((prev) => (prev ? docs.find((d) => d.id === prev.id) || docs[0] : docs[0]));
      } else {
        setDocuments([]);
        setActiveDoc(null);
        setViewMode("chat");
      }
    } catch (e) {
      console.warn("Could not load documents:", e);
      setDocuments([]);
      setActiveDoc(null);
    }
  };

  const loadConversations = async () => {
    try {
      const convs = await api.listConversations();
      if (convs && convs.length > 0) {
        setConversations(convs);
      } else {
        setConversations([]);
      }
    } catch (e) {
      console.warn("Could not load conversations:", e);
      setConversations([]);
    }
  };

  const selectConversation = async (convId) => {
    setActiveConvId(convId);
    try {
      const conv = await api.getConversation(convId);
      if (conv && conv.messages) {
        const msgs = conv.messages;
        setMessages(msgs);
        const lastAsst = [...msgs].reverse().find(m => m.role === "assistant" && m.citations && m.citations.length > 0);
        if (lastAsst) {
          const allBoxes = lastAsst.citations.flatMap(c => (c.bboxes || []).map(b => ({
            ...b,
            page: Number(b.page || c.page || 1),
            source_index: b.source_index || c.source_index
          })));
          setActiveHighlights(allBoxes);
          const topCite = lastAsst.citations[0];
          setFocusedCitation(topCite);
          if (topCite?.page) setCurrentPage(Number(topCite.page));
        } else {
          setActiveHighlights([]);
          setFocusedCitation(null);
        }
      } else {
        setMessages([]);
        setActiveHighlights([]);
        setFocusedCitation(null);
      }
    } catch (e) {
      console.warn("Could not fetch messages for conv:", convId);
      setMessages([]);
      setActiveHighlights([]);
      setFocusedCitation(null);
    }
  };

  const handleNewConversation = async () => {
    setMessages([]);
    setActiveHighlights([]);
    setFocusedCitation(null);
    try {
      const newConv = await api.createConversation("New Chat");
      setConversations((prev) => [newConv, ...prev]);
      setActiveConvId(newConv.id);
    } catch {
      const fallbackConv = { id: `conv_${Date.now()}`, title: "New Chat", updated_at: "Just now" };
      setConversations((prev) => [fallbackConv, ...prev]);
      setActiveConvId(fallbackConv.id);
    }
  };

  const handleDeleteConversation = async (convId) => {
    try {
      await api.deleteConversation(convId);
    } catch {}
    setConversations((prev) => prev.filter((c) => c.id !== convId));
    if (activeConvId === convId) {
      setActiveConvId(null);
      setMessages([]);
    }
  };

  const handleRenameConversation = async (convId, newTitle) => {
    if (!newTitle || !newTitle.trim()) return;
    try {
      await api.updateConversation(convId, newTitle.trim());
      setConversations((prev) =>
        prev.map((c) => (c.id === convId ? { ...c, title: newTitle.trim() } : c))
      );
    } catch (e) {
      console.warn("Could not rename conversation:", e);
    }
  };

  // Clear Chat (All Clear option inside user panel)
  const handleClearChat = () => {
    setMessages([]);
    setActiveHighlights([]);
    setFocusedCitation(null);
  };

  // Clear all conversations (from Settings / History modal)
  const handleClearAllConversations = async () => {
    for (const conv of conversations) {
      try {
        await api.deleteConversation(conv.id);
      } catch {}
    }
    setConversations([]);
    setActiveConvId(null);
    setMessages([]);
    setActiveHighlights([]);
  };

  // Document management (Delete and Rename from Sidebar Document Collection options menu)
  const handleDeleteDocument = async (docId) => {
    try {
      await api.deleteDocument(docId);
      setDocuments((prev) => prev.filter((d) => d.id !== docId));
      if (activeDoc?.id === docId) {
        const remaining = documents.filter((d) => d.id !== docId);
        setActiveDoc(remaining.length > 0 ? remaining[0] : null);
        if (remaining.length === 0) {
          setViewMode("chat");
          setActiveHighlights([]);
          setFocusedCitation(null);
        }
      }
    } catch (e) {
      console.error("Could not delete document from backend:", e);
      alert("Failed to delete document: " + (e.message || "Error"));
    }
  };

  const handleRenameDocument = (docId, newName) => {
    setDocuments((prev) =>
      prev.map((d) => (d.id === docId ? { ...d, filename: newName } : d))
    );
    if (activeDoc?.id === docId) {
      setActiveDoc((prev) => (prev ? { ...prev, filename: newName } : null));
    }
  };

  // Auth & Session Handlers
  const handleLogout = async () => {
    try {
      await api.logout();
    } catch {}
    localStorage.removeItem("docuchat_user");
    localStorage.removeItem("docuchat_token");
    setCurrentUser(null);
    setDocuments([]);
    setActiveDoc(null);
    setConversations([]);
    setActiveConvId(null);
    setMessages([]);
    setActiveHighlights([]);
    setFocusedCitation(null);
    setViewMode("chat");
    setInputMessage("");
    setAuthModalOpen(true);
  };

  const handleLogin = async (username, password) => {
    const res = await api.login(username, password);
    if (res.token) localStorage.setItem("docuchat_token", res.token);
    const u = res.user ? { username: res.user.username, role: res.user.role, id: res.user.id } : { username, role: "user" };
    setCurrentUser(u);
    localStorage.setItem("docuchat_user", JSON.stringify(u));
    setAuthModalOpen(false);
    await loadUserWorkspace();
  };

  const handleRegister = async (username, password, email) => {
    const res = await api.register(username, password, email);
    if (res.token) localStorage.setItem("docuchat_token", res.token);
    const u = res.user ? { username: res.user.username, role: res.user.role, id: res.user.id } : { username, role: "user" };
    setCurrentUser(u);
    localStorage.setItem("docuchat_user", JSON.stringify(u));
    setAuthModalOpen(false);
    await loadUserWorkspace();
  };

  const handleDemoLogin = async (role = "admin") => {
    const targetUser = role === "admin" ? "admin" : "demo";
    const targetPass = role === "admin" ? "admin123" : "demo123";
    try {
      const res = await api.login(targetUser, targetPass);
      if (res.token) localStorage.setItem("docuchat_token", res.token);
      const u = res.user ? { username: res.user.username, role: res.user.role, id: res.user.id } : { username: targetUser, role };
      setCurrentUser(u);
      localStorage.setItem("docuchat_user", JSON.stringify(u));
    } catch {
      const u = {
        username: targetUser,
        role: role === "admin" ? "admin" : "user"
      };
      setCurrentUser(u);
      localStorage.setItem("docuchat_user", JSON.stringify(u));
    }
    setAuthModalOpen(false);
    await loadUserWorkspace();
  };

  const handleRequestAdminMode = () => {
    setAdminPwdModalOpen(true);
  };

  const handleAdminAuthSuccess = () => {
    setCurrentUser((prev) => {
      const updated = {
        username: prev?.username || "amd12321",
        role: "Enterprise Administrator (admin)"
      };
      localStorage.setItem("docuchat_user", JSON.stringify(updated));
      return updated;
    });
    handleOpenDeveloperSettings();
  };

  const handleSwitchToUserMode = () => {
    setCurrentUser((prev) => {
      const updated = {
        username: prev?.username || "amd12321",
        role: "Standard User (Free Plan)"
      };
      localStorage.setItem("docuchat_user", JSON.stringify(updated));
      return updated;
    });
  };

  const handleToggleRole = () => {
    const isCurrentlyAdmin = (currentUser?.role || "").toLowerCase().includes("admin");
    if (isCurrentlyAdmin) {
      handleSwitchToUserMode();
    } else {
      handleRequestAdminMode();
    }
  };

  // Document Upload
  const handleFileUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    try {
      const uploadedDoc = await api.uploadDocument(file);
      setDocuments((prev) => [uploadedDoc, ...prev.filter((d) => d.id !== uploadedDoc.id)]);
      setActiveDoc(uploadedDoc);
      setCurrentPage(1);
      setActiveHighlights([]);
      setFocusedCitation(null);
      setViewMode("split");

      subscribeDocumentProgress(
        uploadedDoc.id,
        (progressEvent) => {
          setDocuments((prev) =>
            prev.map((d) =>
              d.id === uploadedDoc.id
                ? { ...d, status: progressEvent.status, status_message: progressEvent.message }
                : d
            )
          );
          setActiveDoc((prev) =>
            prev && prev.id === uploadedDoc.id
              ? { ...prev, status: progressEvent.status, status_message: progressEvent.message }
              : prev
          );
        },
        () => {
          loadDocuments();
        }
      );
    } catch (err) {
      alert(`Upload error: ${err.message}`);
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  // Citation click handler: jumps side viewer to page & highlights evidence
  const handleCitationClick = (sourceIndexOrCite, citation) => {
    let targetCite = citation;
    let sourceIndex = sourceIndexOrCite;

    // Handle polymorphic call: handleCitationClick(cite) or handleCitationClick(sourceIndex, cite)
    if (sourceIndexOrCite && typeof sourceIndexOrCite === "object") {
      targetCite = sourceIndexOrCite;
      sourceIndex = targetCite.source_index;
    }

    // If citation was not passed directly (e.g. from inline pill without cite obj), look up by sourceIndex
    if (!targetCite) {
      const lastAsst = [...messages].reverse().find(m => m.role === "assistant" && m.citations && m.citations.length > 0);
      const candidates = lastAsst ? lastAsst.citations : [];
      targetCite = candidates.find(c => Number(c.source_index) === Number(sourceIndex)) || candidates[0];
    }
    if (!targetCite) return;

    // Handle web citations (open verified URL in new tab)
    if (targetCite.type === "web" || targetCite.url) {
      if (targetCite.url) {
        window.open(targetCite.url, "_blank", "noopener,noreferrer");
      }
      return;
    }

    // 1. Resolve & activate the document so SideDocumentViewer is guaranteed to show
    const targetDocId = targetCite.doc_id || targetCite.document_id;
    const targetDocName = targetCite.filename || targetCite.doc_name;
    let docToActivate = activeDoc;

    if (
      !docToActivate ||
      (targetDocId && docToActivate.id !== targetDocId) ||
      (targetDocName && docToActivate.filename !== targetDocName)
    ) {
      const match = documents.find(
        (d) => (targetDocId && d.id === targetDocId) || (targetDocName && d.filename === targetDocName)
      );
      if (match) {
        docToActivate = match;
        setActiveDoc(match);
      } else if (targetDocId) {
        const stub = { id: targetDocId, filename: targetDocName || "Document", file_type: "pdf" };
        docToActivate = stub;
        setActiveDoc(stub);
      } else if (documents.length > 0) {
        docToActivate = documents[0];
        setActiveDoc(documents[0]);
      }
    } else if (!docToActivate && documents.length > 0) {
      docToActivate = documents[0];
      setActiveDoc(documents[0]);
    }

    // 2. Jump to the exact target page of this citation
    const targetPage = Math.max(1, Number(targetCite.page || targetCite.page_number || 1));
    setCurrentPage(targetPage);

    // 3. Keep all generated answer highlights active across all pages (no need to click evidence to see highlights)
    const lastAsst = [...messages].reverse().find(m => m.role === "assistant" && m.citations && m.citations.length > 0);
    if (lastAsst?.citations && lastAsst.citations.length > 0) {
      const allBoxes = lastAsst.citations.flatMap(c => (c.bboxes || []).map(b => ({
        ...b,
        page: Number(b.page || c.page || 1),
        source_index: b.source_index || c.source_index
      })));
      if (allBoxes.length > 0) {
        setActiveHighlights(allBoxes);
      }
    } else if (targetCite.bboxes && targetCite.bboxes.length > 0) {
      setActiveHighlights(targetCite.bboxes);
    }
    setFocusedCitation(targetCite);

    // 4. Switch to split view so the document panel is visible
    setViewMode("split");
  };

  // Preview generated PDF artifact in side PDF viewer
  const handlePreviewGeneratedPdf = (artifact) => {
    if (!artifact) return;
    const docStub = {
      id: artifact.id || artifact.artifact_id || artifact.filename,
      filename: artifact.filename,
      file_type: "pdf",
      pdf_path: artifact.file_path,
      download_url: artifact.download_url
    };
    setActiveDoc(docStub);
    setCurrentPage(1);
    setActiveHighlights([]);
    setFocusedCitation(null);
    setViewMode("split");
  };

  // Central Tool Selection Dispatcher
  const handleSelectTool = (toolId, defaultPrompt) => {
    if (toolId === "pdf_tools") {
      setPdfToolsOpen(true);
      setToolsOpen(false);
      return;
    }
    if (toolId === "web_search") {
      setWebMode(true);
      if (defaultPrompt) setInputMessage(defaultPrompt);
      setToolsOpen(false);
      return;
    }
    if (toolId === "create_document" || toolId === "doc_generator") {
      setInputMessage(defaultPrompt || "Generate a professional PDF executive summary report.");
      setToolsOpen(false);
      return;
    }
    if (toolId === "excel_generator") {
      setInputMessage(defaultPrompt || "Generate an Excel workbook with data analysis.");
      setToolsOpen(false);
      return;
    }
    if (defaultPrompt) {
      setInputMessage(defaultPrompt);
      setToolsOpen(false);
      return;
    }
    setActiveToolModal({ isOpen: true, toolId });
    setToolsOpen(false);
  };

  // Chat sending via WebSocket (supports Real-Web Mode and direct tool execution)
  const handleSendMessage = (explicitText = null) => {
    const text = (typeof explicitText === "string" ? explicitText : inputMessage).trim();
    if (!text || isGenerating) return;

    // Immediately clear previous highlights to prevent stale coordinates during consecutive queries
    setActiveHighlights([]);
    setFocusedCitation(null);

    const tempUserMsg = {
      id: `user_${Date.now()}`,
      role: "user",
      content: text,
      created_at: new Date().toISOString()
    };
    const isWeatherQuery = /\b(weather|temperature|forecast|rainfall|umbrella|humidity|wind\s+speed|precipitat|how\s+(?:hot|cold|warm)|is\s+it\s+(?:raining|sunny|cloudy|snowing)|rain\s+in|snow\s+in)\b/i.test(text);
    const isExcelGenQuery = /\b(create|generate|export|build|prepare|make|produce)\b.*\b(excel|sheet|spreadsheet|workbook|\.?xlsx?|\d+\s*(?:data\s*)?rows?|\d+\s*columns?|test\s*cases?)/i.test(text);
    const isDocGenQuery = /\b(create|generate|export|build|prepare|make|produce|write|draft)\b.*\b(docx|word|pdf|text\s+file|text\s+document|\.?txt|markdown|\.?md|project\s+report|technical\s+report|business\s+report|meeting\s+minutes|action\s+items|project\s+proposal|resume|curriculum\s+vitae|\bcv\b|cover\s+letter|technical\s+doc|user\s+manual|srs|prd|test\s+plan|document)/i.test(text);
    const isPdfToolQuery = /\b(merge|split|rotate|compress|extract\s+pages|pdf\s+to\s+(?:text|markdown)|extract\s+(?:pdf\s+)?tables|watermark|page\s+numbers?)\b/i.test(text);
    const isGreeting = /^(hi|hello|hey|good\s+(morning|afternoon|evening)|howdy|sup|who\s+are\s+you|help|thanks|thank\s+you)[.?!]*$/i.test(text.trim());
    const tempAsstId = `asst_${Date.now()}`;
    const tempAsstMsg = {
      id: tempAsstId,
      role: "assistant",
      content: "",
      router_badge: isWeatherQuery ? "⛅ Live Weather" : (isExcelGenQuery ? "📊 Excel Generator" : (isDocGenQuery ? "📝 Document Generator" : (isPdfToolQuery ? "🛠️ PDF Tools" : ((webMode && !isGreeting) ? "🌐 Live Web Search" : null)))),
      citations: [],
      weather: null,
      created_at: new Date().toISOString()
    };

    setMessages((prev) => [...prev, tempUserMsg, tempAsstMsg]);
    if (!explicitText) {
      setInputMessage("");
    }
    setIsGenerating(true);

    const docScopeList = activeDoc
      ? [activeDoc.id]
      : (documents && documents.length > 0 ? documents.map((d) => d.id) : null);

    let accumulatedText = "";
    let hasSpecialContent = false;
    let isCleanedUp = false;

    // Safety timeout: 180 seconds max to prevent infinite loading dots on CPU inference
    const safetyTimer = setTimeout(() => {
      if (!isCleanedUp) {
        if (!accumulatedText && !hasSpecialContent) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === tempAsstId
                ? {
                    ...m,
                    content:
                      "⚠️ Request timed out waiting for server response. Please ensure the backend server and Ollama are running."
                  }
                : m
            )
          );
        }
        setIsGenerating(false);
        cleanup();
      }
    }, 180000);

    const unregToken = chatWs.on("token", (data) => {
      accumulatedText += data.content || "";
      setMessages((prev) =>
        prev.map((m) => (m.id === tempAsstId ? { ...m, content: accumulatedText } : m))
      );
    });

    const unregStart = chatWs.on("start", (data) => {
      if (data.conversation_id && !activeConvId) {
        setActiveConvId(data.conversation_id);
        loadConversations();
      }
      setMessages((prev) =>
        prev.map((m) => (m.id === tempAsstId ? { ...m, router_badge: data.router_badge } : m))
      );
    });

    const unregWeather = chatWs.on("weather", (data) => {
      hasSpecialContent = true;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === tempAsstId
            ? { ...m, weather: data, router_badge: "⛅ Live Weather" }
            : m
        )
      );
    });

    const unregExcel = chatWs.on("excel_artifact", (data) => {
      hasSpecialContent = true;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === tempAsstId
            ? { ...m, excel_artifact: data, router_badge: "📊 Excel Generator" }
            : m
        )
      );
    });

    const unregDoc = chatWs.on("document_artifact", (data) => {
      hasSpecialContent = true;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === tempAsstId
            ? { ...m, document_artifact: data, router_badge: "📝 Document Generator" }
            : m
        )
      );
    });

    const unregPdf = chatWs.on("pdf_artifact", (data) => {
      hasSpecialContent = true;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === tempAsstId
            ? { ...m, pdf_artifact: data, router_badge: "🛠️ PDF Tools" }
            : m
        )
      );
    });

    const unregRenamed = chatWs.on("conversation_renamed", (data) => {
      if (data?.conversation_id && data?.title) {
        setConversations((prev) =>
          prev.map((c) =>
            c.id === data.conversation_id ? { ...c, title: data.title } : c
          )
        );
      }
    });

    const unregCitations = chatWs.on("citations", (data) => {
      const citeList = data.citations || [];
      setMessages((prev) =>
        prev.map((m) => (m.id === tempAsstId ? { ...m, citations: citeList } : m))
      );

      if (citeList.length > 0) {
        const topCitation = citeList[0];
        const targetDocId = topCitation.doc_id || topCitation.document_id;
        const targetDocName = topCitation.filename || topCitation.doc_name;
        if (!activeDoc || (targetDocId && activeDoc.id !== targetDocId)) {
          const match = documents.find(
            (d) => (targetDocId && d.id === targetDocId) || (targetDocName && d.filename === targetDocName)
          );
          if (match) setActiveDoc(match);
          else if (targetDocId) setActiveDoc({ id: targetDocId, filename: targetDocName || "Document", file_type: "pdf" });
        }

        // Collect ALL bounding boxes across ALL citations so EVERY generated page is highlighted immediately
        const allGeneratedBoxes = citeList.flatMap((c) =>
          (c.bboxes || []).map((b) => ({
            ...b,
            page: Number(b.page || c.page || 1),
            source_index: b.source_index || c.source_index
          }))
        );
        setActiveHighlights(allGeneratedBoxes);

        setFocusedCitation(topCitation);
        if (topCitation.page) setCurrentPage(Number(topCitation.page));
        setViewMode("split");
      } else {
        // Clear highlights when no supporting document citations are returned (e.g. unsupported questions)
        setActiveHighlights([]);
        setFocusedCitation(null);
      }
    });

    const unregError = chatWs.on("error", (data) => {
      const errMsg = data?.message || "An unexpected error occurred during generation.";
      setMessages((prev) =>
        prev.map((m) =>
          m.id === tempAsstId
            ? {
                ...m,
                content: accumulatedText
                  ? `${accumulatedText}\n\n⚠️ ${errMsg}`
                  : `⚠️ ${errMsg}`
              }
            : m
        )
      );
      setIsGenerating(false);
      cleanup();
    });

    const unregClose = chatWs.on("close", () => {
      if (!accumulatedText) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === tempAsstId
              ? {
                  ...m,
                  content:
                    "⚠️ Connection to DocuChat backend disconnected. Please check that the backend server is running."
                }
              : m
          )
        );
      }
      setIsGenerating(false);
      cleanup();
    });

    const unregComplete = chatWs.on("complete", () => {
      setIsGenerating(false);
      cleanup();
    });

    const cleanup = () => {
      if (isCleanedUp) return;
      isCleanedUp = true;
      clearTimeout(safetyTimer);
      unregToken();
      unregStart();
      unregWeather();
      unregExcel();
      unregDoc();
      unregPdf();
      unregRenamed();
      unregCitations();
      unregComplete();
      unregError();
      unregClose();
    };

    chatWs.sendMessage({
      message: text,
      conversation_id: activeConvId,
      document_ids: docScopeList,
      top_k: topK,
      score_threshold: scoreThreshold,
      fusion_method: fusionMethod,
      alpha: fusionAlpha,
      web_mode: webMode
    });
  };

  const handleStopGenerating = () => {
    setIsGenerating(false);
  };

  // Insert tool result into chat
  const handleInsertToolResult = (text) => {
    setInputMessage(text);
  };

  return (
    <div className="chatgpt-app-container" data-theme={theme}>
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        style={{ display: "none" }}
        onChange={handleFileUpload}
        accept=".pdf,.docx,.pptx,.xlsx,.txt,.md,.csv,.html"
      />

      {/* Main Layout */}
      <div className="chatgpt-layout-wrapper">
        {/* Left Navigation Sidebar matching Image 2 */}
        <Sidebar
          isOpen={sidebarOpen}
          onToggleSidebar={() => setSidebarOpen((prev) => !prev)}
          theme={theme}
          onToggleTheme={toggleTheme}
          onSelectNavView={(v) => {
            if (v === "tools") setToolsOpen(true);
            if (v === "library") fileInputRef.current?.click();
            if (v === "projects") setProjectsOpen(true);
          }}
          conversations={conversations}
          activeConvId={activeConvId}
          onSelectConversation={selectConversation}
          onNewConversation={handleNewConversation}
          onDeleteConversation={handleDeleteConversation}
          onRenameConversation={handleRenameConversation}
          onOpenHistory={() => setHistoryOpen(true)}
          onOpenProjects={() => setProjectsOpen(true)}
          documents={documents}
          activeDoc={activeDoc}
          onSelectDocument={(doc) => {
            if (activeDoc?.id !== doc.id) {
              setActiveHighlights([]);
              setFocusedCitation(null);
            }
            setActiveDoc(doc);
            setCurrentPage(1);
            setViewMode("split");
          }}
          onTriggerUpload={() => fileInputRef.current?.click()}
          onDeleteDocument={handleDeleteDocument}
          onRenameDocument={handleRenameDocument}
          onOpenSettings={handleOpenSettings}
          onOpenDeveloperSettings={handleOpenDeveloperSettings}
          onOpenTools={() => setToolsOpen(true)}
          onClearChat={handleClearChat}
          onOpenHelp={() => setHelpOpen(true)}
          currentUser={currentUser}
          onOpenAuth={() => setAuthModalOpen(true)}
          onLogout={handleLogout}
          onToggleRole={handleToggleRole}
          onRequestAdminMode={handleRequestAdminMode}
        />

        {/* Central & Right Workspaces (Split View) */}
        <div className={`chatgpt-main-view ${viewMode === "split" && activeDoc ? "split-active" : "chat-only"}`}>
          {/* Top Navbar matching Image 2 */}
          <Navbar
            activeDoc={activeDoc}
            onDeselectDoc={() => {
              setActiveDoc(null);
              setViewMode("chat");
              setActiveHighlights([]);
              setFocusedCitation(null);
            }}
            viewMode={viewMode}
            onToggleSplitView={() => {
              if (viewMode === "split") {
                setViewMode("chat");
              } else if (activeDoc) {
                setViewMode("split");
              } else if (documents.length > 0) {
                setActiveDoc(documents[0]);
                setViewMode("split");
              }
            }}
            currentUser={currentUser}
            onRequestAdminMode={handleRequestAdminMode}
            onSwitchToUserMode={handleSwitchToUserMode}
            onOpenPdfTools={() => setPdfToolsOpen(true)}
          />

          {/* Split Panes Container */}
          <div className={`chatgpt-split-workspace-body ${isResizingSplit ? "resizing" : ""}`}>
            {/* Left Pane: Chat Workspace (visible in Chat Only & Split View modes) */}
            {viewMode !== "document" && (
              <div
                className="chatgpt-chat-column"
                style={{
                  width: (viewMode === "split" && activeDoc) ? `${chatSplitPercent}%` : "100%",
                  flex: (viewMode === "split" && activeDoc) ? "none" : 1
                }}
              >
                <ChatArea
                  messages={messages}
                  isGenerating={isGenerating}
                  onCitationClick={handleCitationClick}
                  onQuickPromptClick={(prompt) => setInputMessage(prompt)}
                  onPreviewInViewer={handlePreviewGeneratedPdf}
                  activeDoc={activeDoc}
                />

                {/* Chat Composer Bar with Popover */}
                <div className="chatgpt-composer-anchor">
                  <ToolsPopover
                    isOpen={toolsOpen}
                    onClose={() => setToolsOpen(false)}
                    onSelectTool={handleSelectTool}
                  />

                  <ChatInput
                    inputMessage={inputMessage}
                    setInputMessage={setInputMessage}
                    onSendMessage={handleSendMessage}
                    isGenerating={isGenerating}
                    onStopGenerating={handleStopGenerating}
                    onOpenFileUpload={() => fileInputRef.current?.click()}
                    onToggleTools={() => setToolsOpen((prev) => !prev)}
                    toolsOpen={toolsOpen}
                    disabled={isGenerating}
                    webMode={webMode}
                    setWebMode={setWebMode}
                  />
                </div>
              </div>
            )}

            {/* Draggable Divider Handle between Chat and Document panels */}
            {viewMode === "split" && activeDoc && (
              <div
                className="chatgpt-split-resizer"
                onMouseDown={handleResizerMouseDown}
                title="Drag to resize chat and document panels"
              >
                <div className="resizer-handle-pill" />
              </div>
            )}

            {/* Right Pane: Document Viewer (visible in Split View & Document Only / Maximized modes) */}
            {viewMode !== "chat" && activeDoc && (
              <SideDocumentViewer
                document={activeDoc}
                currentPage={currentPage}
                setCurrentPage={setCurrentPage}
                activeHighlights={activeHighlights}
                focusedCitation={focusedCitation}
                viewMode={viewMode}
                onToggleSplitView={() => setViewMode((m) => (m === "split" ? "chat" : "split"))}
                onToggleMaximize={() => setViewMode((m) => (m === "document" ? "split" : "document"))}
                onCloseViewer={() => setViewMode("chat")}
              />
            )}
          </div>
        </div>
      </div>

      {/* Tool Execution Modal */}
      <ToolExecutionModal
        isOpen={activeToolModal.isOpen}
        toolId={activeToolModal.toolId}
        onClose={() => setActiveToolModal({ isOpen: false, toolId: null })}
        activeDoc={activeDoc}
        onInsertIntoChat={handleInsertToolResult}
        onExecutePrompt={(promptText) => {
          handleSendMessage(promptText);
        }}
      />

      {/* Full ChatGPT-style Settings Modal matching Image 2 */}
      <SettingsModal
        isOpen={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        initialTab={settingsTab}
        theme={theme}
        setTheme={setTheme}
        topK={topK}
        setTopK={setTopK}
        scoreThreshold={scoreThreshold}
        setScoreThreshold={setScoreThreshold}
        fusionMethod={fusionMethod}
        setFusionMethod={setFusionMethod}
        fusionAlpha={fusionAlpha}
        setFusionAlpha={setFusionAlpha}
        routerMode={routerMode}
        setRouterMode={setRouterMode}
        temperature={temperature}
        setTemperature={setTemperature}
        llmModel={llmModel}
        setLlmModel={setLlmModel}
        embeddingModel={embeddingModel}
        currentUser={currentUser}
        setCurrentUser={setCurrentUser}
        onClearAllConversations={handleClearAllConversations}
        onLogout={handleLogout}
        onToggleRole={handleToggleRole}
        webMode={webMode}
        setWebMode={setWebMode}
      />

      {/* All Past Conversation History Modal */}
      <HistoryModal
        isOpen={historyOpen}
        onClose={() => setHistoryOpen(false)}
        conversations={conversations}
        activeConvId={activeConvId}
        onSelectConversation={selectConversation}
        onDeleteConversation={handleDeleteConversation}
        onRenameConversation={handleRenameConversation}
        onNewConversation={handleNewConversation}
        onClearAllConversations={handleClearAllConversations}
      />

      {/* Workspace Projects Modal */}
      <ProjectsModal
        isOpen={projectsOpen}
        onClose={() => setProjectsOpen(false)}
        projects={projects}
        setProjects={setProjects}
        activeProjectId={activeProjectId}
        setActiveProjectId={setActiveProjectId}
        documents={documents}
      />

      {/* Auth Modal with polished styling and instant demo options */}
      <AuthModal
        isOpen={authModalOpen}
        onClose={() => setAuthModalOpen(false)}
        onLogin={handleLogin}
        onRegister={handleRegister}
        onDemoLogin={handleDemoLogin}
      />

      {/* Admin Password Authentication Modal */}
      <AdminPasswordModal
        isOpen={adminPwdModalOpen}
        onClose={() => setAdminPwdModalOpen(false)}
        onSuccess={handleAdminAuthSuccess}
      />

      {/* Help & Guide Modal */}
      <HelpModal
        isOpen={helpOpen}
        onClose={() => setHelpOpen(false)}
      />

      {/* PDF Tools Workstation Modal */}
      <PdfToolsModal
        isOpen={pdfToolsOpen}
        onClose={() => setPdfToolsOpen(false)}
        documents={documents}
        activeDoc={activeDoc}
        onPreviewInViewer={handlePreviewGeneratedPdf}
        initialOperation={pdfToolsInitialOp}
      />
    </div>
  );
}
