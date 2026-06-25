# db_config.py
import os
import pyodbc

# ── Connection settings (override via .env) ───────────────────────────────────
DRIVER     = os.getenv("DB_DRIVER",            "ODBC Driver 18 for SQL Server")
SERVER     = os.getenv("DB_SERVER",             r"VENAPP\SQLEXPRESS")
ENCRYPT    = os.getenv("DB_ENCRYPT",            "yes")
TRUST_CERT = os.getenv("DB_TRUST_SERVER_CERT",  "yes")

# Read-only SQL auth credentials — MUST be set in .env, never hardcoded
BOT_DB_USER = os.getenv("BOT_DB_USER",     "")
BOT_DB_PASS = os.getenv("BOT_DB_PASSWORD", "")

# Database names
GP_DATABASE = os.getenv("GP_DB_DATABASE", "vencap-production")
LP_DATABASE = os.getenv("LP_DB_DATABASE", "VenCapInsight")


def _ensure_driver() -> None:
    drivers = {d.strip() for d in pyodbc.drivers()}
    if DRIVER not in drivers:
        raise RuntimeError(
            f"ODBC driver not found: '{DRIVER}'. "
            f"Install Microsoft ODBC Driver 17 (or 18) for SQL Server."
        )


def _check_credentials() -> None:
    if not BOT_DB_USER or not BOT_DB_PASS:
        raise RuntimeError(
            "BOT_DB_USER or BOT_DB_PASSWORD is not set in .env. "
            "Both are required before the MCP server can query the database."
        )


def connect_gp() -> pyodbc.Connection:
    """
    Read-only connection to the GP database (vencap-production).
    bot.* and pbi.* schemas. SELECT only — no write permissions on this login.
    """
    _ensure_driver()
    _check_credentials()
    conn_str = (
        f"DRIVER={{{DRIVER}}};"
        f"SERVER={SERVER};"
        f"DATABASE={GP_DATABASE};"
        f"UID={BOT_DB_USER};"
        f"PWD={BOT_DB_PASS};"
        f"Encrypt={ENCRYPT};"
        f"TrustServerCertificate={TRUST_CERT};"
    )
    return pyodbc.connect(conn_str, autocommit=True, timeout=30)


def connect_lp() -> pyodbc.Connection:
    """
    Read-only connection to the LP database (VenCapInsight).
    bot.* schema only. SELECT only — no write permissions on this login.
    """
    _ensure_driver()
    _check_credentials()
    conn_str = (
        f"DRIVER={{{DRIVER}}};"
        f"SERVER={SERVER};"
        f"DATABASE={LP_DATABASE};"
        f"UID={BOT_DB_USER};"
        f"PWD={BOT_DB_PASS};"
        f"Encrypt={ENCRYPT};"
        f"TrustServerCertificate={TRUST_CERT};"
    )
    return pyodbc.connect(conn_str, autocommit=True, timeout=30)