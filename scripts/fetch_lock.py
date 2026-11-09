"""抓取任务互斥锁，避免并发登录国网。"""

import json
import os
import threading
import time
from contextlib import contextmanager
from typing import Iterator

from const import get_data_dir

_LOCK_FILE = "fetch.lock"
_STATE_FILE = "fetch_state.json"
# 持有锁的进程每分钟刷新一次锁文件时间（心跳）；超过这个时间没有刷新，说明进程已退出，锁视为失效。
# 多户、多次重试时一次同步可能超过 1 小时，所以按心跳判断，而不是按开始时间
_STALE_SECONDS = 600
_HEARTBEAT_SECONDS = 60


def _lock_path() -> str:
    return os.path.join(get_data_dir(), _LOCK_FILE)


def _state_path() -> str:
    return os.path.join(get_data_dir(), _STATE_FILE)


def read_fetch_state() -> dict:
    path = _state_path()
    if not os.path.isfile(path):
        return {"status": "idle", "message": "", "started_at": None, "finished_at": None}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # 如果状态是 running，检查是否应该自动重置
        if data.get("status") == "running" and data.get("started_at"):
            # lock 文件不存在说明进程已重启，立即重置
            lock_path = _lock_path()
            if not os.path.isfile(lock_path):
                data["status"] = "idle"
                data["message"] = "上次任务因容器重启已自动重置"
                write_fetch_state(data)
            elif time.time() - os.path.getmtime(lock_path) > _STALE_SECONDS:
                data["status"] = "idle"
                data["message"] = "上次任务已无响应（锁文件超过 10 分钟没有心跳），已自动重置"
                write_fetch_state(data)
                _release_lock_file()
        return data
    except Exception:
        return {"status": "idle", "message": "", "started_at": None, "finished_at": None}


def write_fetch_state(state: dict) -> None:
    os.makedirs(get_data_dir(), exist_ok=True)
    with open(_state_path(), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def mark_fetch_running(source: str = "manual") -> None:
    prev = read_fetch_state()
    write_fetch_state(
        {
            "status": "running",
            "source": source,
            "message": "正在同步国家电网数据...",
            "started_at": time.time(),
            "finished_at": None,
            "last_success_at": prev.get("last_success_at"),
        }
    )


def mark_fetch_finished(success: bool, message: str = "") -> None:
    prev = read_fetch_state()
    finished = time.time()
    last_success = finished if success else prev.get("last_success_at")
    msg = message or ("同步完成" if success else "同步失败")
    source = prev.get("source", "")
    write_fetch_state(
        {
            "status": "success" if success else "failed",
            "source": source,
            "message": msg,
            "started_at": prev.get("started_at"),
            "finished_at": finished,
            "last_success_at": last_success,
        }
    )
    _release_lock_file()
    write_fetch_state(
        {
            "status": "idle",
            "source": source,
            "message": msg,
            "started_at": prev.get("started_at"),
            "finished_at": finished,
            "last_success_at": last_success,
        }
    )
    # 落盘每日成败并在连续多日失败时推送告警
    try:
        from fetch_health import record_fetch_result

        record_fetch_result(success, message=msg, source=source)
    except Exception as exc:
        import logging

        logging.warning("更新抓取健康记录失败（非致命）: %s", exc)


def is_fetch_running() -> bool:
    return read_fetch_state().get("status") == "running"


def _release_lock_file() -> None:
    path = _lock_path()
    try:
        if os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass


def _try_acquire_lock() -> bool:
    path = _lock_path()
    os.makedirs(get_data_dir(), exist_ok=True)
    if os.path.isfile(path):
        try:
            age = time.time() - os.path.getmtime(path)
            if age > _STALE_SECONDS:
                os.remove(path)
            else:
                return False
        except Exception:
            return False
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        return True
    except FileExistsError:
        return False
    except Exception:
        return False


def _heartbeat(stop: threading.Event) -> None:
    """持有锁期间每分钟刷新锁文件时间，表明进程还活着"""
    while not stop.wait(_HEARTBEAT_SECONDS):
        try:
            os.utime(_lock_path(), None)
        except Exception:
            pass


@contextmanager
def fetch_lock(source: str = "manual", block: bool = False) -> Iterator[bool]:
    acquired = False
    stop = threading.Event()
    try:
        while True:
            if _try_acquire_lock():
                acquired = True
                mark_fetch_running(source)
                threading.Thread(target=_heartbeat, args=(stop,), daemon=True).start()
                break
            if not block:
                yield False
                return
            time.sleep(1)
        yield True
    finally:
        stop.set()
        if acquired:
            _release_lock_file()

