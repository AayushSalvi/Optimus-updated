#!/bin/bash
# install_openrouter_swap.sh
# Swaps all LLM client setups to use a shared env-var-driven config.
# - LLM_PROVIDER: "vllm" (default) or "openrouter"
# - LLM_MODEL:    model string for the chosen provider
# - OPENROUTER_API_KEY: required when LLM_PROVIDER=openrouter
#
# Run from ~/Optimus-1.

set -e
cd ~/Optimus-1

GPT4=src/optimus1/models/gpt4_planning.py
LEDGER=src/optimus1/progress_ledger/llm_client.py
CONFIG=src/optimus1/llm_config.py

# ---------- Pre-flight ----------
python -m py_compile "$GPT4" 2>&1 || { echo "ERROR: $GPT4 doesn't compile"; exit 1; }
python -m py_compile "$LEDGER" 2>&1 || { echo "ERROR: $LEDGER doesn't compile"; exit 1; }

if grep -q "from optimus1.llm_config import" "$GPT4"; then
  echo "ERROR: gpt4_planning.py already patched. To redo, restore from git first."
  exit 1
fi

# Backups
cp "$GPT4" "${GPT4}.bak_openrouter"
cp "$LEDGER" "${LEDGER}.bak_openrouter"
echo "Backups created"

# ---------- 1. Write the shared config module ----------
cat > "$CONFIG" << 'PYEOF'
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
PYEOF

python -m py_compile "$CONFIG" && echo "Wrote $CONFIG"

# ---------- 2. Patch gpt4_planning.py ----------
python3 << 'PYEOF'
import re
import sys

path = "src/optimus1/models/gpt4_planning.py"
with open(path) as f:
    src = f.read()

# Replace client setup
old_client = '''client = openai.OpenAI(
    api_key="not-needed", base_url="http://localhost:8000/v1",
    timeout=2000,
    max_retries=3,
)'''

new_client = '''from optimus1.llm_config import make_client, get_model
client = make_client(timeout=2000, max_retries=3)
_LLM_MODEL = get_model()'''

if old_client not in src:
    print("ERROR: client setup anchor not found in gpt4_planning.py")
    sys.exit(1)
src = src.replace(old_client, new_client, 1)

# Replace all 4 hardcoded model strings
n = src.count('model="Qwen/Qwen3-VL-8B-Instruct"')
src = src.replace('model="Qwen/Qwen3-VL-8B-Instruct"', "model=_LLM_MODEL")
print(f"Replaced {n} model= occurrences in gpt4_planning.py")

# Compile check
try:
    compile(src, path, "exec")
except SyntaxError as e:
    print(f"SyntaxError: {e}")
    sys.exit(1)

with open(path, "w") as f:
    f.write(src)
print(f"Patched {path}")
PYEOF

python -m py_compile "$GPT4" && echo "$GPT4 compiles OK"

# ---------- 3. Patch progress_ledger/llm_client.py ----------
python3 << 'PYEOF'
import re
import sys

path = "src/optimus1/progress_ledger/llm_client.py"
with open(path) as f:
    src = f.read()

# Replace the DEFAULT_MODEL/DEFAULT_BASE_URL constants and _client construction
# with a call to the shared config module.

old_block = '''DEFAULT_MODEL = "Qwen/Qwen3-VL-8B-Instruct"
DEFAULT_BASE_URL = "http://localhost:8000/v1"

# Single shared client (same pattern as gpt4_planning.py)
_client = openai.OpenAI(
    api_key="not-needed",
    base_url=DEFAULT_BASE_URL,
    timeout=120,
    max_retries=2,
)'''

new_block = '''from optimus1.llm_config import make_client, get_model

# Single shared client driven by env-var config (same provider/model as planner)
_client = make_client(timeout=120, max_retries=2)
DEFAULT_MODEL = get_model()'''

if old_block not in src:
    print("ERROR: ledger client anchor not found")
    sys.exit(1)
src = src.replace(old_block, new_block, 1)

try:
    compile(src, path, "exec")
except SyntaxError as e:
    print(f"SyntaxError: {e}")
    sys.exit(1)

with open(path, "w") as f:
    f.write(src)
print(f"Patched {path}")
PYEOF

python -m py_compile "$LEDGER" && echo "$LEDGER compiles OK"

# ---------- 4. Verify ----------
echo ""
echo "=== Verification ==="
echo "Files using llm_config:"
grep -l "from optimus1.llm_config" src/optimus1/models/gpt4_planning.py src/optimus1/progress_ledger/llm_client.py
echo ""
echo "Hardcoded model strings remaining (should be 0):"
grep -c "Qwen/Qwen3-VL-8B-Instruct" src/optimus1/models/gpt4_planning.py src/optimus1/progress_ledger/llm_client.py 2>/dev/null
echo ""
echo "All compiles:"
python -m py_compile src/optimus1/llm_config.py src/optimus1/models/gpt4_planning.py src/optimus1/progress_ledger/llm_client.py && echo "  OK"

echo ""
echo "=== Usage ==="
echo "Run with vLLM/Qwen (default, your current setup):"
echo "  # No env vars needed — defaults work"
echo "  python -m optimus1.main ..."
echo ""
echo "Run with OpenRouter/GPT-4o:"
echo "  export LLM_PROVIDER=openrouter"
echo "  export OPENROUTER_API_KEY=<your-rotated-key>"
echo "  export LLM_MODEL=openai/gpt-4o"
echo "  python -m optimus1.main ..."
echo ""
echo "To check active config:"
echo "  python3 -c 'from optimus1.llm_config import describe; print(describe())'"
