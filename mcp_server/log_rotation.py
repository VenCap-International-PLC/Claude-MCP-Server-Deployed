# =============================================================================
# log_rotation.py — monthly log rotation for the VenCap MCP Server
# =============================================================================
# On the first write of a new month, the live log file is moved into
# old_logs/ and renamed with the month it covers, e.g.
#
#     audit_log.jsonl      ->  old_logs/audit_log_2026-09_September.jsonl
#     server_console.log   ->  old_logs/server_console_2026-09_September.log
#
# A fresh, empty file then takes its place. The year-month prefix keeps the
# archive folder sorted in date order in File Explorer.
# =============================================================================
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]


def _month_key(dt: datetime) -> tuple[int, int]:
    return dt.year, dt.month


def archive_file(path: Path, archive_dir: Path, month: tuple[int, int]) -> Path:
    """Move `path` into `archive_dir`, named after the month it covers."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    year, mon = month
    base = f"{path.stem}_{year}-{mon:02d}_{_MONTHS[mon - 1]}"
    target = archive_dir / f"{base}{path.suffix}"
    n = 2
    while target.exists():                      # never overwrite an archive
        target = archive_dir / f"{base}_{n}{path.suffix}"
        n += 1
    os.replace(path, target)
    return target


def rotate_if_stale(path: Path, archive_dir: Path) -> Path | None:
    """
    If `path` was last written in an earlier month, archive it under that
    month's name. Safe to call on every write (one cheap stat call).
    Returns the archive path if a rotation happened.
    """
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    if st.st_size == 0:
        return None
    last_written = datetime.fromtimestamp(st.st_mtime)
    if _month_key(last_written) == _month_key(datetime.now()):
        return None
    return archive_file(path, archive_dir, _month_key(last_written))


class MonthlyRotatingFileHandler(logging.FileHandler):
    """logging handler that rolls its file over at the start of each month."""

    def __init__(self, path: Path, archive_dir: Path):
        self._path = Path(path)
        self._archive_dir = Path(archive_dir)
        self._retry_after: datetime | None = None
        try:
            rotate_if_stale(self._path, self._archive_dir)   # e.g. after a restart
        except OSError as exc:
            print(f"log_rotation: startup rotation failed: {exc}", file=sys.stderr)
        super().__init__(self._path, mode="a", encoding="utf-8")
        self._month = _month_key(datetime.now())

    def emit(self, record: logging.LogRecord) -> None:
        now = datetime.now()
        if _month_key(now) != self._month and (
            self._retry_after is None or now >= self._retry_after
        ):
            if self.stream:
                self.stream.close()
                self.stream = None              # FileHandler reopens on emit
            try:
                archive_file(self._path, self._archive_dir, self._month)
                self._month = _month_key(now)
                self._retry_after = None
            except OSError as exc:
                # e.g. the file is open in an editor that locks it — keep
                # writing to the current file and try again in 10 minutes.
                print(f"log_rotation: could not archive {self._path}: {exc}",
                      file=sys.stderr)
                self._retry_after = now + timedelta(minutes=10)
        super().emit(record)