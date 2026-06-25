# security.py
import re
import logging

logger = logging.getLogger(__name__)

# ── Blocked SQL patterns ──────────────────────────────────────────────────────
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
    r'\bXP_\w+',
    r'\bSP_\w+',
    r'--',
    r'/\*[\s\S]*?\*/',
    r';',
]

ALLOWED_SCHEMAS = ["bot", "pbi"]


def is_safe_query(sql: str) -> bool:
    if not sql or not sql.strip():
        logger.warning("SECURITY BLOCK: Empty query received.")
        return False

    clean = sql.strip().upper()

    if not clean.startswith("SELECT"):
        logger.warning(f"SECURITY BLOCK: Query does not start with SELECT. SQL: {sql[:200]}")
        return False

    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, clean, re.IGNORECASE | re.DOTALL):
            logger.warning(f"SECURITY BLOCK: Pattern '{pattern}' matched. SQL: {sql[:200]}")
            return False

    return True


def validate_schema_access(sql: str, database: str) -> bool:
    if database == "lp":
        permitted = ["bot"]
    else:
        permitted = ["bot", "pbi"]

    schema_pattern = r'\[?([a-zA-Z]{2,})\]?\.\[?\w+'
    referenced = set(re.findall(schema_pattern, sql, re.IGNORECASE))

    sql_keywords = {"inner", "left", "right", "outer", "cross", "full"}
    referenced -= sql_keywords

    for schema in referenced:
        if schema.lower() not in permitted:
            logger.warning(
                f"SECURITY BLOCK: Schema '{schema}' not permitted for database='{database}'. "
                f"SQL: {sql[:200]}"
            )
            return False

    return True