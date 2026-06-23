"""
main.py — NIOS Study Centre Collection Agent Orchestrator

Usage:
  python main.py                  # Run full pipeline once
  python main.py --schedule       # Run now + schedule every 30 days
  python main.py --reports-only   # Generate reports from existing DB data
  python main.py --test           # Test with Delhi only (1 district)
  python main.py --state 9107     # Run for a single state code

Pipeline:
  For each State → For each District:
    1. Browser Agent  : Open NIOS form, select State/District/Academic, submit
    2. Extraction Agent: Parse HTML → structured JSON
    3. Validation Agent: Validate fields, flag missing data
    4. Database        : UPSERT records (dedup on ai_code)
    Retry each district up to 3 times on failure.
  After all states:
    5. Report Agent   : Generate DOCX, XLSX, PDF
"""

from __future__ import annotations

import sys
import time
import argparse
import traceback
from datetime import datetime
from typing import List, Dict, Any, Optional

from config import (
    INDIAN_STATES, MAX_RETRIES, REQUEST_DELAY_SECONDS,
    DOCX_PATH, XLSX_PATH, PDF_PATH,
)
from db.database import (
    init_db, upsert_centres, get_all_centres, get_centres_count,
    start_run, finish_run, save_checkpoint, load_checkpoint,
)
from agents.browser_agent import BrowserAgent
from agents.extraction_agent import ExtractionAgent
from agents.validation_agent import ValidationAgent
from agents.report_agent import ReportAgent
from utils.logger import (
    log, log_separator, log_state_start,
    log_district_result, log_district_failure, log_run_summary,
)


# ════════════════════════════════════════════════════════════════
#  Core Pipeline
# ════════════════════════════════════════════════════════════════

def run_pipeline(
    state_filter: Optional[str] = None,
    district_limit: Optional[int] = None,
    district_filter: Optional[str] = None,
) -> None:
    """
    Full NIOS Academic Study Centre extraction pipeline.

    Args:
        state_filter:   If set, only scrape this state code.
        district_limit: If set, stop after this many districts per state.
    """
    start_time = time.time()

    # ── Initialise DB ──
    init_db()

    # ── Start run tracking ──
    run_id = start_run()

    # ── Agent instances ──
    extractor  = ExtractionAgent()
    validator  = ValidationAgent()
    validator.reset_dedup()

    # ── State list (optionally filtered) ──
    states_to_process = INDIAN_STATES
    if state_filter:
        states_to_process = [s for s in INDIAN_STATES if s["code"] == state_filter]
        if not states_to_process:
            log.error(f"State code {state_filter!r} not found. Exiting.")
            return

    total_states     = len(states_to_process)
    total_districts  = 0
    total_centres    = 0
    failed_districts = []

    log_separator("NIOS ACADEMIC STUDY CENTRE AGENT — STARTING")
    log.info(f"Run #{run_id} | States to process: {total_states}")
    log.info(f"Category: Academic only | Retry: {MAX_RETRIES}x | Delay: {REQUEST_DELAY_SECONDS}s")
    log_separator()

    # ── Open browser (single session for all scraping) ──
    with BrowserAgent() as browser:

        for state_idx, state in enumerate(states_to_process, start=1):
            state_name = state["name"]
            state_code = state["code"]

            log_state_start(state_name, state_idx, total_states)

            # ── Get districts for this state ──
            districts = _get_districts_with_retry(browser, state_code, state_name)
            if not districts:
                log.warning(f"  No districts found for {state_name}. Skipping.")
                continue

            if district_limit:
                districts = districts[:district_limit]

            if district_filter:
                districts = [d for d in districts if d["code"] == district_filter]

            log.info(f"  Districts found: {len(districts)}")
            total_districts += len(districts)

            # ── Process each district ──
            for dist_idx, district in enumerate(districts, start=1):
                district_name = district["name"]
                district_code = district["code"]

                log.info(
                    f"  [{dist_idx}/{len(districts)}] {district_name}"
                )

                # Save checkpoint
                save_checkpoint(run_id, state_code, state_name,
                                district_code, district_name)

                # Scrape with retries
                centres_found = _scrape_district_with_retry(
                    browser=browser,
                    extractor=extractor,
                    validator=validator,
                    state_name=state_name,
                    state_code=state_code,
                    district_name=district_name,
                    district_code=district_code,
                    run_id=run_id,
                    failed_districts=failed_districts,
                )
                total_centres += centres_found

            log.info(
                f"  ✓ {state_name} complete | "
                f"Districts: {len(districts)} | "
                f"Centres so far: {total_centres}"
            )

    # ── Finish run ──
    elapsed = time.time() - start_time
    finish_run(
        run_id=run_id,
        total_states=total_states,
        total_districts=total_districts,
        total_centres=total_centres,
        failed_districts=failed_districts,
        status="completed",
    )
    log_run_summary(
        run_id=run_id,
        total_states=total_states,
        total_districts=total_districts,
        total_centres=total_centres,
        failed_count=len(failed_districts),
        elapsed_seconds=elapsed,
    )

    # ── Generate reports ──
    _generate_reports()


# ════════════════════════════════════════════════════════════════
#  District Scraping with Retry
# ════════════════════════════════════════════════════════════════

def _scrape_district_with_retry(
    browser: BrowserAgent,
    extractor: ExtractionAgent,
    validator: ValidationAgent,
    state_name: str,
    state_code: str,
    district_name: str,
    district_code: str,
    run_id: int,
    failed_districts: List[Dict],
) -> int:
    """
    Attempt to scrape one district up to MAX_RETRIES times.
    Returns number of valid centres stored, or 0 on all-fail.
    Appends to failed_districts list on failure.
    """
    delay = 5.0
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # 1. Browser: get HTML
            html = browser.search_study_centres(
                state_code=state_code,
                state_name=state_name,
                district_code=district_code,
                district_name=district_name,
            )

            if not html:
                raise ValueError("Empty HTML returned from browser")

            # 2. Extract centres from HTML
            raw_centres = extractor.extract(html, state_name, district_name)

            # 3. Validate
            validated = validator.validate_batch(raw_centres, use_ai_fallback=True)

            # 4. Store in DB (upsert = dedup on ai_code)
            if validated:
                upsert_centres([
                    {
                        "ai_code":        c["ai_code"],
                        "name":           c.get("name", ""),
                        "address":        c.get("address", ""),
                        "district":       c.get("district", district_name),
                        "state":          c.get("state", state_name),
                        "category":       c.get("category", "Academic"),
                        "is_valid":       c.get("is_valid", True),
                        "missing_fields": c.get("missing_fields", []),
                    }
                    for c in validated
                ])

            count = len(validated)
            log_district_result(state_name, district_name, attempt, MAX_RETRIES, count)
            return count

        except Exception as exc:
            last_error = str(exc)
            log_district_failure(state_name, district_name, attempt, MAX_RETRIES, last_error)

            if attempt < MAX_RETRIES:
                log.debug(f"    Retrying in {delay:.0f}s...")
                time.sleep(delay)
                delay *= 2  # exponential backoff
            else:
                # Record permanent failure — continue to next district
                failed_districts.append({
                    "state":    state_name,
                    "district": district_name,
                    "error":    last_error,
                    "attempts": MAX_RETRIES,
                })
                log.error(
                    f"    ✗ Giving up on {district_name}, {state_name} "
                    f"after {MAX_RETRIES} attempts. Continuing..."
                )

    return 0


def _get_districts_with_retry(
    browser: BrowserAgent,
    state_code: str,
    state_name: str,
) -> List[Dict]:
    """Get districts for a state, retrying up to MAX_RETRIES times."""
    delay = 5.0
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return browser.get_districts(state_code)
        except Exception as exc:
            log.warning(f"  District enumeration failed (attempt {attempt}/{MAX_RETRIES}): {exc}")
            if attempt < MAX_RETRIES:
                time.sleep(delay)
                delay *= 2
    return []


# ════════════════════════════════════════════════════════════════
#  Report Generation
# ════════════════════════════════════════════════════════════════

def _generate_reports() -> None:
    """Pull all centres from DB and generate DOCX/XLSX/PDF."""
    log_separator("GENERATING REPORTS")

    centres = get_all_centres()
    if not centres:
        log.warning("No centres in database — reports will be empty.")

    reporter = ReportAgent()
    results  = reporter.generate_all(centres)

    log_separator()
    log.info("Reports saved:")
    for fmt, path in results.items():
        log.info(f"  {fmt.upper()}: {path}")


# ════════════════════════════════════════════════════════════════
#  CLI Entry Point
# ════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="NIOS Academic Study Centre Collection Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                         # Full run (all states)
  python main.py --schedule              # Run now + repeat every 30 days
  python main.py --reports-only          # Generate reports from DB (no scraping)
  python main.py --test                  # Quick test: Delhi, 1 district
  python main.py --state 9107            # Only Delhi
  python main.py --state 9107 --dlimit 3 # Delhi, max 3 districts
        """,
    )

    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Run pipeline now then repeat every 30 days automatically.",
    )
    parser.add_argument(
        "--reports-only",
        action="store_true",
        help="Generate reports from existing database data (skip scraping).",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Quick test run: Delhi state, limit to 1 district.",
    )
    parser.add_argument(
        "--state",
        type=str,
        default=None,
        help="Only process a specific state code (e.g. 9107 for Delhi).",
    )
    parser.add_argument(
        "--dlimit",
        type=int,
        default=None,
        help="Limit districts per state (useful for testing).",
    )
    parser.add_argument(
        "--district",
        type=str,
        default=None,
        help="Only process a specific district code (e.g. 910706 for CENTRAL DELHI).",
    )

    args = parser.parse_args()

    # ── Reports only ──
    if args.reports_only:
        init_db()
        _generate_reports()
        return

    # ── Test mode ──
    if args.test:
        log.info("🧪 TEST MODE: Delhi state, 1 district only")
        run_pipeline(state_filter="9107", district_limit=1)
        return

    # ── Scheduled mode ──
    if args.schedule:
        from utils.scheduler import run_now_then_schedule
        run_now_then_schedule(lambda: run_pipeline(
            state_filter=args.state,
            district_limit=args.dlimit,
            district_filter=args.district,
        ))
        return

    # ── Normal run ──
    run_pipeline(
        state_filter=args.state,
        district_limit=args.dlimit,
        district_filter=args.district,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("\nInterrupted by user. Exiting gracefully.")
        sys.exit(0)
    except Exception as e:
        log.critical(f"Fatal error in main: {e}")
        log.debug(traceback.format_exc())
        sys.exit(1)
