"""
utils/logger.py — Loguru-based rotating logger for the NIOS agent
Outputs to console (coloured) and to logs/agent_YYYYMMDD.log
"""

import sys
from datetime import datetime
from pathlib import Path

from loguru import logger
from colorama import init as colorama_init

colorama_init(autoreset=True)

# ─── Paths ──────────────────────────────────────────────────────
_LOGS_DIR = Path(__file__).parent.parent / "logs"
_LOGS_DIR.mkdir(exist_ok=True)

_log_filename = _LOGS_DIR / f"agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# ─── Remove default loguru handler ──────────────────────────────
logger.remove()

# ─── Console handler (coloured, concise) ────────────────────────
# Use sys.stderr with errors="replace" to avoid UnicodeEncodeError
# on Windows consoles that use cp1252 encoding.
import io
_console_stream = io.TextIOWrapper(
    sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
)

logger.add(
    _console_stream,
    colorize=True,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{message}</cyan>"
    ),
    level="INFO",
)

# ─── File handler (full detail) ─────────────────────────────────
logger.add(
    str(_log_filename),
    rotation="100 MB",
    retention="90 days",
    compression="zip",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} | {message}",
    level="DEBUG",
    encoding="utf-8",
)

# Public alias
log = logger


def log_separator(title: str = "") -> None:
    """Print a visual separator line to the log."""
    bar = "=" * 70
    if title:
        log.info(f"{bar}")
        log.info(f"  {title.upper()}")
        log.info(f"{bar}")
    else:
        log.info(bar)


def log_state_start(state_name: str, state_index: int, total_states: int) -> None:
    log_separator(f"STATE [{state_index}/{total_states}]: {state_name}")


def log_district_result(
    state: str,
    district: str,
    attempt: int,
    max_attempts: int,
    count: int,
) -> None:
    log.info(
        f"  ✓ District: {district:<30} | State: {state:<25} | "
        f"Attempt: {attempt}/{max_attempts} | Found: {count} centres"
    )


def log_district_failure(
    state: str,
    district: str,
    attempt: int,
    max_attempts: int,
    error: str,
) -> None:
    log.warning(
        f"  ✗ District: {district:<30} | State: {state:<25} | "
        f"Attempt: {attempt}/{max_attempts} | Error: {error}"
    )


def log_run_summary(
    run_id: int,
    total_states: int,
    total_districts: int,
    total_centres: int,
    failed_count: int,
    elapsed_seconds: float,
) -> None:
    log_separator("RUN COMPLETE")
    log.info(f"  Run ID        : #{run_id}")
    log.info(f"  States        : {total_states}")
    log.info(f"  Districts     : {total_districts}")
    log.info(f"  Centres Found : {total_centres}")
    log.info(f"  Failed Dists  : {failed_count}")
    log.info(f"  Elapsed       : {elapsed_seconds/60:.1f} minutes")
    log_separator()
