import json
import logging
from typing import AsyncGenerator, Dict, Any, List, Optional
import httpx
from backend.config import settings

logger = logging.getLogger(__name__)

class OllamaClient:
    def __init__(self, base_url: str = settings.LLM_BASE_URL, model: str = settings.LLM_MODEL):
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def generate_complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = settings.LLM_TEMPERATURE,
        max_tokens: int = settings.LLM_MAX_TOKENS,
    ) -> str:
        """Non-streaming generation."""
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": "24h",
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_gpu": 99,
                "num_thread": getattr(settings, "LLM_NUM_THREADS", 2),
                "num_ctx": getattr(settings, "LLM_NUM_CTX", 2048),
            }
        }
        if system:
            payload["system"] = system

        async with httpx.AsyncClient(timeout=90.0) as client:
            try:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data.get("response", "").strip()
            except Exception as e:
                logger.error(f"Ollama generate_complete error: {e}")
                return ""

    async def stream_generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = settings.LLM_TEMPERATURE,
        max_tokens: int = settings.LLM_MAX_TOKENS,
    ) -> AsyncGenerator[str, None]:
        """Streaming token generator."""
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "keep_alive": "24h",
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_gpu": 99,
                "num_thread": getattr(settings, "LLM_NUM_THREADS", 2),
                "num_ctx": getattr(settings, "LLM_NUM_CTX", 2048),
            }
        }
        if system:
            payload["system"] = system

        client_timeout = getattr(settings, "LLM_TIMEOUT", 180.0)
        async with httpx.AsyncClient(timeout=client_timeout) as client:
            try:
                async with client.stream("POST", url, json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            token = data.get("response", "")
                            if token:
                                yield token
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                err_str = str(e)
                logger.error(f"Ollama stream error: {e}")
                if "not found" in err_str.lower():
                    yield f"\n[Ollama error: Model '{self.model}' not found. Please run 'ollama pull {self.model}']"
                elif "memory" in err_str.lower() or "cuda" in err_str.lower():
                    yield f"\n[Ollama resource error: Insufficient memory/VRAM to load '{self.model}'.]"
                elif "timeout" in err_str.lower() or "timed out" in err_str.lower():
                    yield f"\n[Ollama timeout error: Request to '{self.model}' timed out.]"
                elif "connect" in err_str.lower():
                    yield f"\n[Ollama connection error: Could not reach Ollama at {self.base_url}.]"
                else:
                    yield f"\n[Generation error: {e}]"

ollama_client = OllamaClient()
