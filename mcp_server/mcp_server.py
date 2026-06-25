# =============================================================================
# mcp_server.py — VenCap MCP Server
# =============================================================================
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# load_dotenv MUST run before db_config is imported
# db_config reads env vars at import time, so .env must already be loaded
load_dotenv(override=True)

from mcp.server.fastmcp import FastMCP
from db_config import connect_gp, connect_lp
from security import is_safe_query, validate_schema_access

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("vencap.mcp")

# ── API key ───────────────────────────────────────────────────────────────────
_MCP_API_KEY: str = os.getenv("MCP_API_KEY", "")

if not _MCP_API_KEY:
    raise RuntimeError(
        "MCP_API_KEY is not set in .env. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )

# ── MCP server instance ───────────────────────────────────────────────────────
mcp = FastMCP(
    name="vencap-mcp-server",
    host="127.0.0.1",
    port=int(os.getenv("MCP_PORT", "8001")),
)

# ── Audit log ─────────────────────────────────────────────────────────────────
_AUDIT_LOG = Path(__file__).parent / "audit_log.jsonl"


def _audit(
    database: str,
    sql: str,
    row_count: int | None = None,
    duration_ms: float | None = None,
    blocked: bool = False,
    block_reason: str | None = None,
) -> None:
    entry = {
        "timestamp":    datetime.now().isoformat(),
        "database":     database.upper(),
        "blocked":      blocked,
        "block_reason": block_reason,
        "row_count":    row_count,
        "duration_ms":  duration_ms,
        "sql":          sql,
    }
    try:
        with _AUDIT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
    except Exception as exc:
        logger.warning("Could not write audit log: %s", exc)


# ── API key check ─────────────────────────────────────────────────────────────
def _check_api_key(api_key: str | None) -> bool:
    import hmac
    if not api_key:
        return False
    return hmac.compare_digest(api_key.strip(), _MCP_API_KEY)


# ── run_sql tool ──────────────────────────────────────────────────────────────
@mcp.tool()
def run_sql(query: str, database: str, api_key: str) -> str:
    """
    Execute a SELECT query against VenCap SQL Server databases.

    Use this for any question about NAV, capital calls, distributions,
    fund performance, portfolio exposure, investor transactions,
    stock holdings, IPO data, or share valuations.

    Only SELECT statements are permitted.

    Args:
        query:    A valid SQL SELECT statement.
                  GP queries may use bot.* and pbi.* schemas.
                  LP queries may only use bot.* schema.
        database: 'gp' for fund-level data (bot.* and pbi.* schemas)
                  'lp' for investor-level data (bot.* schema only)
        api_key:  Server authentication key (from MCP_API_KEY in .env)
    """

    # Layer 1 — API key
    if not _check_api_key(api_key):
        logger.warning("SECURITY: Invalid or missing API key — request rejected.")
        _audit(database, query, blocked=True, block_reason="invalid_api_key")
        return "Error: Unauthorised. Invalid or missing API key."

    # Layer 2 — database parameter
    if database not in ("gp", "lp"):
        logger.warning("SECURITY: Invalid database parameter: %s", database)
        _audit(database, query, blocked=True, block_reason="invalid_database_param")
        return "Error: Invalid database parameter. Must be 'gp' or 'lp'."

    # Layer 3 — SQL safety check
    if not is_safe_query(query):
        logger.warning("SECURITY: Query blocked by safety check. SQL: %s", query[:200])
        _audit(database, query, blocked=True, block_reason="sql_safety_check")
        return "Error: Query blocked. Only SELECT statements are permitted."

    # Layer 4 — schema access check
    if not validate_schema_access(query, database):
        logger.warning("SECURITY: Query blocked by schema check. SQL: %s", query[:200])
        _audit(database, query, blocked=True, block_reason="schema_access_check")
        return "Error: Query references a schema not permitted for this database."

    # Layer 5 — execute against read-only DB login
    conn = None
    try:
        start = time.perf_counter()
        conn  = connect_lp() if database == "lp" else connect_gp()

        cursor = conn.cursor()
        cursor.execute(query)
        rows    = cursor.fetchall()
        columns = [col[0] for col in cursor.description] if cursor.description else []
        duration_ms = round((time.perf_counter() - start) * 1000, 1)

        if not rows:
            _audit(database, query, row_count=0, duration_ms=duration_ms)
            return "No results found for this query."

        result = [dict(zip(columns, row)) for row in rows]
        _audit(database, query, row_count=len(rows), duration_ms=duration_ms)
        logger.info(
            "Query OK | db=%s | rows=%d | %.1fms | sql=%s",
            database.upper(), len(rows), duration_ms, query[:120]
        )
        return json.dumps(result, default=str)

    except Exception as exc:
        logger.error("DB error | db=%s | error=%s | sql=%s", database, exc, query[:200])
        _audit(database, query, blocked=True, block_reason=f"db_error: {exc}")
        return f"Database error: {str(exc)}"

    finally:
        if conn:
            conn.close()


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("VenCap MCP Server starting on 127.0.0.1:%s", os.getenv("MCP_PORT", "8001"))
    mcp.run(transport="sse")