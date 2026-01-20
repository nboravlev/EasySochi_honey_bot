import os
from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any
from collections import Counter

class LogReader:
    def __init__(self, log_dir: str = "/app/logs"):
        self.log_dir = Path(log_dir)
    
    def get_log_files(self) -> List[Dict[str, Any]]:
        """Get list of available log files"""
        log_files = []
        if self.log_dir.exists():
            for file_path in self.log_dir.glob("*.log*"):
                stat = file_path.stat()
                log_files.append({
                    'name': file_path.name,
                    'path': str(file_path),
                    'size': stat.st_size,
                    'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
        return sorted(log_files, key=lambda x: x['modified'], reverse=True)
    
    def read_structured_logs(
        self,
        limit: int = 100,
        level: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        user_id: Optional[int] = None,
        action: Optional[str] = None,
        search_query: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Read and filter structured logs"""
        logs = []
        structured_log_file = self.log_dir / "bot_structured.log"
        
        print(f"Looking for log file: {structured_log_file}")
        print(f"File exists: {structured_log_file.exists()}")
        print(f"Log directory exists: {self.log_dir.exists()}")
        if self.log_dir.exists():
            print(f"Files in log dir: {list(self.log_dir.glob('*'))}")
        
        if not structured_log_file.exists():
            return logs
        
        try:
            with open(structured_log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                print(f"Read {len(lines)} lines from log file")
                
                for line_num, line in enumerate(lines):
                    if not line.strip():
                        continue
                    
                    try:
                        log_entry = json.loads(line.strip())
                        
                        # Apply filters
                        if level and log_entry.get('level') != level:
                            continue
                        
                        if user_id and log_entry.get('user_id') != user_id:
                            continue
                        
                        if action and action.lower() not in log_entry.get('action', '').lower():
                            continue
                        
                        if search_query:
                            search_text = f"{log_entry.get('message', '')} {log_entry.get('action', '')}".lower()
                            if search_query.lower() not in search_text:
                                continue
                        
                        # Time filtering
                        if start_time or end_time:
                            try:
                                timestamp_str = log_entry.get('timestamp', '')
                                if timestamp_str.endswith('Z'):
                                    log_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                                else:
                                    log_time = datetime.fromisoformat(timestamp_str)
                                
                                # Make log_time timezone-naive for comparison
                                if log_time.tzinfo is not None:
                                    log_time = log_time.replace(tzinfo=None)
                                
                                if start_time and log_time < start_time:
                                    continue
                                if end_time and log_time > end_time:
                                    continue
                            except (ValueError, TypeError) as e:
                                print(f"Error parsing timestamp: {timestamp_str}, error: {e}")
                                continue
                        
                        logs.append(log_entry)
                        
                        if len(logs) >= limit:
                            break
                    
                    except json.JSONDecodeError as e:
                        print(f"Error parsing JSON on line {line_num}: {e}")
                        continue
        
        except Exception as e:
            print(f"Error reading logs: {e}")
        
        print(f"Returning {len(logs)} logs after filtering")
        return list(reversed(logs))  # Most recent first
    
    def get_log_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Get logging statistics for the last N hours"""
        start_time = datetime.utcnow() - timedelta(hours=hours)
        logs = self.read_structured_logs(limit=10000, start_time=start_time)
        
        if not logs:
            return {
                'total_logs': 0,
                'level_distribution': {},
                'top_actions': {},
                'error_count': 0,
                'unique_users': 0,
                'avg_execution_time': 0
            }
        
        # Calculate statistics
        level_counts = Counter(log.get('level') for log in logs)
        action_counts = Counter(log.get('action') for log in logs if log.get('action'))
        error_count = sum(1 for log in logs if log.get('level') == 'ERROR')
        unique_users = len(set(log.get('user_id') for log in logs if log.get('user_id')))
        
        # Calculate average execution time
        exec_times = [log.get('execution_time') for log in logs if log.get('execution_time')]
        avg_exec_time = sum(exec_times) / len(exec_times) if exec_times else 0
        
        return {
            'total_logs': len(logs),
            'level_distribution': dict(level_counts),
            'top_actions': dict(action_counts.most_common(10)),
            'error_count': error_count,
            'unique_users': unique_users,
            'avg_execution_time': round(avg_exec_time, 3),
            'timeframe_hours': hours
        }

# FastAPI app setup
app = FastAPI(title="Bot Log Viewer", description="Web interface for viewing bot logs")

# Mount static files and templates - FIXED FOR YOUR DOCKERFILE STRUCTURE
templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

log_reader = LogReader()

@app.get("/")
async def dashboard(request: Request):
    """Main dashboard page"""
    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.get("/api/logs")
async def get_logs(
    limit: int = Query(100, ge=1, le=1000),
    level: Optional[str] = Query(None),
    hours: Optional[int] = Query(24, ge=1, le=168),
    user_id: Optional[int] = Query(None),
    action: Optional[str] = Query(None),
    search: Optional[str] = Query(None)
):
    """API endpoint to get filtered logs"""
    start_time = datetime.utcnow() - timedelta(hours=hours) if hours else None
    
    logs = log_reader.read_structured_logs(
        limit=limit,
        level=level,
        start_time=start_time,
        user_id=user_id,
        action=action,
        search_query=search
    )
    
    return {
        "logs": logs,
        "total": len(logs),
        "filters": {
            "limit": limit,
            "level": level,
            "hours": hours,
            "user_id": user_id,
            "action": action,
            "search": search
        }
    }

@app.get("/api/stats")
async def get_stats(hours: int = Query(24, ge=1, le=168)):
    """API endpoint to get logging statistics"""
    return log_reader.get_log_stats(hours=hours)

@app.get("/api/files")
async def get_log_files():
    """API endpoint to get list of log files"""
    return {"files": log_reader.get_log_files()}

@app.get("/logs")
async def logs_page(request: Request):
    """Logs viewing page"""
    return templates.TemplateResponse("logs.html", {"request": request})

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    log_dir_exists = log_reader.log_dir.exists()
    log_files = log_reader.get_log_files()
    
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "log_dir_exists": log_dir_exists,
        "log_files_count": len(log_files),
        "log_files": [f['name'] for f in log_files[:5]]  # Show first 5 files for debugging
    }

if __name__ == "__main__":
    import os
    import uvicorn

    app_host = os.getenv("LOG_VIEWER_HOST", "0.0.0.0")
    app_port = int(os.getenv("LOG_VIEWER_PORT", 8000))

    uvicorn.run(
        "log_viewer:app",
        host=app_host,
        port=app_port,
        log_level="info",
        reload=False
    )