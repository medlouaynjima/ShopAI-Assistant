"""Shared, lazily initialized language-model clients for agent nodes."""
from src.agent.tools import ALL_TOOLS
from src.config import settings

LLM_TIMEOUT_SECONDS = 15

_llm = None
_llms_with_tools = {}


def get_llm():
    """Return the shared language model, initializing it on first use."""
    global _llm
    if _llm is None:
        provider = settings.llm_provider.strip().lower()
        if provider == "ollama":
            from langchain_ollama import ChatOllama

            _llm = ChatOllama(
                model=settings.ollama_model,
                base_url=settings.ollama_base_url,
                temperature=settings.temperature,
                client_kwargs={"timeout": LLM_TIMEOUT_SECONDS},
            )
        elif provider == "google":
            if not settings.gemini_api_key.strip():
                raise RuntimeError(
                    "Gemini is selected but GEMINI_API_KEY is not configured in .env."
                )
            from langchain_google_genai import ChatGoogleGenerativeAI

            _llm = ChatGoogleGenerativeAI(
                model=settings.gemini_model,
                temperature=settings.temperature,
                google_api_key=settings.gemini_api_key,
                timeout=LLM_TIMEOUT_SECONDS,
                max_retries=0,
            )
        elif provider == "openai":
            if not settings.openai_api_key.strip():
                raise RuntimeError(
                    "OpenAI is selected but OPENAI_API_KEY is not configured in .env."
                )
            from langchain_openai import ChatOpenAI

            _llm = ChatOpenAI(
                model=settings.openai_model,
                temperature=settings.temperature,
                api_key=settings.openai_api_key,
                timeout=LLM_TIMEOUT_SECONDS,
                max_retries=0,
            )
        elif provider == "groq":
            if not settings.groq_api_key.strip():
                raise RuntimeError(
                    "Groq is selected but GROQ_API_KEY is not configured in .env."
                )
            from langchain_groq import ChatGroq

            _llm = ChatGroq(
                model=settings.groq_model,
                temperature=settings.temperature,
                api_key=settings.groq_api_key,
                timeout=LLM_TIMEOUT_SECONDS,
                max_retries=0,
            )
        else:
            raise ValueError(
                f"Unsupported LLM_PROVIDER '{settings.llm_provider}'. "
                "Choose 'ollama', 'google', 'openai', or 'groq'."
            )
    return _llm


def get_llm_with_tools(tools=ALL_TOOLS):
    """Return a cached language model bound to the requested tools."""
    key = tuple(tool.name for tool in tools)
    if key not in _llms_with_tools:
        _llms_with_tools[key] = get_llm().bind_tools(tools)
    return _llms_with_tools[key]
