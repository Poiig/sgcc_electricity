"""Web 仪表盘 FastAPI 服务。"""

import logging
import os
import secrets
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from const import load_project_env
from dashboard_db import (
    db_available,
    get_daily_chart,
    get_monthly_chart,
    get_user_summary,
    is_db_enabled,
    latest_balance_log_timestamp,
    list_balance_logs,
    list_users,
    tail_log,
)
from env_manager import read_env_file, reload_env, write_env_file
from fetch_lock import is_fetch_running, read_fetch_state

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parent / "static" / "dashboard"
_fetch_thread: Optional[threading.Thread] = None
_server_threads: List[threading.Thread] = []
_sessions: dict[str, float] = {}
_SESSION_TTL = 7 * 86400


def _dashboard_enabled() -> bool:
    return os.getenv("WEB_DASHBOARD", "true").strip().lower() in ("true", "1", "yes")


def _bind_hosts() -> List[str]:
    custom = os.getenv("WEB_DASHBOARD_BIND", "").strip()
    if custom:
        return [h.strip() for h in custom.split(",") if h.strip()]
    return ["0.0.0.0", "::"]


def _dashboard_port() -> int:
    return int(os.getenv("WEB_DASHBOARD_PORT", "8080"))


def _dashboard_password() -> str:
    raw = os.getenv("WEB_DASHBOARD_PASSWORD")
    if raw is None or not str(raw).strip():
        return "password"
    return str(raw).strip()


def _login_required() -> bool:
    return True


def _check_session(x_dashboard_session: Optional[str]) -> None:
    if not _login_required():
        return
    if not x_dashboard_session or x_dashboard_session not in _sessions:
        raise HTTPException(status_code=401, detail="请先登录")
    if _sessions[x_dashboard_session] < time.time():
        _sessions.pop(x_dashboard_session, None)
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")


def require_auth(x_dashboard_session: Optional[str] = Header(None, alias="X-Dashboard-Session")) -> None:
    _check_session(x_dashboard_session)


def _cooldown_minutes() -> int:
    try:
        return max(5, int(os.getenv("FETCH_COOLDOWN_MINUTES", "30")))
    except ValueError:
        return 30


def _last_fetch_timestamp() -> Optional[float]:
    state = read_fetch_state()
    for key in ("last_success_at", "finished_at", "started_at"):
        val = state.get(key)
        if val:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    if is_db_enabled():
        ts = latest_balance_log_timestamp()
        if ts is not None:
            return ts
    return None


def _format_ts(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return None


def _run_fetch_subprocess() -> None:
    scripts_dir = Path(__file__).resolve().parent
    try:
        subprocess.run(
            [sys.executable, "run_fetch_once.py"],
            cwd=str(scripts_dir),
            env=os.environ.copy(),
        )
    except Exception as exc:
        logger.exception("手动同步异常: %s", exc)


def _register_routes(router: APIRouter) -> None:
    @router.get("/")
    def index():
        index_file = _STATIC_DIR / "index.html"
        if not index_file.is_file():
            raise HTTPException(status_code=404, detail="dashboard 静态文件缺失")
        return FileResponse(index_file)

    @router.get("/api/config")
    def api_config():
        return {
            "login_required": _login_required(),
            "db_enabled": is_db_enabled(),
            "db_available": db_available(),
            "db_type": os.getenv("DB_TYPE", "sqlite"),
        }

    @router.post("/api/login")
    def api_login(body: dict = Body(...)):
        password = body.get("password", "")
        expected = _dashboard_password()
        if not expected:
            raise HTTPException(status_code=500, detail="控制台未配置密码")
        if password != expected:
            raise HTTPException(status_code=401, detail="密码错误")
        token = secrets.token_urlsafe(32)
        _sessions[token] = time.time() + _SESSION_TTL
        return {"ok": True, "token": token, "message": "登录成功"}

    @router.post("/api/logout")
    def api_logout(x_dashboard_session: Optional[str] = Header(None, alias="X-Dashboard-Session")):
        _sessions.pop(x_dashboard_session or "", None)
        return {"ok": True}

    @router.get("/api/status", dependencies=[Depends(require_auth)])
    def api_status():
        state = read_fetch_state()
        last_ts = _last_fetch_timestamp()
        cooldown = _cooldown_minutes()
        can_fetch = not is_fetch_running()
        if last_ts and can_fetch:
            elapsed = time.time() - last_ts
            if elapsed < cooldown * 60:
                can_fetch = False
                state = {**state, "cooldown_remaining_sec": int(cooldown * 60 - elapsed)}
        return {
            "db_type": os.getenv("DB_TYPE", "sqlite"),
            "db_enabled": is_db_enabled(),
            "db_available": db_available(),
            "fetch": state,
            "can_fetch": can_fetch and not is_fetch_running(),
            "cooldown_minutes": cooldown,
            "last_sync_at": _format_ts(state.get("last_success_at") or state.get("finished_at") or last_ts),
            "last_sync_source": state.get("source") or "",
            "login_required": _login_required(),
        }

    @router.get("/api/logs", dependencies=[Depends(require_auth)])
    def api_logs(per_user: int = Query(5, ge=1, le=20), app_lines: int = Query(100, ge=0, le=500)):
        balance_groups = list_balance_logs(per_user) if is_db_enabled() else []
        return {
            "balance_groups": balance_groups,
            "app_lines": tail_log(app_lines) if app_lines > 0 else [],
        }

    @router.get("/api/users", dependencies=[Depends(require_auth)])
    def api_users():
        if not is_db_enabled():
            return {"users": [], "db_enabled": False, "db_available": False}
        from dashboard_db import _query

        users = list_users()
        for u in users:
            rows = _query(
                "SELECT updated_at FROM users WHERE user_id = ? LIMIT 1",
                (u["user_id"],),
            )
            if rows and rows[0].get("updated_at"):
                u["last_sync"] = rows[0]["updated_at"]
        return {"users": users, "db_enabled": True, "db_available": db_available()}

    @router.get("/api/users/{user_id}", dependencies=[Depends(require_auth)])
    def api_user(user_id: str):
        if not is_db_enabled():
            raise HTTPException(status_code=503, detail="未开启数据库，无法读取用电数据")
        return get_user_summary(user_id)

    @router.get("/api/users/{user_id}/charts/daily", dependencies=[Depends(require_auth)])
    def api_daily(user_id: str, days: int = Query(30, ge=7, le=90)):
        if not is_db_enabled():
            return {"user_id": user_id, "days": days, "data": [], "db_enabled": False}
        return {"user_id": user_id, "days": days, "data": get_daily_chart(user_id, days), "db_enabled": True}

    @router.get("/api/users/{user_id}/charts/monthly", dependencies=[Depends(require_auth)])
    def api_monthly(user_id: str, months: int = Query(12, ge=3, le=24)):
        if not is_db_enabled():
            return {"user_id": user_id, "months": months, "data": [], "db_enabled": False}
        return {"user_id": user_id, "months": months, "data": get_monthly_chart(user_id, months), "db_enabled": True}

    @router.post("/api/fetch", dependencies=[Depends(require_auth)])
    def api_fetch():
        global _fetch_thread
        if is_fetch_running():
            raise HTTPException(status_code=409, detail="已有同步任务正在运行")
        last_ts = _last_fetch_timestamp()
        if last_ts:
            elapsed = time.time() - last_ts
            if elapsed < _cooldown_minutes() * 60:
                raise HTTPException(
                    status_code=429,
                    detail=f"请等待 {_cooldown_minutes()} 分钟后再试",
                )
        if _fetch_thread and _fetch_thread.is_alive():
            raise HTTPException(status_code=409, detail="同步任务已启动")
        _fetch_thread = threading.Thread(target=_run_fetch_subprocess, daemon=True)
        _fetch_thread.start()
        return JSONResponse({"ok": True, "message": "已启动手动同步，请查看运行日志"})

    @router.get("/api/env", dependencies=[Depends(require_auth)])
    def api_env_get():
        return read_env_file(mask_secrets=False)

    @router.put("/api/env", dependencies=[Depends(require_auth)])
    def api_env_put(body: dict = Body(...)):
        content = body.get("content")
        if content is None or not isinstance(content, str):
            raise HTTPException(status_code=400, detail="缺少 content 字段")
        result = write_env_file(content)
        logging.info("Web 控制台已保存并重载 .env")
        return result

    @router.post("/api/env/reload", dependencies=[Depends(require_auth)])
    def api_env_reload():
        return reload_env()


def create_app() -> FastAPI:
    app = FastAPI(title="国家电网数据同步控制台", docs_url=None, redoc_url=None)
    router = APIRouter()
    _register_routes(router)
    app.include_router(router)
    return app


def _access_urls(port: int) -> str:
    return f"http://127.0.0.1:{port}/ · http://[::1]:{port}/"


def _run_uvicorn(host: str, port: int, app: FastAPI) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="warning")


def start_dashboard_servers(app: Optional[FastAPI] = None, block: bool = False) -> None:
    """在 0.0.0.0 与 :: 上监听同一端口（IPv4 + IPv6）。"""
    if not _dashboard_enabled():
        logging.info("WEB_DASHBOARD 未启用，跳过 Web 控制台")
        return
    app = app or create_app()
    port = _dashboard_port()
    hosts = _bind_hosts()
    global _server_threads
    _server_threads = []
    for host in hosts:
        t = threading.Thread(
            target=_run_uvicorn,
            args=(host, port, app),
            daemon=not block,
            name=f"web-dashboard-{host}",
        )
        t.start()
        _server_threads.append(t)
        logging.info("Web 控制台监听 %s:%s", host, port)
    logging.info("Web 控制台访问: %s", _access_urls(port))
    if block:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass


def run_in_thread() -> None:
    start_dashboard_servers(block=False)


def main():
    if "PYTHON_IN_DOCKER" not in os.environ:
        load_project_env()
    start_dashboard_servers(block=True)


if __name__ == "__main__":
    main()
