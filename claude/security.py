# claude/security.py
import re
import logging

logger = logging.getLogger(__name__)

# ── Blocked SQL patterns ──────────────────────────────────────────────────────
# Any of these appearing in Claude-generated SQL will cause the query to be
# rejected before it ever reaches the database.

BLOCKED_PATTERNS = [
    r'\bDROP\b',
    r'\bDELETE\b',
    r'\bINSERT\b',
    r'\bUPDATE\b',
    r'\bTRUNCATE\b',
    r'\bEXEC\b',
    r'\bEXECUTE\b',
    r'\bCREATE\b',
    r'\bALTER\b',
    r'\bGRANT\b',
    r'\bREVOKE\b',
    r'\bMERGE\b',
    r'\bBULK\b',
    r'\bOPENROWSET\b',
    r'\bOPENDATASOURCE\b',
    r'\bOPENQUERY\b',
    r'\bXP_\w+',        # xp_cmdshell and other extended stored procedures
    r'\bSP_\w+',        # system stored procedures
    r'--',              # SQL line comment — used in injection attacks
    r'/\*[\s\S]*?\*/',  # SQL block comment (multiline)
    r';',               # semicolon — no legitimate single SELECT needs one
]


def is_safe_query(sql: str) -> bool:
    """
    Validates that Claude-generated SQL is safe to execute.

    Rules:
      1. Must start with SELECT (only read operations allowed)
      2. Must not contain any blocked keywords or patterns

    Returns True if safe, False if blocked.
    Logs a warning if blocked so you have an audit trail.
    """
    if not sql or not sql.strip():
        logger.warning("BLOCKED: Empty query received.")
        return False

    clean = sql.strip().upper()

    # Rule 1 — must start with SELECT
    if not clean.startswith("SELECT"):
        logger.warning(f"BLOCKED: Query does not start with SELECT.\nSQL: {sql[:200]}")
        return False

    # Rule 2 — must not contain blocked patterns
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, clean, re.IGNORECASE | re.DOTALL):
            logger.warning(
                f"BLOCKED: Pattern '{pattern}' found in query.\nSQL: {sql[:200]}"
            )
            return False

    return True


def validate_schema_access(sql: str, allowed_schemas: list = None) -> bool:
    """
    Ensures the query only references allowed schemas.
    Default allowed schemas: bot

    Handles both plain (dbo.table) and bracket notation ([dbo].[table]).
    Note: the readonly DB login is the primary enforcement layer —
    this is a belt-and-suspenders check at the Python level.
    """
    if allowed_schemas is None:
        allowed_schemas = ["bot"]

    # Match both plain and bracket-quoted schema references, e.g.:
    #   bot.fund_navs  →  captures 'bot'
    #   [dbo].[table]  →  captures 'dbo'
    schema_pattern = r'\[?([a-zA-Z]{2,})\]?\.\[?\w+'
    referenced_schemas = set(re.findall(schema_pattern, sql, re.IGNORECASE))

    # Remove known SQL keywords that superficially match schema.column pattern
    sql_keywords = {"inner", "left", "right", "outer", "cross", "full"}
    referenced_schemas -= sql_keywords

    for schema in referenced_schemas:
        if schema.lower() not in [s.lower() for s in allowed_schemas]:
            logger.warning(
                f"BLOCKED: Query references disallowed schema '{schema}'.\nSQL: {sql[:200]}"
            )
            return False

    return True