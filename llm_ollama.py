# llm_ollama.py
import os
import requests
from typing import List, Dict

OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")

def chat(messages: List[Dict[str, str]]) -> str:
    """
    Send a ChatCompletion request to the local Ollama server
    and return the assistant's reply.
    """
    url = f"{OLLAMA_BASE}/v1/chat/completions"
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages
    }
    r = requests.post(url, json=payload, timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]
