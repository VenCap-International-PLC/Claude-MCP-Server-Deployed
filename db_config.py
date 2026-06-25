# db_config.py
import os
import pyodbc

# ── Connection settings (override via .env if needed) ────────────────────────
DRIVER = os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server")
SERVER = os.getenv("DB_SERVER", r"VENAPP\SQLEXPRESS")
DATABASE = os.getenv("DB_DATABASE", "vencap_bot")
TRUSTED = os.getenv("DB_TRUSTED", "yes")  # Windows auth
ENCRYPT = os.getenv("DB_ENCRYPT", "yes")  # TLS
TRUST_CERT = os.getenv("DB_TRUST_SERVER_CERT", "yes")  # accept server cert

# Read-only bot credentials (SQL auth — stored in .env only, never hardcoded)
BOT_DB_USER = os.getenv("BOT_DB_USER", "")
BOT_DB_PASS = os.getenv("BOT_DB_PASSWORD")   # MUST exist in .env


def _ensure_driver():
    drivers = {d.strip() for d in pyodbc.drivers()}
    if DRIVER not in drivers:
        raise RuntimeError(
            f"SQL Server ODBC driver not found: '{DRIVER}'. "
            f"Install Microsoft ODBC Driver 17 (or 18) for SQL Server."
        )


def connect_readonly():
    """
    Read-only connection for the Claude AI agent layer ONLY.
    Uses vencap_bot_readonly SQL login — SELECT on bot.* schema only.
    No INSERT / UPDATE / DELETE / EXEC permissions on this login.
    Password loaded from .env — never hardcoded here.
    """
    _ensure_driver()

    if not BOT_DB_PASS:
        raise RuntimeError(
            "BOT_DB_PASSWORD is not set in your .env file. "
            "Add it before using the Claude handler."
        )

    conn_str = (
        f"DRIVER={{{DRIVER}}};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        f"UID={BOT_DB_USER};"
        f"PWD={BOT_DB_PASS};"
        f"Encrypt={ENCRYPT};"
        f"TrustServerCertificate={TRUST_CERT};"
    )
    return pyodbc.connect(conn_str, autocommit=True, timeout=30)



INSIGHT_DATABASE = os.getenv("INSIGHT_DB_DATABASE", "vencap-bot-insight")

def connect_insight_readonly():
    """
    Read-only connection for LP/investor data (vencap-bot-insight).
    Uses same credentials as bot connection.
    """
    _ensure_driver()

    if not BOT_DB_PASS:
        raise RuntimeError(
            "BOT_DB_PASSWORD is not set in your .env file."
        )

    conn_str = (
        f"DRIVER={{{DRIVER}}};"
        f"SERVER={SERVER};"
        f"DATABASE={INSIGHT_DATABASE};"  # Different database
        f"UID={BOT_DB_USER};"
        f"PWD={BOT_DB_PASS};"
        f"Encrypt={ENCRYPT};"
        f"TrustServerCertificate={TRUST_CERT};"
    )
    return pyodbc.connect(conn_str, autocommit=True, timeout=30)