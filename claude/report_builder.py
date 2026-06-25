# claude/report_builder.py
"""
VenCap Report Builder
Generates branded Word documents (and PDF via LibreOffice) from structured
report data emitted by Claude in a <report>...</report> block.

Supported output types:  "word"  |  "pdf"
Template:                "board_paper" (default)  |  "letterhead"

The JS builder (build_report.js) lives at the project root alongside this file.
"""

import json
import re
import subprocess
import tempfile
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Path to the JS builder script (same directory as this file's parent)
_HERE        = Path(__file__).parent.parent    # project root
_JS_SCRIPT   = _HERE / "build_report.js"
_NODE        = r"C:\Program Files\nodejs\node.exe"

def _run_js_builder(payload: dict, output_path: Path) -> None:
    """Invoke the Node.js builder with the JSON payload."""
    payload_str = json.dumps(payload, ensure_ascii=False)
    result = subprocess.run(
        [_NODE, str(_JS_SCRIPT), payload_str, str(output_path)],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Report builder failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
    logger.info(f"Report builder: {result.stdout.strip()}")


def build_report(report_data: dict) -> tuple[bytes, str, str]:
    """
    Build a report from the structured data dict.

    Args:
        report_data: dict with keys:
            type            – "word" | "pptx"
            title           – document title
            month           – e.g. "May"
            year            – e.g. "2025"
            date            – e.g. "May 2025" (falls back to month+year)
            template        – "board_paper" | "letterhead" (Word only)
            executive_summary – short paragraph (Word only)
            sections        – list of section dicts (Word only)
            slides          – list of slide dicts (pptx only)

    Returns:
        (file_bytes, filename, mime_type)
    """
    output_type = report_data.get("type", "word").lower()
    title       = report_data.get("title", "VenCap Report")
    now         = datetime.now()
    report_data.setdefault("month", now.strftime("%B"))
    report_data.setdefault("year",  str(now.year))
    report_data.setdefault("date",  f"{report_data['month']} {report_data['year']}")

    with tempfile.TemporaryDirectory() as tmpdir:
        if output_type == "pptx":
            out_path = Path(tmpdir) / "report.pptx"
            mime     = ("application/vnd.openxmlformats-officedocument"
                        ".presentationml.presentation")
            ext      = "pptx"
        else:
            # Default to Word for anything (PDF requests redirected by system prompt)
            out_path = Path(tmpdir) / "report.docx"
            mime     = ("application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document")
            ext      = "docx"

        _run_js_builder(report_data, out_path)
        final_path = out_path
        file_bytes = final_path.read_bytes()

    # Build a clean filename from the title
    safe_title = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")[:60]
    filename   = f"{safe_title}.{ext}"

    return file_bytes, filename, mime


def extract_report_block(text: str) -> tuple[dict | None, str]:
    """
    Extract a <report>...</report> JSON block from Claude's response text.
    Returns (report_dict, cleaned_text) — cleaned_text has the block removed.
    """
    pattern = r"<report>(.*?)</report>"
    match   = re.search(pattern, text, re.DOTALL)
    if not match:
        return None, text

    try:
        data = json.loads(match.group(1).strip())
    except json.JSONDecodeError as e:
        logger.warning(f"Could not parse <report> block: {e}")
        return None, text

    cleaned = re.sub(pattern, "", text, flags=re.DOTALL).strip()
    return data, cleaned