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
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
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
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        }
        if system:
            payload["system"] = system

        async with httpx.AsyncClient(timeout=120.0) as client:
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
                logger.error(f"Ollama stream error: {e}")
                yield f"\n[Generation error: {e}]"

ollama_client = OllamaClient()
