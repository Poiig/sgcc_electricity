import sys
import os

# Windows 终端 UTF-8（必须在任何中文日志输出之前执行）
if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import logging
import logging.config
import time
import schedule
import json
import random
from error_watcher import ErrorWatcher
from sensor_updator import SensorUpdator
from mqtt_sensor_updator import MQTTSensorUpdator
from datetime import datetime,timedelta
from const import *
from data_fetcher import DataFetcher

def main():
    global RETRY_TIMES_LIMIT
    if 'PYTHON_IN_DOCKER' not in os.environ:
        load_project_env()
    if os.path.isfile('/data/options.json'):
        with open('/data/options.json') as f:
            options = json.load(f)
        try:
            for key, value in options.items():
                os.environ[key] = str(value)
            logging.info("当前以 Home Assistant Add-on 形式运行")
        except Exception as e:
            logging.error(f"读取 options.json 失败，程序退出: {e}")
            sys.exit()

    try:
        PHONE_NUMBER = os.getenv("PHONE_NUMBER")
        PASSWORD = os.getenv("PASSWORD")
        HASS_URL = os.getenv("HASS_URL")
        MQTT_HOST = os.getenv("MQTT_HOST", "").strip()
        JOB_START_TIME = os.getenv("JOB_START_TIME", "09:30")
        RUN_ON_STARTUP = os.getenv("RUN_ON_STARTUP", "false").strip().strip('"').strip("'").lower() in ("true", "1", "yes")
        LOG_LEVEL = os.getenv("LOG_LEVEL","INFO")
        VERSION = os.getenv("VERSION", "unknown")
        RETRY_TIMES_LIMIT = int(os.getenv("RETRY_TIMES_LIMIT", 5))
        
        logger_init(LOG_LEVEL)
        start_web_dashboard_if_enabled()
        if 'PYTHON_IN_DOCKER' in os.environ:
            logging.info("当前运行在 Docker 容器中")
        else:
            logging.info("当前运行在本地环境")
        logging.info(f"登录账号: {PHONE_NUMBER}")
        logging.info(f"RUN_ON_STARTUP={os.getenv('RUN_ON_STARTUP', 'false')} (生效: {'是' if RUN_ON_STARTUP else '否'})")
    except Exception as e:
        logging.error(f"读取环境变量失败，程序退出: {e}")
        sys.exit()

    logging.info(f"当前版本: {VERSION}，构建时间: {os.getenv('BUILD_DATE', 'unknown')}，仓库地址: {REPO_URL}")
    current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logging.info(f"当前时间: {current_datetime}")

    logging.info("正在初始化 ErrorWatcher...")
    error_dir = os.path.join(get_data_dir(), 'errors')
    ErrorWatcher.init(root_dir=error_dir)
    logging.info("ErrorWatcher 初始化完成")
    fetcher = DataFetcher(PHONE_NUMBER, PASSWORD)

    # 初始化数据推送方式
    if MQTT_HOST:
        updator = MQTTSensorUpdator()
        logging.info(f"使用 MQTT Discovery 方式推送数据到: {MQTT_HOST}")
        # 注册到 web_dashboard，避免"立即推送"创建重复 MQTT 连接
        try:
            from web_dashboard import register_mqtt_updator
            register_mqtt_updator(updator)
        except Exception:
            pass
    else:
        updator = SensorUpdator()
        logging.info(f"使用 REST API 方式推送数据到: {HASS_URL}")

    from env_manager import register_env_reload

    register_env_reload(lambda: fetcher.reload_from_env())

    # 生成随机延迟时间（-10分钟到+10分钟）
    random_delay_minutes = random.randint(-10, 10)
    parsed_time = datetime.strptime(JOB_START_TIME, "%H:%M") + timedelta(minutes=random_delay_minutes)
    logging.info(f"登录账号: {PHONE_NUMBER}，每天 {parsed_time.strftime('%H:%M')} 定时同步")

    # 添加随机延迟
    next_run_time = parsed_time + timedelta(hours=12)

    logging.info(f"定时任务已注册，每天 {parsed_time.strftime('%H:%M')} 和 {next_run_time.strftime('%H:%M')} 各执行一次")
    schedule.every().day.at(parsed_time.strftime("%H:%M")).do(run_task, fetcher)
    schedule.every().day.at(next_run_time.strftime("%H:%M")).do(run_task, fetcher)
    
    # 每5分钟重发一次数据，防止HA重启后数据丢失
    schedule.every(5).minutes.do(updator.republish)
    
    # 启动时抓取策略：
    # RUN_ON_STARTUP=true  → 立即登录抓取（Docker 调试/首次部署推荐）
    # 否则先尝试缓存恢复，无缓存才抓取（有缓存则等到定时任务，避免频繁重启封号）
    if RUN_ON_STARTUP:
        logging.info("RUN_ON_STARTUP 已启用，启动后立即执行登录与数据抓取...")
        run_task(fetcher)
    elif not updator.republish():
        logging.info("未找到有效缓存，立即从国家电网抓取数据...")
        run_task(fetcher)
    else:
        logging.info("已从缓存恢复数据，跳过启动时抓取，等待定时任务执行。")
    
    while True:
        schedule.run_pending()
        time.sleep(1)


def run_task(data_fetcher: DataFetcher):
    from fetch_lock import fetch_lock, mark_fetch_finished

    with fetch_lock(source="schedule", block=False) as acquired:
        if not acquired:
            logging.warning("跳过定时同步：已有抓取任务正在运行")
            return
        for retry_times in range(1, RETRY_TIMES_LIMIT + 1):
            try:
                data_fetcher.fetch()
                mark_fetch_finished(True, "定时同步完成")
                return
            except Exception as e:
                logging.error(f"数据同步任务失败: [{e}]，剩余重试次数 {RETRY_TIMES_LIMIT - retry_times}")
                continue
        mark_fetch_finished(False, "定时同步重试次数已用尽")

def logger_init(level: str):
    logger = logging.getLogger()
    logger.setLevel(level)
    # 移除所有默认 handler，避免重复输出（解决 INFO:root: 乱码问题）
    for h in logger.handlers[:]:
        logger.removeHandler(h)
    logging.getLogger("urllib3").setLevel(logging.CRITICAL)
    fmt = logging.Formatter("%(asctime)s  [%(levelname)-8s] ---- %(message)s", "%Y-%m-%d %H:%M:%S")
    sh = logging.StreamHandler(stream=sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    try:
        from logging.handlers import TimedRotatingFileHandler
        log_dir = get_data_dir()
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "app.log")
        # 按天轮转，保留 30 天，轮转后文件名格式 app.log.2026-06-07
        fh = TimedRotatingFileHandler(
            log_file, when="midnight", interval=1, backupCount=30, encoding="utf-8"
        )
        fh.suffix = "%Y-%m-%d"
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception as exc:
        logging.warning("无法写入日志文件 app.log: %s", exc)


def start_web_dashboard_if_enabled() -> None:
    if os.getenv("WEB_DASHBOARD", "true").strip().lower() not in ("true", "1", "yes"):
        return
    try:
        from web_dashboard import run_in_thread

        run_in_thread()
    except Exception as exc:
        logging.warning("Web 控制台启动失败 (非致命): %s", exc)


if __name__ == "__main__":
    main()
