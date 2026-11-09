"""本地单次抓取测试（不进入定时循环）"""
import os
import sys
import logging

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from const import load_project_env, get_data_dir
from error_watcher import ErrorWatcher

load_project_env()

ErrorWatcher.init(root_dir=os.path.join(get_data_dir(), "errors"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)-8s] ---- %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
log_path = os.path.join(get_data_dir(), "app.log")
try:
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s  [%(levelname)-8s] ---- %(message)s", "%Y-%m-%d %H:%M:%S"))
    logging.getLogger().addHandler(fh)
except Exception:
    pass

from data_fetcher import DataFetcher, describe_fetch_result
from fetch_lock import fetch_lock, mark_fetch_finished

phone = os.getenv("PHONE_NUMBER")
password = os.getenv("PASSWORD")
logging.info(
    "开始本地测试抓取, 登录方式=%s, DB=%s",
    os.getenv("LOGIN_METHOD"),
    os.getenv("DB_TYPE"),
)
fetcher = DataFetcher(phone, password)
with fetch_lock(source="manual", block=False) as acquired:
    if not acquired:
        logging.error("已有同步任务正在运行，请稍后再试")
        sys.exit(2)
    try:
        success, detail = describe_fetch_result(fetcher.fetch())
        if success:
            mark_fetch_finished(True, f"手动同步完成（{detail}）" if detail else "手动同步完成")
        else:
            mark_fetch_finished(False, f"手动同步失败: {detail}")
            logging.error("手动同步失败: %s", detail)
            sys.exit(1)
    except Exception as exc:
        mark_fetch_finished(False, str(exc))
        raise
logging.info("本地测试抓取完成")
