/**
 * DocuChat AI - Production WebSocket Client
 * Provides resilient, low-latency streaming for:
 * 1. Interactive Chat (/ws/chat) with token streaming & citation delivery.
 * 2. Real-time document ingestion progress (/ws/documents/:id/progress).
 */
import { api } from "./api";

export function getWsBase() {
  if (process.env.REACT_APP_WS_BASE) return process.env.REACT_APP_WS_BASE;
  const host = typeof window !== "undefined" && window.location.hostname ? window.location.hostname : "localhost";
  const protocol = typeof window !== "undefined" && window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${host}:5000`;
}

export class ChatWebSocketClient {
  constructor() {
    this.ws = null;
    this.handlers = {
      start: [],
      token: [],
      citations: [],
      weather: [],
      excel_artifact: [],
      document_artifact: [],
      conversation_renamed: [],
      complete: [],
      error: [],
      close: [],
    };
    this.messageQueue = [];
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 10;
    this.isConnected = false;
    this.lastToken = null;
    this.pingInterval = null;
    this.isExplicitlyClosed = false;
    this.reconnectTimer = null;
  }

  connect(token = null) {
    if (token) this.lastToken = token;
    const effectiveToken = token || this.lastToken || (typeof localStorage !== "undefined" ? localStorage.getItem("docuchat_token") : null);

    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    this.isExplicitlyClosed = false;
    const wsBase = getWsBase();
    const url = effectiveToken
      ? `${wsBase}/ws/chat?token=${encodeURIComponent(effectiveToken)}`
      : `${wsBase}/ws/chat`;

    try {
      this.ws = new WebSocket(url);
    } catch (e) {
      console.error("[WS Chat] Constructor error:", e);
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.isConnected = true;
      this.reconnectAttempts = 0;
      console.log("[WS Chat] Connected successfully to", url);

      // Flush all queued messages safely
      while (this.messageQueue.length > 0) {
        const item = this.messageQueue.shift();
        try {
          this.ws.send(JSON.stringify(item));
        } catch (err) {
          console.error("[WS Chat] Error flushing queued message:", err);
        }
      }

      // Keep-alive heartbeat ping every 25 seconds
      if (this.pingInterval) clearInterval(this.pingInterval);
      this.pingInterval = setInterval(() => {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          try {
            this.ws.send(JSON.stringify({ action: "ping" }));
          } catch {}
        }
      }, 25000);
    };

    this.ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.event === "pong" || payload.ping || payload.pong) return;
        const eventType = payload.event;
        const listeners = this.handlers[eventType] || [];
        listeners.forEach((fn) => fn(payload.data, payload.request_id));
      } catch (e) {
        console.error("[WS Chat] Malformed message:", event.data);
      }
    };

    this.ws.onerror = (err) => {
      console.error("[WS Chat] Socket error:", err);
      // Only emit error handler if message was queued or generation was awaiting
      if (this.messageQueue.length > 0 || !this.isConnected) {
        (this.handlers.error || []).forEach((fn) => fn({ message: "WebSocket connection error" }));
      }
    };

    this.ws.onclose = () => {
      this.isConnected = false;
      if (this.pingInterval) {
        clearInterval(this.pingInterval);
        this.pingInterval = null;
      }
      console.log("[WS Chat] Disconnected.");
      (this.handlers.close || []).forEach((fn) => fn());

      if (!this.isExplicitlyClosed) {
        this.scheduleReconnect();
      }
    };
  }

  scheduleReconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.warn("[WS Chat] Reached max reconnect attempts.");
      return;
    }
    const delay = Math.min(1000 * Math.pow(1.4, this.reconnectAttempts), 5000);
    this.reconnectAttempts++;
    this.reconnectTimer = setTimeout(() => {
      if (!this.isConnected && !this.isExplicitlyClosed) {
        console.log(`[WS Chat] Reconnecting attempt ${this.reconnectAttempts}...`);
        this.connect();
      }
    }, delay);
  }

  on(event, callback) {
    if (!this.handlers[event]) {
      this.handlers[event] = [];
    }
    this.handlers[event].push(callback);
    return () => {
      this.off(event, callback);
    };
  }

  off(event, callback) {
    if (this.handlers[event]) {
      this.handlers[event] = this.handlers[event].filter((fn) => fn !== callback);
    }
  }

  sendMessage(data) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.log("[WS Chat] Socket not yet OPEN; queueing message and connecting...");
      this.messageQueue.push(data);
      this.connect();
      return;
    }
    this.ws.send(JSON.stringify(data));
  }

  disconnect() {
    this.isExplicitlyClosed = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.pingInterval) {
      clearInterval(this.pingInterval);
      this.pingInterval = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}

/**
 * Subscribes to live ingestion job progress for a specific document.
 * Combines WebSocket streaming with a robust polling fallback so progress never gets stuck.
 */
export function subscribeDocumentProgress(docId, onProgress, onComplete, onError) {
  const wsBase = getWsBase();
  const url = `${wsBase}/ws/documents/${docId}/progress`;
  let ws = null;
  let isDone = false;
  let pollInterval = null;

  const startPollingFallback = () => {
    if (pollInterval || isDone) return;
    pollInterval = setInterval(async () => {
      if (isDone) {
        clearInterval(pollInterval);
        return;
      }
      try {
        const docStatus = await api.getDocumentStatus(docId);
        if (docStatus) {
          onProgress && onProgress({
            document_id: docId,
            status: docStatus.status,
            progress: docStatus.job ? docStatus.job.progress : (docStatus.status === "ready" ? 100 : 50),
            message: docStatus.status_message || (docStatus.job ? docStatus.job.message : docStatus.status)
          });
          if (docStatus.status === "ready" || docStatus.status === "failed") {
            isDone = true;
            clearInterval(pollInterval);
            onComplete && onComplete(docStatus);
          }
        }
      } catch (err) {
        console.debug("[WS Progress] Polling check notice:", err);
      }
    }, 2000);
  };

  try {
    ws = new WebSocket(url);

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.ping) return;
        onProgress && onProgress(data);
        if (data.status === "ready" || data.status === "failed") {
          isDone = true;
          if (pollInterval) clearInterval(pollInterval);
          onComplete && onComplete(data);
          try { ws.close(); } catch {}
        }
      } catch (e) {
        console.error("[WS Progress] Parse error:", e);
      }
    };

    ws.onerror = (err) => {
      console.warn("[WS Progress] Socket error, falling back to REST polling:", err);
      startPollingFallback();
      onError && onError(err);
    };

    ws.onclose = () => {
      if (!isDone) {
        startPollingFallback();
      }
    };
  } catch (err) {
    console.warn("[WS Progress] Could not open WebSocket, falling back to REST polling:", err);
    startPollingFallback();
  }

  return () => {
    isDone = true;
    if (pollInterval) clearInterval(pollInterval);
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      try { ws.close(); } catch {}
    }
  };
}

export const chatWs = new ChatWebSocketClient();
