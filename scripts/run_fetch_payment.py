"""仅拉取交费记录（扫码登录后本地测试用）。

用法（项目根目录已配置 .env）：
  .\\.venv\\Scripts\\Activate.ps1
  cd scripts
  python run_fetch_payment.py

依赖 .env：
  PHONE_NUMBER / PASSWORD
  LOGIN_FALLBACK=qrcode   # 验证码失败时扫码
  DB_TYPE=sqlite          # 或 mysql / postgresql
"""
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

# 必须在 import data_fetcher 前设置：只跑交费记录
os.environ["FETCH_ONLY_PAYMENT"] = "1"
os.environ.setdefault("FETCH_PAYMENT_RECORDS", "true")

from const import load_project_env, get_data_dir
from error_watcher import ErrorWatcher

load_project_env()
# load_project_env 可能覆盖，再强制一次
os.environ["FETCH_ONLY_PAYMENT"] = "1"

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
    "开始交费记录测试抓取, 登录方式=%s, DB=%s, FETCH_ONLY_PAYMENT=1",
    os.getenv("LOGIN_METHOD") or os.getenv("LOGIN_FALLBACK"),
    os.getenv("DB_TYPE"),
)
fetcher = DataFetcher(phone, password)
with fetch_lock(source="manual-payment", block=False) as acquired:
    if not acquired:
        logging.error("已有同步任务正在运行，请稍后再试")
        sys.exit(2)
    try:
        status, detail = describe_fetch_result(fetcher.fetch())
        if status != "failed":
            mark_fetch_finished(True, f"交费{detail}" if status == "success" else f"交费同步{detail}")
        else:
            mark_fetch_finished(False, f"交费同步失败: {detail}")
            logging.error("交费同步失败: %s", detail)
            sys.exit(1)
    except Exception as exc:
        mark_fetch_finished(False, str(exc))
        raise
logging.info("交费记录测试抓取完成；可打开 Web 控制台查看「缴费记录」")
