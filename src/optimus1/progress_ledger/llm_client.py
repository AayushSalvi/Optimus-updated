"""LLM client adapter.

Wraps the existing vLLM/OpenAI client (same one used by gpt4_planning.py) into a
simple callable that initializer.py / key_node_detector.py / summarizer.py can use.

Usage:
    call_llm = make_call_llm()   # returns a callable
    response = call_llm(system_prompt, user_text)   # returns str
"""
import logging
from typing import Optional

import openai

logger = logging.getLogger(__name__)

from optimus1.llm_config import make_client, get_model

# Single shared client driven by env-var config (same provider/model as planner)
_client = make_client(timeout=120, max_retries=2)
DEFAULT_MODEL = get_model()


def make_call_llm(model: str = DEFAULT_MODEL, max_tokens: int = 1200, temperature: float = 0.0):
    """Returns a callable: (system_prompt, user_text, model_override=None) -> str.

    The 3 progress_ledger LLM modules accept this callable as a dependency,
    so they don't import openai directly.
    """
    def call_llm(system_prompt: str, user_text: str, model_override: Optional[str] = None) -> str:
        model_to_use = model_override or model
        try:
            response = _client.chat.completions.create(
                model=model_to_use,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            content = response.choices[0].message.content or ""
            return content
        except Exception as e:
            logger.warning(f"[ProgressLedger.llm] call failed: {type(e).__name__}: {e}")
            raise
    return call_llm


def health_check() -> bool:
    """Quick check that vLLM is reachable. Returns True on success."""
    try:
        call = make_call_llm(max_tokens=20)
        out = call("You answer in one word.", "Say OK.")
        logger.info(f"[ProgressLedger.llm] health check response: {out!r}")
        return bool(out)
    except Exception as e:
        logger.warning(f"[ProgressLedger.llm] health check failed: {e}")
        return False
