# backend/core/llm.py
import os
from langchain_google_genai import ChatGoogleGenerativeAI

try:
    from core.config import GOOGLE_API_KEY, GROQ_API_KEY, IS_PRODUCTION
except ModuleNotFoundError:
    from backend.core.config import GOOGLE_API_KEY, GROQ_API_KEY, IS_PRODUCTION

# --- LLM RESILIENCE & FAILOVER SYSTEM ---
if GROQ_API_KEY:
    from langchain_groq import ChatGroq
    llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.2)
    print("[AI] Primary LLM: Groq llama-3.3-70b-versatile")
elif GOOGLE_API_KEY:
    llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", google_api_key=GOOGLE_API_KEY, temperature=0.2)
    print("[AI] Primary LLM: Google Gemini 2.0 Flash")
else:
    if IS_PRODUCTION:
        raise ValueError("Critical Security Exception: No valid LLM API key configured in Production mode.")
    llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", google_api_key="DEMO_MODE_NO_KEY", temperature=0.2)
    print("[AI] Warning: Neither GROQ_API_KEY nor GOOGLE_API_KEY set. Operating in dev demo mode.")


def get_fallback_llm():
    """Dynamically instantiates Google Gemini as resilient failover model."""
    key = GOOGLE_API_KEY or "DEMO_MODE_NO_KEY"
    return ChatGoogleGenerativeAI(model="gemini-2.0-flash", google_api_key=key, temperature=0.2)


def safe_llm_invoke(prompt: str, structured_schema=None):
    """
    Resilient LLM Execution Wrapper:
    Attempts to invoke the primary LLM (ChatGroq / Gemini). If rate-limited or timed out,
    catches the exception and seamlessly fails over to ChatGoogleGenerativeAI (Gemini)
    without interrupting graph execution or corrupting memory state.
    """
    global llm
    try:
        if structured_schema:
            target = llm.with_structured_output(structured_schema)
            return target.invoke(prompt)
        else:
            res = llm.invoke(prompt)
            return res.content if hasattr(res, "content") else str(res)
    except Exception as primary_err:
        print(f" [LLM Failover] Primary LLM exception caught. Failing over to fallback Gemini model...")
        try:
            fallback = get_fallback_llm()
            if structured_schema:
                target = fallback.with_structured_output(structured_schema)
                return target.invoke(prompt)
            else:
                res = fallback.invoke(prompt)
                return res.content if hasattr(res, "content") else str(res)
        except Exception as fallback_err:
            print(f" [LLM Failover Critical] Fallback LLM invocation failed.")
            raise fallback_err
