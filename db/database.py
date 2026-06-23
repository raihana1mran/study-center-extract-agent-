"""
db/database.py — SQLite database layer with SQLAlchemy ORM
Handles: table creation, UPSERT, deduplication, run history
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional, Dict, Any

from sqlalchemy import (
    create_engine, Column, Integer, String, Boolean,
    Text, DateTime, func, event
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import DATABASE_URL
from utils.logger import log


# ─── ORM Base ───────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ─── Models ─────────────────────────────────────────────────────

class StudyCentre(Base):
    """
    Represents one NIOS Academic Study Centre.
    ai_code is the unique centre identifier issued by NIOS.
    """
    __tablename__ = "study_centres"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    ai_code        = Column(String(30), nullable=False, unique=True, index=True)
    name           = Column(Text, nullable=False)
    address        = Column(Text)
    district       = Column(String(150))
    state          = Column(String(150))
    category       = Column(String(30), default="Academic")
    is_valid       = Column(Boolean, default=True)
    missing_fields = Column(Text, default="[]")   # JSON stored as text for SQLite
    created_at     = Column(DateTime, default=datetime.utcnow)
    updated_at     = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<StudyCentre ai_code={self.ai_code!r} name={self.name!r}>"

    @property
    def missing_fields_list(self) -> list:
        """Deserialise missing_fields JSON text to a Python list."""
        if isinstance(self.missing_fields, list):
            return self.missing_fields
        try:
            return json.loads(self.missing_fields or "[]")
        except (json.JSONDecodeError, TypeError):
            return []


class ScrapeRun(Base):
    """
    Tracks each full scrape run with stats and failed districts.
    """
    __tablename__ = "scrape_runs"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    started_at      = Column(DateTime, default=datetime.utcnow)
    completed_at    = Column(DateTime, nullable=True)
    total_states    = Column(Integer, default=0)
    total_districts = Column(Integer, default=0)
    total_centres   = Column(Integer, default=0)
    failed_districts= Column(Text, default="[]")  # JSON stored as text
    status          = Column(String(20), default="running")  # running | completed | failed

    @property
    def failed_districts_list(self) -> list:
        if isinstance(self.failed_districts, list):
            return self.failed_districts
        try:
            return json.loads(self.failed_districts or "[]")
        except (json.JSONDecodeError, TypeError):
            return []


class CheckpointState(Base):
    """
    Persists progress so crashes can resume from last saved state.
    """
    __tablename__ = "checkpoint_state"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    run_id        = Column(Integer, nullable=False)
    state_code    = Column(String(20))
    state_name    = Column(String(150))
    district_code = Column(String(20))
    district_name = Column(String(150))
    saved_at      = Column(DateTime, default=datetime.utcnow)


# ─── Engine & Session ───────────────────────────────────────────

_engine = None
_SessionLocal = None


def _set_sqlite_pragmas(dbapi_conn, connection_record):
    """Enable WAL mode and foreign keys for better SQLite performance."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            DATABASE_URL,
            echo=False,
        )
        # Apply SQLite performance pragmas on every new connection
        if DATABASE_URL.startswith("sqlite"):
            event.listen(_engine, "connect", _set_sqlite_pragmas)
    return _engine


def get_session() -> Session:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionLocal()


# ─── Init ────────────────────────────────────────────────────────

def init_db() -> None:
    """Create all tables if they don't exist."""
    engine = get_engine()
    Base.metadata.create_all(engine)
    log.info("Database tables initialised (or already exist).")


# ─── CRUD Operations ─────────────────────────────────────────────

def upsert_centres(centres: List[Dict[str, Any]]) -> int:
    """
    Insert or update study centres by ai_code (deduplication key).
    Uses SQLite-compatible INSERT OR REPLACE via session merge.
    Returns number of rows affected.
    """
    if not centres:
        return 0

    count = 0
    with get_session() as session:
        for c in centres:
            # Serialise list fields to JSON text for SQLite
            missing = c.get("missing_fields", [])
            if isinstance(missing, list):
                missing = json.dumps(missing)

            # Check if centre already exists
            existing = session.query(StudyCentre).filter_by(
                ai_code=c["ai_code"]
            ).first()

            if existing:
                # Update existing record
                existing.name           = c.get("name", "")
                existing.address        = c.get("address", "")
                existing.district       = c.get("district", "")
                existing.state          = c.get("state", "")
                existing.category       = c.get("category", "Academic")
                existing.is_valid       = c.get("is_valid", True)
                existing.missing_fields = missing
                existing.updated_at     = datetime.utcnow()
            else:
                # Insert new record
                session.add(StudyCentre(
                    ai_code        = c["ai_code"],
                    name           = c.get("name", ""),
                    address        = c.get("address", ""),
                    district       = c.get("district", ""),
                    state          = c.get("state", ""),
                    category       = c.get("category", "Academic"),
                    is_valid       = c.get("is_valid", True),
                    missing_fields = missing,
                ))
            count += 1

        session.commit()
    return count


def get_all_centres(state: Optional[str] = None) -> List[StudyCentre]:
    """Fetch all centres from DB, optionally filtered by state."""
    with get_session() as session:
        q = session.query(StudyCentre).order_by(StudyCentre.state, StudyCentre.district, StudyCentre.name)
        if state:
            q = q.filter(StudyCentre.state == state)
        return q.all()


def get_centres_count() -> int:
    """Return total number of study centres in DB."""
    with get_session() as session:
        return session.query(func.count(StudyCentre.id)).scalar()


def get_invalid_centres() -> List[StudyCentre]:
    """Return centres that failed validation."""
    with get_session() as session:
        return session.query(StudyCentre).filter(StudyCentre.is_valid == False).all()


# ─── Run Tracking ────────────────────────────────────────────────

def start_run() -> int:
    """Create a new scrape run record and return its ID."""
    with get_session() as session:
        run = ScrapeRun(started_at=datetime.utcnow(), status="running")
        session.add(run)
        session.commit()
        log.info(f"Scrape run #{run.id} started.")
        return run.id


def finish_run(
    run_id: int,
    total_states: int,
    total_districts: int,
    total_centres: int,
    failed_districts: List[Dict],
    status: str = "completed"
) -> None:
    """Mark a scrape run as complete with final stats."""
    with get_session() as session:
        run = session.query(ScrapeRun).filter_by(id=run_id).first()
        if run:
            run.completed_at     = datetime.utcnow()
            run.total_states     = total_states
            run.total_districts  = total_districts
            run.total_centres    = total_centres
            run.failed_districts = json.dumps(failed_districts)
            run.status           = status
            session.commit()
    log.info(f"Run #{run_id} finished: {status} | {total_centres} centres across {total_states} states.")


# ─── Checkpoint ──────────────────────────────────────────────────

def save_checkpoint(
    run_id: int,
    state_code: str,
    state_name: str,
    district_code: str,
    district_name: str
) -> None:
    """Save progress checkpoint to resume from on crash."""
    with get_session() as session:
        # Delete old checkpoint for this run
        session.query(CheckpointState).filter_by(run_id=run_id).delete()
        cp = CheckpointState(
            run_id=run_id,
            state_code=state_code,
            state_name=state_name,
            district_code=district_code,
            district_name=district_name,
        )
        session.add(cp)
        session.commit()


def load_checkpoint(run_id: int) -> Optional[Dict]:
    """Load last saved checkpoint for a run."""
    with get_session() as session:
        cp = session.query(CheckpointState).filter_by(run_id=run_id).order_by(
            CheckpointState.saved_at.desc()
        ).first()
        if cp:
            return {
                "state_code":    cp.state_code,
                "state_name":    cp.state_name,
                "district_code": cp.district_code,
                "district_name": cp.district_name,
            }
    return None


# ─── Dashboard Stats & Search Queries ───────────────────────────

def get_dashboard_stats() -> Dict[str, Any]:
    """Get overall stats for the dashboard."""
    with get_session() as session:
        total_centres = session.query(func.count(StudyCentre.id)).scalar() or 0
        total_states = session.query(func.count(func.distinct(StudyCentre.state))).scalar() or 0
        total_districts = session.query(func.count(func.distinct(StudyCentre.district))).scalar() or 0
        total_runs = session.query(func.count(ScrapeRun.id)).scalar() or 0
        
        # Get last completed run
        last_run = session.query(ScrapeRun).order_by(ScrapeRun.started_at.desc()).first()
        last_run_data = None
        if last_run:
            last_run_data = {
                "id": last_run.id,
                "started_at": last_run.started_at.isoformat() if last_run.started_at else None,
                "completed_at": last_run.completed_at.isoformat() if last_run.completed_at else None,
                "total_centres": last_run.total_centres,
                "status": last_run.status,
            }
            
        return {
            "total_centres": total_centres,
            "total_states": total_states,
            "total_districts": total_districts,
            "total_runs": total_runs,
            "last_run": last_run_data,
        }


def get_state_summary() -> List[Dict[str, Any]]:
    """Get counts of study centres grouped by state."""
    with get_session() as session:
        results = session.query(
            StudyCentre.state,
            func.count(StudyCentre.id)
        ).group_by(StudyCentre.state).order_by(func.count(StudyCentre.id).desc()).all()
        
        return [{"state": r[0] or "Unknown", "count": r[1]} for r in results]


def get_district_summary(state_name: str) -> List[Dict[str, Any]]:
    """Get counts of study centres in a state grouped by district."""
    with get_session() as session:
        results = session.query(
            StudyCentre.district,
            func.count(StudyCentre.id)
        ).filter(StudyCentre.state == state_name).group_by(StudyCentre.district).order_by(func.count(StudyCentre.id).desc()).all()
        
        return [{"district": r[0] or "Unknown", "count": r[1]} for r in results]


def get_recent_runs(limit: int = 10) -> List[Dict[str, Any]]:
    """Get recent scrape runs."""
    with get_session() as session:
        runs = session.query(ScrapeRun).order_by(ScrapeRun.started_at.desc()).limit(limit).all()
        return [
            {
                "id": r.id,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "total_states": r.total_states,
                "total_districts": r.total_districts,
                "total_centres": r.total_centres,
                "failed_districts": r.failed_districts_list,
                "status": r.status,
            }
            for r in runs
        ]


def search_centres(
    query: Optional[str] = None,
    state: Optional[str] = None,
    district: Optional[str] = None,
    page: int = 1,
    per_page: int = 50
) -> Dict[str, Any]:
    """Search and filter study centres with pagination."""
    with get_session() as session:
        q = session.query(StudyCentre)
        
        if state:
            q = q.filter(StudyCentre.state == state)
        if district:
            q = q.filter(StudyCentre.district == district)
            
        if query:
            search_pattern = f"%{query}%"
            q = q.filter(
                (StudyCentre.ai_code.like(search_pattern)) |
                (StudyCentre.name.like(search_pattern)) |
                (StudyCentre.address.like(search_pattern))
            )
            
        total = q.count()
        
        # Paginate
        centres = q.order_by(StudyCentre.state, StudyCentre.district, StudyCentre.name).offset((page - 1) * per_page).limit(per_page).all()
        
        items = [
            {
                "id": c.id,
                "ai_code": c.ai_code,
                "name": c.name,
                "address": c.address,
                "district": c.district,
                "state": c.state,
                "category": c.category,
                "is_valid": c.is_valid,
                "missing_fields": c.missing_fields_list,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in centres
        ]
        
        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page
        }

