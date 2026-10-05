# =============================================================================
# mcp_server.py — VenCap MCP Server
# =============================================================================
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
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
from log_rotation import MonthlyRotatingFileHandler, rotate_if_stale

# ── Logging ───────────────────────────────────────────────────────────────────
# Python now writes server_console.log itself (instead of start_server.bat
# redirecting output into it). That is what makes monthly rotation possible:
# the file is only ever held open by this process, so it can be closed,
# moved to old_logs/ and reopened at the start of each month.
_HERE        = Path(__file__).parent
_ARCHIVE_DIR = _HERE / "old_logs"
_CONSOLE_LOG = _HERE / "server_console.log"

_log_fmt = logging.Formatter(
    "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_file_handler = MonthlyRotatingFileHandler(_CONSOLE_LOG, _ARCHIVE_DIR)
_file_handler.setFormatter(_log_fmt)
_handlers: list[logging.Handler] = [_file_handler]
if sys.stdout and sys.stdout.isatty():           # also echo when run by hand
    _console = logging.StreamHandler(sys.stdout)
    _console.setFormatter(_log_fmt)
    _handlers.append(_console)
logging.basicConfig(level=logging.INFO, handlers=_handlers, force=True)
logger = logging.getLogger("vencap.mcp")


def _log_uncaught(exc_type, exc, tb):
    logger.critical("Uncaught exception — server exiting", exc_info=(exc_type, exc, tb))

sys.excepthook = _log_uncaught

# Per-query timeout (seconds). The longest queries in the log ran 10-17
# minutes; long before then the analyst's client has usually given up.
_QUERY_TIMEOUT: int = int(os.getenv("DB_QUERY_TIMEOUT", "120"))

# ── API key ───────────────────────────────────────────────────────────────────
_MCP_API_KEY: str = os.getenv("MCP_API_KEY", "")

if not _MCP_API_KEY:
    raise RuntimeError(
        "MCP_API_KEY is not set in .env. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )

# ── MCP server instance ───────────────────────────────────────────────────────
# MCP_HOST controls which network interface this server listens on.
#   "127.0.0.1"          -> localhost only (old reverse-proxy design; NOT
#                            reachable by thin clients on other laptops)
#   "192.168.100.148"    -> this machine's internal LAN IP only (recommended
#                            for the thin-client model — reachable over
#                            VPN/LAN, but not on any other interface)
#   "0.0.0.0"             -> all interfaces (broader; rely on Windows
#                            Firewall / network isolation as the perimeter)
# Set MCP_HOST explicitly in .env before deploying — do not leave this on
# the 127.0.0.1 default once thin clients are in use, or every laptop
# request will be refused at the network level before Layer 1 (API key)
# is ever reached.
_MCP_HOST: str = os.getenv("MCP_HOST", "127.0.0.1")

mcp = FastMCP(
    name="vencap-mcp-server",
    host=_MCP_HOST,
    port=int(os.getenv("MCP_PORT", "8001")),
)

# ── Audit log ─────────────────────────────────────────────────────────────────
_AUDIT_LOG  = _HERE / "audit_log.jsonl"
_audit_lock = threading.Lock()   # tool calls can run concurrently


def _audit(
    database: str,
    sql: str,
    user: str = "unknown",
    row_count: int | None = None,
    duration_ms: float | None = None,
    blocked: bool = False,
    block_reason: str | None = None,
) -> None:
    entry = {
        "timestamp":    datetime.now().isoformat(),
        "user":         user,
        "database":     database.upper(),
        "blocked":      blocked,
        "block_reason": block_reason,
        "row_count":    row_count,
        "duration_ms":  duration_ms,
        "sql":          sql,
    }
    line = json.dumps(entry, default=str) + "\n"
    with _audit_lock:
        try:
            archived = rotate_if_stale(_AUDIT_LOG, _ARCHIVE_DIR)
            if archived:
                logger.info("Audit log rotated -> %s", archived.name)
        except OSError as exc:   # e.g. file open in an editor; retry next write
            logger.warning("Could not rotate audit log (will retry): %s", exc)
        try:
            with _AUDIT_LOG.open("a", encoding="utf-8") as fh:
                fh.write(line)
        except Exception as exc:
            logger.warning("Could not write audit log: %s", exc)


# ── API key check ─────────────────────────────────────────────────────────────
def _check_api_key(api_key: str | None) -> bool:
    import hmac
    if not api_key:
        return False
    return hmac.compare_digest(api_key.strip(), _MCP_API_KEY)


# Console log lines deliberately omit the SQL text — the full statement for
# every query lives only in audit_log.jsonl (match on timestamp + user).

# ── run_sql tool ──────────────────────────────────────────────────────────────
# IMPORTANT: the docstring below IS the tool description sent to every
# analyst's Claude Desktop. From v0.4.0 of the thin client onwards, the
# client fetches tool definitions from this server at startup rather than
# hardcoding them. To change how Claude routes or interprets queries, edit
# this docstring and restart the server — no extension repack or redeploy.
@mcp.tool()
def run_sql(query: str, database: str, api_key: str, user: str = "unknown") -> str:
    """
    Query VenCap portfolio and investor data. Only SELECT statements are permitted.

    DATABASE ROUTING - choose by PERSPECTIVE, not by keyword:

    - 'gp' = FUND perspective. VenCap's funds-of-funds and the venture funds
      they invest into. Schemas: bot.* and pbi.*
      Use for: fund NAV, capital calls VenCap paid to VFs, distributions
      VenCap received, portfolio company exposure, commitments to VFs, VF
      metadata, and stock pipeline / IPO / share valuation data (pbi.*).

    - 'lp' = INVESTOR perspective. External investors in VenCap's own FoFs.
      Schema: bot.* ONLY - never reference pbi.* for lp.
      Use for: calls VenCap made to its investors, distributions paid to
      investors, investor commitments, fees, investor profiles, geography.

    The same word means different things depending on perspective:
      'capital calls VenCap 16 paid to Sequoia'  -> gp
      'capital calls VenCap 16 made to its LPs'  -> lp
      'NAV of VenCap 16'                         -> gp
      'net value for Church Commissioners'       -> lp
      'who are the investors in VenCap 16'       -> lp
      'exposure to Snowflake'                    -> gp

    If the perspective is genuinely ambiguous, ASK the user before querying.
    Never tell the user which database was used - routing is internal only.

    Args:
        query:    A valid SQL SELECT statement. GP queries may use bot.* and
                  pbi.* schemas. LP queries may only use bot.* schema.
        database: 'gp' for fund-level data, 'lp' for investor-level data.
        api_key:  Supplied automatically by the thin client. Do not provide.
        user:     Supplied automatically by the thin client. Do not provide.
    """

    # Layer 1 — API key
    if not _check_api_key(api_key):
        logger.warning("SECURITY: Invalid or missing API key — request rejected.")
        _audit(database, query, user=user, blocked=True, block_reason="invalid_api_key")
        return "Error: Unauthorised. Invalid or missing API key."

    # Layer 2 — database parameter
    if database not in ("gp", "lp"):
        logger.warning("SECURITY: Invalid database parameter: %s", database)
        _audit(database, query, user=user, blocked=True, block_reason="invalid_database_param")
        return "Error: Invalid database parameter. Must be 'gp' or 'lp'."

    # Layer 3 — SQL safety check
    if not is_safe_query(query):
        logger.warning("SECURITY: Query blocked by safety check | db=%s | user=%s", database, user)
        _audit(database, query, user=user, blocked=True, block_reason="sql_safety_check")
        return "Error: Query blocked. Only SELECT statements are permitted."

    # Layer 4 — schema access check
    if not validate_schema_access(query, database):
        logger.warning("SECURITY: Query blocked by schema check | db=%s | user=%s", database, user)
        _audit(database, query, user=user, blocked=True, block_reason="schema_access_check")
        return "Error: Query references a schema not permitted for this database."

    # Layer 5 — execute against read-only DB login
    conn = None
    try:
        start = time.perf_counter()
        conn  = connect_lp() if database == "lp" else connect_gp()
        conn.timeout = _QUERY_TIMEOUT   # per-query limit (connect timeout is separate)

        cursor = conn.cursor()
        cursor.execute(query)
        rows    = cursor.fetchall()
        columns = [col[0] for col in cursor.description] if cursor.description else []
        duration_ms = round((time.perf_counter() - start) * 1000, 1)

        if not rows:
            _audit(database, query, user=user, row_count=0, duration_ms=duration_ms)
            return "No results found for this query."

        result = [dict(zip(columns, row)) for row in rows]
        _audit(database, query, user=user, row_count=len(rows), duration_ms=duration_ms)
        logger.info(
            "Query OK | db=%s | user=%s | rows=%d | %.1fms",
            database.upper(), user, len(rows), duration_ms,
        )
        return json.dumps(result, default=str)

    except Exception as exc:
        if "HYT00" in str(exc):   # ODBC "Query timeout expired"
            logger.warning("Query timeout | db=%s | user=%s", database, user)
            _audit(database, query, user=user, blocked=True, block_reason="query_timeout")
            return (
                f"Error: query exceeded the {_QUERY_TIMEOUT}s time limit and was cancelled. "
                "Narrow it (filter by fund, date range, or use TOP / aggregation) and retry."
            )
        logger.error("DB error | db=%s | user=%s | error=%s", database, user, exc)
        _audit(database, query, user=user, blocked=True, block_reason=f"db_error: {exc}")
        return f"Database error: {str(exc)}"

    finally:
        if conn:
            conn.close()


# ── Event-loop watchdog ───────────────────────────────────────────────────────
# Windows' asyncio Proactor loop has a failure mode: if a client's network
# drops at exactly the wrong moment (VPN blip, Wi-Fi change, laptop sleeping),
# accept() raises WinError 64, asyncio logs "Accept failed on a socket" and
# CLOSES THE LISTENING SOCKET. The process stays alive but never accepts
# another connection — so Task Scheduler sees nothing wrong and never
# restarts it. This handler turns that silent hang into a clean exit, and
# start_server.bat brings the server straight back up.
_HARMLESS_DISCONNECTS = (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)


def _loop_exception_handler(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    message = context.get("message", "")
    exc = context.get("exception")

    if "Accept failed" in message:
        logger.critical(
            "Listening socket was closed by asyncio (%r). Exiting so "
            "start_server.bat restarts the server.", exc,
        )
        logging.shutdown()   # flush logs before exiting
        os._exit(3)

    if isinstance(exc, _HARMLESS_DISCONNECTS):
        # WinError 10054 etc: an analyst's client closed its connection.
        # Previously a full traceback each time (~270 in the log) — pure noise.
        logger.debug("Client disconnected: %r", exc)
        return

    loop.default_exception_handler(context)


async def _serve() -> None:
    import uvicorn

    asyncio.get_running_loop().set_exception_handler(_loop_exception_handler)
    config = uvicorn.Config(
        mcp.sse_app(),
        host=_MCP_HOST,
        port=int(os.getenv("MCP_PORT", "8001")),
        log_level="info",
        log_config=None,   # route uvicorn's logs through our handlers above
    )
    await uvicorn.Server(config).serve()


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("VenCap MCP Server starting on %s:%s", _MCP_HOST, os.getenv("MCP_PORT", "8001"))
    if _MCP_HOST == "127.0.0.1":
        logger.warning(
            "MCP_HOST is still 127.0.0.1 — this server will NOT be reachable "
            "from thin clients on other laptops. Set MCP_HOST in .env to this "
            "machine's LAN IP (or 0.0.0.0) before deploying for thin-client use."
        )
    # Equivalent to mcp.run(transport="sse"), but lets us install the
    # watchdog exception handler on the event loop first.
    asyncio.run(_serve())