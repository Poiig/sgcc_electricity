import os

# 国网电力官网
LOGIN_URL = "https://95598.cn/osgweb/login"
ELECTRIC_USAGE_URL = "https://95598.cn/osgweb/electricityCharge"
BALANCE_URL = "https://95598.cn/osgweb/userAcc"
BILL_SUMMARY_URL = "https://95598.cn/osgweb/electricityCharge"
STEP_ELECTRICITY_URL = "https://95598.cn/osgweb/stepElectricityConsumption"
# 与登录等页统一用无 www 的 95598.cn，避免跨子域丢 cookie 被踢回登录
PAYMENT_RECORD_URL = "https://95598.cn/osgweb/paymentRecord"
ELECTRIC_BILL_SUMMARY_URL = (
    "https://95598.cn/osgweb01/electricityChargeQuery/queryElectricBillSummary"
)

# Home Assistant
SUPERVISOR_URL = "http://supervisor/core"
API_PATH = "/api/states/"

BALANCE_SENSOR_NAME = "sensor.electricity_charge_balance"
DAILY_USAGE_SENSOR_NAME = "sensor.last_electricity_usage"
YEARLY_USAGE_SENSOR_NAME = "sensor.yearly_electricity_usage"
YEARLY_CHARGE_SENSOR_NAME = "sensor.yearly_electricity_charge"
MONTH_USAGE_SENSOR_NAME = "sensor.month_electricity_usage"
MONTH_CHARGE_SENSOR_NAME = "sensor.month_electricity_charge"
MONTH_VALLEY_SENSOR_NAME = "sensor.month_valley_usage"
MONTH_FLAT_SENSOR_NAME = "sensor.month_flat_usage"
MONTH_PEAK_SENSOR_NAME = "sensor.month_peak_usage"
MONTH_TIP_SENSOR_NAME = "sensor.month_tip_usage"
PREPAY_BALANCE_SENSOR_NAME = "sensor.prepay_balance"
STEP_USED_STEP1_SENSOR_NAME = "sensor.step_used_step1"
STEP_REMAIN_STEP1_SENSOR_NAME = "sensor.step_remain_step1"
STEP_USED_STEP2_SENSOR_NAME = "sensor.step_used_step2"
STEP_REMAIN_STEP2_SENSOR_NAME = "sensor.step_remain_step2"
STEP_USED_STEP3_SENSOR_NAME = "sensor.step_used_step3"
STEP_TOTAL_USAGE_SENSOR_NAME = "sensor.step_total_usage"
STEP_STAGE_SENSOR_NAME = "sensor.step_stage"
BALANCE_UNIT = "CNY"
USAGE_UNIT = "KWH"

# 项目仓库
REPO_URL = "https://github.com/Poiig/sgcc_electricity"

# Home Assistant 传感器友好名称（日志展示用）
SENSOR_LABELS = {
    BALANCE_SENSOR_NAME: "电费余额",
    DAILY_USAGE_SENSOR_NAME: "最近日用电量",
    YEARLY_USAGE_SENSOR_NAME: "年度用电量",
    YEARLY_CHARGE_SENSOR_NAME: "年度电费",
    MONTH_USAGE_SENSOR_NAME: "当月用电量",
    MONTH_CHARGE_SENSOR_NAME: "当月电费",
    MONTH_VALLEY_SENSOR_NAME: "当月谷时用电量",
    MONTH_FLAT_SENSOR_NAME: "当月平时用电量",
    MONTH_PEAK_SENSOR_NAME: "当月峰时用电量",
    MONTH_TIP_SENSOR_NAME: "当月尖时用电量",
    PREPAY_BALANCE_SENSOR_NAME: "预付费余额/应交金额",
    STEP_USED_STEP1_SENSOR_NAME: "阶梯一阶已用电量",
    STEP_REMAIN_STEP1_SENSOR_NAME: "阶梯一阶剩余电量",
    STEP_USED_STEP2_SENSOR_NAME: "阶梯二阶已用电量",
    STEP_REMAIN_STEP2_SENSOR_NAME: "阶梯二阶剩余电量",
    STEP_USED_STEP3_SENSOR_NAME: "阶梯三阶已用电量",
    STEP_TOTAL_USAGE_SENSOR_NAME: "阶梯累计用电量",
    STEP_STAGE_SENSOR_NAME: "阶梯当前阶段",
}


def get_data_dir() -> str:
    """获取数据存储目录：Docker 用 /data，本地用项目下的 data/"""
    if 'PYTHON_IN_DOCKER' in os.environ:
        return '/data'
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def load_project_env() -> None:
    """加载项目根目录 .env（本地开发时 cwd 可能在 scripts/）。"""
    if 'PYTHON_IN_DOCKER' in os.environ:
        return
    import dotenv
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
    dotenv.load_dotenv(env_path, verbose=True, override=True)

