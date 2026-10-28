/**
 * DocuChat AI - Unified REST API Client
 * Manages JWT authorization headers, base URLs, error handling,
 * documents, conversations, and safe tool invocations.
 */

export function getBackendRoot() {
  if (process.env.REACT_APP_BACKEND_URL) return process.env.REACT_APP_BACKEND_URL.replace(/\/api\/?$/, "");
  const host = typeof window !== "undefined" && window.location.hostname ? window.location.hostname : "localhost";
  const protocol = typeof window !== "undefined" && window.location.protocol ? window.location.protocol : "http:";
  return `${protocol}//${host}:5000`;
}

export function getApiBase() {
  if (process.env.REACT_APP_API_BASE) return process.env.REACT_APP_API_BASE;
  return `${getBackendRoot()}/api`;
}

export const API_BASE = getApiBase();

function getAuthHeaders() {
  const token = localStorage.getItem("docuchat_token");
  const headers = { "Content-Type": "application/json" };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

export const api = {
  // Auth
  async login(username, password) {
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || err.message || "Login failed");
    }
    return res.json();
  },

  async register(username, password, email) {
    const res = await fetch(`${API_BASE}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password, email }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || err.message || "Registration failed");
    }
    return res.json();
  },

  async getMe() {
    const res = await fetch(`${API_BASE}/auth/me`, {
      headers: getAuthHeaders(),
    });
    if (!res.ok) throw new Error("Unauthorized");
    return res.json();
  },

  async logout() {
    try {
      await fetch(`${API_BASE}/auth/logout`, {
        method: "POST",
        headers: getAuthHeaders(),
      });
    } catch {}
    localStorage.removeItem("docuchat_token");
    localStorage.removeItem("docuchat_user");
  },

  // Documents
  async listDocuments(skip = 0, limit = 50) {
    const res = await fetch(`${API_BASE}/documents?skip=${skip}&limit=${limit}`, {
      headers: getAuthHeaders(),
    });
    if (!res.ok) throw new Error("Failed to load documents");
    return res.json();
  },

  async uploadDocument(file) {
    const formData = new FormData();
    formData.append("file", file);
    const token = localStorage.getItem("docuchat_token");
    const headers = {};
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    const res = await fetch(`${API_BASE}/documents`, {
      method: "POST",
      headers,
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || err.message || "Upload failed");
    }
    return res.json();
  },

  async getDocumentStatus(docId) {
    const res = await fetch(`${API_BASE}/documents/${docId}/status`, {
      headers: getAuthHeaders(),
    });
    if (!res.ok) throw new Error("Failed to fetch document status");
    return res.json();
  },

  async deleteDocument(docId) {
    const res = await fetch(`${API_BASE}/documents/${docId}`, {
      method: "DELETE",
      headers: getAuthHeaders(),
    });
    if (!res.ok) throw new Error("Failed to delete document");
    return res.json();
  },

  async getSpreadsheetData(docId, sheetName = null, page = 1, pageSize = 100) {
    const params = new URLSearchParams();
    if (sheetName) params.append("sheet_name", sheetName);
    params.append("page", page);
    params.append("page_size", pageSize);
    const res = await fetch(`${API_BASE}/documents/${docId}/spreadsheet?${params.toString()}`, {
      headers: getAuthHeaders(),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to load spreadsheet data");
    }
    return res.json();
  },

  // Conversations
  async listConversations(skip = 0, limit = 50) {
    const res = await fetch(`${API_BASE}/conversations?skip=${skip}&limit=${limit}`, {
      headers: getAuthHeaders(),
    });
    if (!res.ok) throw new Error("Failed to load conversations");
    return res.json();
  },

  async createConversation(title = "New Chat") {
    const res = await fetch(`${API_BASE}/conversations`, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify({ title }),
    });
    if (!res.ok) throw new Error("Failed to create conversation");
    return res.json();
  },

  async getConversation(convId) {
    const res = await fetch(`${API_BASE}/conversations/${convId}`, {
      headers: getAuthHeaders(),
    });
    if (!res.ok) throw new Error("Failed to fetch conversation");
    return res.json();
  },

  async deleteConversation(convId) {
    const res = await fetch(`${API_BASE}/conversations/${convId}`, {
      method: "DELETE",
      headers: getAuthHeaders(),
    });
    if (!res.ok) throw new Error("Failed to delete conversation");
    return res.json();
  },

  async updateConversation(convId, title) {
    const res = await fetch(`${API_BASE}/conversations/${convId}`, {
      method: "PATCH",
      headers: getAuthHeaders(),
      body: JSON.stringify({ title }),
    });
    if (!res.ok) throw new Error("Failed to update conversation");
    return res.json();
  },

  // Health
  async getHealth() {
    const res = await fetch(`${getBackendRoot()}/health`);
    return res.json();
  },

  async getReadiness() {
    const res = await fetch(`${getBackendRoot()}/ready`);
    return res.json();
  },

  // Excel Artifact Download
  getDownloadUrl(identifier) {
    const safeId = encodeURIComponent(identifier);
    return `${API_BASE}/tools/download/${safeId}`;
  },

  async downloadExcelFile(identifier, downloadFilename) {
    const safeId = encodeURIComponent(identifier);
    const url = `${API_BASE}/tools/download/${safeId}`;
    const token = localStorage.getItem("docuchat_token");
    const headers = {};
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
    const res = await fetch(url, { headers });
    if (!res.ok) {
      throw new Error(`Failed to download workbook: HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const blobUrl = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = blobUrl;
    a.download = downloadFilename || identifier;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(blobUrl);
    document.body.removeChild(a);
  },

  async downloadDocumentFile(identifier, downloadFilename) {
    const safeId = encodeURIComponent(identifier);
    const url = `${API_BASE}/tools/download/${safeId}`;
    const token = localStorage.getItem("docuchat_token");
    const headers = {};
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
    const res = await fetch(url, { headers });
    if (!res.ok) {
      throw new Error(`Failed to download document: HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const blobUrl = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = blobUrl;
    a.download = downloadFilename || identifier;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(blobUrl);
    document.body.removeChild(a);
  },

  // PDF Tools Module
  async pdfToolsPost(endpoint, formData) {
    const token = localStorage.getItem("docuchat_token");
    const headers = {};
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
    const res = await fetch(`${API_BASE}/pdf-tools/${endpoint}`, {
      method: "POST",
      headers,
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || err.message || `PDF operation failed (${res.status})`);
    }
    return res.json();
  },

  async downloadPdfArtifact(identifier, downloadFilename) {
    return this.downloadDocumentFile(identifier, downloadFilename);
  }
};

export default api;
