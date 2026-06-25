# claude/config.py
import os

ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-opus-4-8")
MAX_TOKENS: int = int(os.getenv("CLAUDE_MAX_TOKENS", "4096"))

# How many conversation turns to keep in history per session
# (each turn = 1 user msg + 1 assistant msg)
MAX_HISTORY_TURNS: int = 10

if not ANTHROPIC_API_KEY:
    import warnings
    warnings.warn(
        "ANTHROPIC_API_KEY is not set. Claude AI mode will not work.",
        RuntimeWarning,
    )
