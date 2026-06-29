"""Shared LLM config — env-var driven.

Set LLM_PROVIDER, LLM_MODEL, OPENROUTER_API_KEY in your shell.

For local vLLM (default, current setup):
    LLM_PROVIDER=vllm
    LLM_MODEL=Qwen/Qwen3-VL-8B-Instruct

For OpenRouter (e.g., GPT-4o):
    LLM_PROVIDER=openrouter
    LLM_MODEL=openai/gpt-4o
    OPENROUTER_API_KEY=sk-or-v1-...

All three call sites (planner, reflector, ledger) read from here so a single
env change swaps the model everywhere.
"""
import os
import openai


def _get(name, default=None, required=False):
    val = os.environ.get(name, default)
    if required and not val:
        raise RuntimeError(
            f"Required env var {name} not set. "
            f"Add it to ~/.bashrc or your run script."
        )
    return val


PROVIDER = _get("LLM_PROVIDER", "vllm").lower()

if PROVIDER == "vllm":
    BASE_URL = _get("LLM_BASE_URL", "http://localhost:8000/v1")
    API_KEY = _get("LLM_API_KEY", "not-needed")
    MODEL = _get("LLM_MODEL", "Qwen/Qwen3-VL-8B-Instruct")
elif PROVIDER == "openrouter":
    BASE_URL = "https://openrouter.ai/api/v1"
    API_KEY = _get("OPENROUTER_API_KEY", required=True)
    MODEL = _get("LLM_MODEL", "openai/gpt-4o")
else:
    raise RuntimeError(
        f"Unknown LLM_PROVIDER={PROVIDER!r}. Use 'vllm' or 'openrouter'."
    )


def make_client(timeout: int = 120, max_retries: int = 2):
    """Return an OpenAI-compatible client configured for the active provider."""
    return openai.OpenAI(
        api_key=API_KEY,
        base_url=BASE_URL,
        timeout=timeout,
        max_retries=max_retries,
    )


def get_model() -> str:
    """Return the model string for the active provider."""
    return MODEL


def describe() -> str:
    return f"provider={PROVIDER} model={MODEL} base_url={BASE_URL}"
