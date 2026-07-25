"""
app.py — Flask Web Dashboard Backend
"""

import os
import threading
from pathlib import Path
from datetime import datetime
from flask import Flask, jsonify, request, send_file, render_template

from config import INDIAN_STATES, REPORTS_DIR, DOCX_PATH, XLSX_PATH, PDF_PATH, JSON_PATH
from db.database import (
    get_session, StudyCentre, ScrapeRun, CheckpointState,
    get_dashboard_stats, get_state_summary, get_district_summary,
    get_recent_runs, search_centres, init_db
)
from main import run_pipeline, _generate_reports

app = Flask(__name__, template_folder='templates', static_folder='static')

# Initialize DB tables and cleanup crashed runs on server start
init_db()
try:
    from datetime import datetime
    with get_session() as session:
        leftovers = session.query(ScrapeRun).filter_by(status="running").all()
        for run in leftovers:
            run.status = "failed"
            run.completed_at = datetime.utcnow()
        session.commit()
        if leftovers:
            print(f"Cleaned up {len(leftovers)} crashed/leftover runs from database.")
except Exception as e:
    print(f"Error cleaning up leftover runs: {e}")


# Thread control for scraping
scrape_lock = threading.Lock()
scrape_thread = None
scrape_status = {
    "running": False,
    "current_state": "",
    "current_district": "",
    "progress": "",
    "error": None
}

def run_scraping_in_background(state_code=None, district_code=None):
    global scrape_status
    try:
        run_pipeline(state_filter=state_code, district_filter=district_code)
        with scrape_lock:
            scrape_status["running"] = False
            scrape_status["current_state"] = ""
            scrape_status["current_district"] = ""
            scrape_status["progress"] = "Scraping completed successfully."
            scrape_status["error"] = None
    except Exception as e:
        import traceback
        error_msg = f"Error: {str(e)}\n{traceback.format_exc()}"
        with scrape_lock:
            scrape_status["running"] = False
            scrape_status["progress"] = "Scraping failed."
            scrape_status["error"] = error_msg

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/config')
def get_app_config():
    return jsonify({
        "states": INDIAN_STATES
    })

@app.route('/api/stats')
def get_stats():
    try:
        stats = get_dashboard_stats()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/centres')
def get_centres():
    try:
        q = request.args.get('q', '')
        state = request.args.get('state', '')
        district = request.args.get('district', '')
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 50))
        
        results = search_centres(
            query=q if q else None,
            state=state if state else None,
            district=district if district else None,
            page=page,
            per_page=per_page
        )
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/centres/<ai_code>')
def get_centre_details(ai_code):
    try:
        with get_session() as session:
            centre = session.query(StudyCentre).filter_by(ai_code=ai_code).first()
            if not centre:
                return jsonify({"error": "Centre not found"}), 404
            
            return jsonify({
                "id": centre.id,
                "ai_code": centre.ai_code,
                "name": centre.name,
                "address": centre.address,
                "district": centre.district,
                "state": centre.state,
                "category": centre.category,
                "is_valid": centre.is_valid,
                "missing_fields": centre.missing_fields_list,
                "created_at": centre.created_at.isoformat() if centre.created_at else None,
                "updated_at": centre.updated_at.isoformat() if centre.updated_at else None,
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/states')
def get_states():
    try:
        return jsonify(get_state_summary())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/districts/<state_name>')
def get_districts(state_name):
    try:
        return jsonify(get_district_summary(state_name))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/districts-live/<state_code>')
def get_districts_live(state_code):
    try:
        from agents.browser_agent import BrowserAgent
        with BrowserAgent() as browser:
            districts = browser.get_districts(state_code)
            return jsonify(districts)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/data/clear', methods=['POST'])
def clear_data_api():
    try:
        from db.database import get_session, StudyCentre, ScrapeRun, CheckpointState
        from sqlalchemy import text
        
        with get_session() as session:
            session.query(StudyCentre).delete()
            session.query(ScrapeRun).delete()
            session.query(CheckpointState).delete()
            try:
                session.execute(text("DELETE FROM sqlite_sequence WHERE name IN ('study_centres', 'scrape_runs', 'checkpoint_state')"))
            except Exception:
                pass
            session.commit()
            
        for path in [DOCX_PATH, XLSX_PATH, PDF_PATH]:
            if path.exists():
                path.unlink()
                
        return jsonify({"status": "success", "message": "Database and reports cleared successfully. Dashboard is fresh."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/runs')
def get_runs():
    try:
        limit = int(request.args.get('limit', 10))
        return jsonify(get_recent_runs(limit))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/runs/start', methods=['POST'])
def start_run_api():
    global scrape_thread, scrape_status
    with scrape_lock:
        if scrape_status["running"]:
            return jsonify({"error": "Scrape run is already in progress"}), 400
        
        data = request.json or {}
        state_code = data.get('state_code', None)
        district_code = data.get('district_code', None)
                
        scrape_status["running"] = True
        scrape_status["progress"] = "Starting scrape run..."
        scrape_status["error"] = None
        
        scrape_thread = threading.Thread(
            target=run_scraping_in_background,
            args=(state_code, district_code),
            daemon=True
        )
        scrape_thread.start()
        
        return jsonify({"status": "started", "message": "Scrape run started in background."})

@app.route('/api/runs/status')
def get_run_status():
    global scrape_status
    with scrape_lock:
        db_running = False
        current_state = scrape_status["current_state"]
        current_district = scrape_status["current_district"]
        progress = scrape_status["progress"]
        
        try:
            with get_session() as session:
                active_run = session.query(ScrapeRun).filter_by(status="running").order_by(ScrapeRun.started_at.desc()).first()
                if active_run:
                    db_running = True
                    cp = session.query(CheckpointState).filter_by(run_id=active_run.id).order_by(CheckpointState.saved_at.desc()).first()
                    if cp:
                        current_state = cp.state_name
                        current_district = cp.district_name
                        progress = f"Scraping {cp.district_name}, {cp.state_name}"
        except Exception:
            pass
                
        is_running = scrape_status["running"] or db_running
        
        return jsonify({
            "running": is_running,
            "current_state": current_state,
            "current_district": current_district,
            "progress": progress,
            "error": scrape_status["error"]
        })

@app.route('/api/reports')
def list_reports():
    reports = []
    formats = {
        "docx": DOCX_PATH,
        "xlsx": XLSX_PATH,
        "pdf": PDF_PATH
    }
    
    for fmt, path in formats.items():
        if path.exists():
            stat = path.stat()
            reports.append({
                "format": fmt,
                "filename": path.name,
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "exists": True
            })
        else:
            reports.append({
                "format": fmt,
                "filename": path.name,
                "size_bytes": 0,
                "modified": None,
                "exists": False
            })
            
    return jsonify(reports)

@app.route('/api/reports/download/<format_type>')
def download_report(format_type):
    formats = {
        "docx": DOCX_PATH,
        "xlsx": XLSX_PATH,
        "pdf": PDF_PATH,
        "json": JSON_PATH
    }
    
    if format_type not in formats:
        return jsonify({"error": "Invalid format"}), 400
        
    path = formats[format_type]
    if not path.exists():
        return jsonify({"error": f"Report in {format_type.upper()} format does not exist yet. Please run a scrape or click regenerate."}), 404
        
    return send_file(path, as_attachment=True)

@app.route('/api/reports/generate', methods=['POST'])
def generate_reports_api():
    try:
        _generate_reports()
        return jsonify({"status": "success", "message": "Reports generated successfully."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route('/api/logs')
def get_live_logs():
    try:
        logs_dir = Path(__file__).parent / "logs"
        log_files = sorted(logs_dir.glob("agent_*.log"))
        if not log_files:
            return jsonify({"filename": None, "logs": "No log files found."})
        
        latest_log = log_files[-1]
        with open(latest_log, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            
        max_lines = int(request.args.get('max_lines', 200))
        recent_lines = lines[-max_lines:] if len(lines) > max_lines else lines
        
        return jsonify({
            "filename": latest_log.name,
            "logs": "".join(recent_lines)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
