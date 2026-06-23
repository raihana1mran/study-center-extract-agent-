"""
utils/scheduler.py — APScheduler-based 30-day automatic refresh scheduler.
Persists the job schedule to PostgreSQL so restarts don't lose the schedule.
"""

from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor

from config import DATABASE_URL, REFRESH_DAYS
from utils.logger import log


def create_scheduler() -> BackgroundScheduler:
    """
    Create and configure the APScheduler with PostgreSQL job store.
    Jobs survive application restarts.
    """
    jobstores = {
        "default": SQLAlchemyJobStore(url=DATABASE_URL, tablename="apscheduler_jobs"),
    }
    executors = {
        "default": ThreadPoolExecutor(max_workers=1),
    }
    job_defaults = {
        "coalesce": True,           # merge missed runs into one
        "max_instances": 1,         # only one run at a time
        "misfire_grace_time": 3600, # allow 1hr late start
    }

    scheduler = BackgroundScheduler(
        jobstores=jobstores,
        executors=executors,
        job_defaults=job_defaults,
    )
    return scheduler


def schedule_refresh(run_pipeline_func) -> None:
    """
    Schedule the full pipeline to run immediately and then every REFRESH_DAYS days.

    Args:
        run_pipeline_func: The main pipeline callable (no arguments).
    """
    scheduler = create_scheduler()

    # Calculate next run: now + REFRESH_DAYS
    next_run = datetime.now() + timedelta(days=REFRESH_DAYS)

    # Remove any existing job to avoid duplicates
    try:
        scheduler.remove_job("nios_refresh")
    except Exception:
        pass

    scheduler.add_job(
        func=run_pipeline_func,
        trigger="interval",
        days=REFRESH_DAYS,
        id="nios_refresh",
        name="NIOS Study Centre 30-Day Refresh",
        replace_existing=True,
        next_run_time=next_run,  # First scheduled run after REFRESH_DAYS
    )

    scheduler.start()
    log.info(
        f"Scheduler started. Next automatic refresh: {next_run.strftime('%Y-%m-%d %H:%M')} "
        f"(every {REFRESH_DAYS} days)"
    )
    return scheduler


def run_now_then_schedule(run_pipeline_func) -> None:
    """
    Run the pipeline immediately, then schedule future runs every REFRESH_DAYS days.
    This is the main entry point when --schedule flag is used.
    """
    log.info("Running pipeline immediately (first run)...")
    try:
        run_pipeline_func()
    except Exception as e:
        log.error(f"First pipeline run failed: {e}")

    # Start background scheduler for future runs
    scheduler = schedule_refresh(run_pipeline_func)
    log.info("Scheduler is active. Press Ctrl+C to stop.")

    try:
        import time
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        log.info("Scheduler stopped.")
