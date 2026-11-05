"""读写 .env 并热加载到当前进程。"""

import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List

logger = logging.getLogger(__name__)

SECRET_KEYS = {
    "PASSWORD",
    "HASS_TOKEN",
    "LLM_API_KEY",
    "MYSQL_PASSWORD",
    "WEB_DASHBOARD_PASSWORD",
    "WEWORK_WEBHOOK_URL",
    "PUSHPLUS_TOKEN",
}

_PLACEHOLDER = "***"
_KV_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_reload_callbacks: List[Callable[[], None]] = []


def get_env_file_path() -> Path:
    explicit = os.getenv("ENV_FILE", "").strip()
    if explicit:
        return Path(explicit)
    if "PYTHON_IN_DOCKER" in os.environ:
        docker_path = Path("/data/.env")
        if docker_path.is_file():
            return docker_path
    return Path(__file__).resolve().parent.parent / ".env"


def register_env_reload(callback: Callable[[], None]) -> None:
    _reload_callbacks.append(callback)


def _parse_kv(text: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _KV_RE.match(stripped)
        if m:
            result[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return result


def _mask_content(text: str) -> str:
    lines = []
    for line in text.splitlines():
        m = _KV_RE.match(line.strip())
        if m and m.group(1) in SECRET_KEYS and m.group(2).strip():
            lines.append(f"{m.group(1)}={_PLACEHOLDER}")
        else:
            lines.append(line)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def read_env_file(mask_secrets: bool = True) -> dict:
    path = get_env_file_path()
    if not path.is_file():
        return {
            "path": str(path),
            "exists": False,
            "content": "",
            "updated_at": None,
            "secret_keys": sorted(SECRET_KEYS),
        }
    raw = path.read_text(encoding="utf-8")
    stat = path.stat()
    return {
        "path": str(path),
        "exists": True,
        "content": _mask_content(raw) if mask_secrets else raw,
        "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "secret_keys": sorted(SECRET_KEYS),
    }


def write_env_file(content: str) -> dict:
    path = get_env_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    new_text = content if content.endswith("\n") else content + "\n"

    if path.is_file():
        backup = path.with_suffix(path.suffix + f".bak.{datetime.now().strftime('%Y%m%d%H%M%S')}")
        shutil.copy2(path, backup)

    path.write_text(new_text, encoding="utf-8")
    logger.info("已更新环境配置文件: %s", path)
    return reload_env()


def reload_env() -> dict:
    from const import load_project_env

    load_project_env()
    for cb in _reload_callbacks:
        try:
            cb()
        except Exception as exc:
            logger.warning("配置重载回调失败: %s", exc)

    return {
        "ok": True,
        "message": "配置已重新加载",
        "path": str(get_env_file_path()),
        "restart_required_keys": [
            "JOB_START_TIME",
            "REPUBLISH_INTERVAL_MINUTES",
            "WEB_DASHBOARD_PORT",
            "WEB_DASHBOARD_PASSWORD",
            "RUN_ON_STARTUP",
        ],
    }
