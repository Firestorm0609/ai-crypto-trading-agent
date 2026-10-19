# Bot Config
# Trading Bot Configuration
import os
from pathlib import Path

# Load .env file if it exists
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            # .env is the source of truth for the bot token: an ambient
            # exported token (e.g. a revoked one left in a shell profile)
            # must never shadow the current one.
            if key.strip() == "TELEGRAM_BOT_TOKEN":
                os.environ[key.strip()] = value.strip()
            else:
                os.environ.setdefault(key.strip(), value.strip())

# API Configuration
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
# xAI (Grok) — primary/main LLM (moved from vernom 2026-10-15)
XAI_API_KEY = os.environ.get("XAI_API_KEY", "")
XAI_MODEL = os.environ.get("XAI_MODEL", "grok-4.7")
XAI_BASE_URL = "https://api.x.ai/v1"

# Auto-trade live routing: AUTO_TRADE_LIVE=1 routes rule/strategy signals to
# real Jupiter/Solana swaps; otherwise they stay paper. Cap keeps a misbehaved
# rule from looping a drain-through-the-wallet.
AUTO_TRADE_LIVE = os.environ.get("AUTO_TRADE_LIVE", "0") == "1"
AUTO_TRADE_MAX_USD = float(os.environ.get("AUTO_TRADE_MAX_USD", "25"))

# Tool scoping: the old Mistral heuristics hid ~150 of ~194 tools from the
# model every call. Grok handles the full registry fine and the owner wants
# the agent never to hold back on its toolset — scoping is now DISABLED by
# default (set TOOL_SCOPING=1 to re-enable the lean subset).
TOOL_SCOPING = os.environ.get("TOOL_SCOPING", "0") == "1"

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "mistralai/mistral-small")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "qwen/qwen3-32b")
MISTRAL_MODEL = os.environ.get("MISTRAL_MODEL", "mistral-small-latest")

# Collect ALL Mistral API keys
MISTRAL_API_KEYS = []
for i in range(1, 20):
    key = os.environ.get(f"MISTRAL_API_KEY_{i}", "")
    if key:
        MISTRAL_API_KEYS.append(key)
base_mistral = os.environ.get("MISTRAL_API_KEY", "")
if base_mistral:
    MISTRAL_API_KEYS.insert(0, base_mistral)
CEREBRAS_API_KEY = os.environ.get("CEREBRAS_API_KEY", "")
CEREBRAS_MODEL = os.environ.get("CEREBRAS_MODEL", "llama-3.3-70b")  # Cerebras serves real llama-3.3-70b
MAX_AGENT_STEPS = int(os.environ.get("MAX_AGENT_STEPS", "15"))

# Collect ALL Groq API keys (supports GROQ_API_KEY, GROQ_API_KEY_1, GROQ_API_KEY_2, etc.)
GROQ_API_KEYS = []
for i in range(1, 20):  # Support up to 19 keys
    key = os.environ.get(f"GROQ_API_KEY_{i}", "")
    if key:
        GROQ_API_KEYS.append(key)
# Also check the base GROQ_API_KEY
base_key = os.environ.get("GROQ_API_KEY", "")
if base_key:
    GROQ_API_KEYS.insert(0, base_key)

# Paths
WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", Path(__file__).parent / "workspace"))
WORKSPACE_DIR.mkdir(exist_ok=True)
