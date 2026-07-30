"""
core/llm_client.py
Shared LLM client factory.  Both the raw Groq SDK client and the
LangChain-wrapped ChatGroq are provided via module-level singletons so every
agent reuses the same connection pool instead of constructing new instances.
"""

from __future__ import annotations

from typing import Optional

from groq import Groq
from langchain_groq import ChatGroq

from core.config import settings

# ─── Raw Groq SDK client ──────────────────────────────────────────────────────

_groq_client: Optional[Groq] = None


def get_groq_client() -> Groq:
    """Return a lazily-constructed, module-level Groq SDK client."""
    global _groq_client
    if _groq_client is None:
        if not settings.groq_api_key:
            raise EnvironmentError(
                "GROQ_API_KEY is not set. Add it to your .env file."
            )
        _groq_client = Groq(api_key=settings.groq_api_key)
    return _groq_client


# ─── LangChain ChatGroq wrapper ───────────────────────────────────────────────

_langchain_llm: Optional[ChatGroq] = None
_langchain_llm_fast: Optional[ChatGroq] = None


def get_langchain_llm(temperature: float = 0.1) -> ChatGroq:
    """
    Return a LangChain ChatGroq instance using the main model
    (llama-3.3-70b-versatile by default).  temperature is honoured only on
    first construction; subsequent calls return the cached instance.
    """
    global _langchain_llm
    if _langchain_llm is None:
        if not settings.groq_api_key:
            raise EnvironmentError(
                "GROQ_API_KEY is not set. Add it to your .env file."
            )
        _langchain_llm = ChatGroq(
            model=settings.groq_model,
            groq_api_key=settings.groq_api_key,
            temperature=temperature,
        )
    return _langchain_llm


def get_langchain_llm_fast(temperature: float = 0.0) -> ChatGroq:
    """
    Return a LangChain ChatGroq instance using the fast / cheap model
    (llama-3.1-8b-instant by default).  Used for classification tasks.
    """
    global _langchain_llm_fast
    if _langchain_llm_fast is None:
        if not settings.groq_api_key:
            raise EnvironmentError(
                "GROQ_API_KEY is not set. Add it to your .env file."
            )
        _langchain_llm_fast = ChatGroq(
            model=settings.groq_model_fast,
            groq_api_key=settings.groq_api_key,
            temperature=temperature,
        )
    return _langchain_llm_fast
