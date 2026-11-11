# 本地运行与调试指南

## 前置条件

- **Python 3.11+**（推荐 3.11 或 3.12）
- **Google Chrome 或 Microsoft Edge** 浏览器
- **Git**
- **操作系统**：Windows / macOS / Linux

## 1. 安装 Python

### Windows

1. 访问 [python.org](https://www.python.org/downloads/) 下载 Python 3.11 或 3.12 安装包
2. 安装时勾选 **"Add Python to PATH"**
3. 打开终端验证：

```powershell
python --version
# Python 3.11.x 或 3.12.x
```

### macOS

```bash
brew install python@3.11
```

### Linux (Debian/Ubuntu)

```bash
sudo apt update
sudo apt install python3.11 python3.11-venv python3-pip
```

## 2. 克隆项目 & 安装依赖

```bash
cd d:\github-code
git clone https://github.com/ARC-MX/sgcc_electricity_new.git
cd sgcc_electricity_new
```

创建虚拟环境并安装依赖：

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> **注意**：`opencv-python-headless` 和 `ddddocr` 包较大（约 100MB+），安装可能需要几分钟。

## 3. 配置环境变量

复制示例配置文件：

```powershell
copy example.env .env
```

编辑 `.env`，填写以下必填项：

```ini
# 国网登录信息
PHONE_NUMBER="你的手机号"
PASSWORD="你的密码"

# Home Assistant
HASS_URL="http://你的HA地址:8123/"
HASS_TOKEN="你的HA长期访问令牌"

# 登录失败后的备选方案
LOGIN_FALLBACK='qrcode'
```

### Home Assistant 令牌获取

1. 打开 Home Assistant 界面
2. 点击左下角用户头像 → 安全
3. 滚动到「长期访问令牌」→ 创建令牌
4. 复制令牌填入 `HASS_TOKEN`

## 4. 运行项目

### 命令行运行

```powershell
# 激活虚拟环境（如果还没激活）
.\.venv\Scripts\Activate.ps1

# 进入脚本目录
cd scripts

# 运行
python main.py
```

### VS Code 调试

1. 用 VS Code 打开项目根目录
2. 按 `F5` 或在「运行和调试」面板选择 **"Debug main.py"**
3. 断点打在 `scripts/data_fetcher.py` 的 `_login` 方法内即可调试登录流程

## 5. 点选验证码说明

国网已从滑动验证码升级为 **腾讯点选验证码**。本项目集成了离线图像匹配方案：

### 工作原理

1. 输入账密后点击登录
2. 系统检测到腾讯验证码弹窗
3. 截取「题目图片」和「背景图片」
4. 使用图像匹配算法（mask IoU + 轮廓匹配 + 边缘匹配）找到目标位置
5. 模拟点击目标位置，提交验证

### 调试图片

验证码处理过程中会自动保存调试图片到 `scripts/pages/` 目录：

- `captcha_answer_attempt_0.png` — 题目图片（需要找的图标）
- `captcha_bg_attempt_0.png` — 背景图片（需要点击的区域）
- `captcha_report_attempt_0.json` — 匹配诊断信息

如果验证码识别失败，查看这些文件可以帮助分析原因。

### 可调参数

在 `.env` 中可以调整：

```ini
# 点选验证码最大刷新重试次数（默认 4）
CAPTCHA_POINT_CLICK_MAX_REFRESHES=4
# 候选方案数量（默认 5）
CAPTCHA_LOCAL_SOLUTION_CANDIDATES=5
# 匹配平均分阈值（默认 0.35，越高越严格）
CAPTCHA_MIN_AVG_SCORE=0.35
# 单个点最低分阈值（默认 0.16）
CAPTCHA_MIN_POINT_SCORE=0.16
# 分数差距阈值（默认 0.002）
CAPTCHA_MIN_SCORE_GAP=0.002
```

### 兜底方案

如果点选验证码识别失败，系统会自动切换到 **二维码登录** 备选方案（需要在 `.env` 中配置 `LOGIN_FALLBACK='qrcode'`）。

## 6. 项目文件结构

```
sgcc_electricity_new/
├── .env                          # 环境变量配置（需自行创建）
├── .vscode/launch.json           # VS Code 调试配置
├── requirements.txt              # Python 依赖
├── example.env                   # 环境变量示例
├── scripts/
│   ├── main.py                   # 入口：定时任务调度
│   ├── data_fetcher.py           # 核心：登录 + 数据抓取
│   ├── sensor_updator.py         # HA REST API 数据推送
│   ├── const.py                  # 常量定义
│   ├── db.py                     # 数据库（SQLite/MySQL）
│   ├── error_watcher.py          # 错误监控 + 截图
│   ├── notify.py                 # 通知（余额不足、二维码）
│   ├── captcha_solver/           # 验证码解决方案
│   │   ├── __init__.py
│   │   ├── image.py              # 图像匹配算法（纯 Python，不依赖 cv2）
│   │   └── tencent.py            # 腾讯点选验证码 DOM 交互
│   └── pages/                    # 调试截图（运行时生成）
└── tests/                        # 单元测试
```

## 7. 登录流程说明

```
启动
  │
  ├── 尝试恢复缓存数据（republish）
  │     └── 有缓存 → 推送到 HA，跳过抓取
  │     └── 无缓存 → 执行登录抓取
  │
  ├── 打开 95598 登录页
  │
  ├── 输入账密 → 点击登录
  │
  ├── 等待登录状态
  │     ├── 已跳转 → 登录成功 ✅
  │     ├── 检测到验证码 → 进入验证码处理
  │     │     ├── 点选验证码 → 图像匹配 → 点击 → 提交
  │     │     │     ├── 成功 → 登录成功 ✅
  │     │     │     └── 失败 → 刷新重试（最多 N 次）
  │     │     └── 其他类型 → 二维码兜底
  │     └── 页面报错 → 二维码兜底
  │
  ├── 登录成功 → 抓取数据
  │     ├── 电费余额
  │     ├── 年度用电/电费
  │     ├── 月度用电/电费
  │     ├── 日用电量
  │     └── 推送到 HA REST API
  │
  └── 定时调度（每天 2 次）
```

## 8. 常见问题

### Q: `ModuleNotFoundError: No module named 'ddddocr'`

确认已激活虚拟环境并安装依赖：
```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Q: 验证码识别一直失败

1. 检查 `scripts/pages/` 下的调试图片，确认截图是否正常
2. 适当降低阈值：`CAPTCHA_MIN_AVG_SCORE=0.35`
3. 增加重试次数：`CAPTCHA_POINT_CLICK_MAX_REFRESHES=4`
4. 确认网络正常，国网页面能正常访问

### Q: 登录次数过多被限制

国网每天有登录次数限制（约 5-10 次/天），频繁测试会导致账号被临时锁定。建议：

1. 调试时使用 `RETRY_TIMES_LIMIT=1` 减少重试
2. 利用缓存恢复机制避免重复登录
3. 一天内不要反复重启程序

### Q: Windows 上 Selenium 报错找不到浏览器

确保已安装 Chrome 或 Edge 浏览器。程序会优先使用 Edge，如果未找到会尝试 Chrome。

### Q: `pip install` 安装 opencv-python-headless 失败

如果 `opencv-python-headless` 安装失败，可以尝试：
```powershell
pip install opencv-python==4.10.0.84
```
注意 `image.py` 中的点选验证码算法在 **没有 cv2 的情况下也能运行**（有纯 numpy fallback），只是精度略低。

### Q: 想只测试验证码识别，不抓数据

在 `scripts/` 下可以创建临时测试脚本：

```python
from captcha_solver.image import PointClickImageSolver
from PIL import Image

solver = PointClickImageSolver()
answer = Image.open("pages/captcha_answer_xxx.png")
bg = Image.open("pages/captcha_bg_xxx.png")
points = solver.solve_from_images(answer, bg)
print(points)
```

## 9. 仅测试交费记录（扫码登录）

用于验证 `paymentRecord` 拉取与入库，不抓余额/用电。

### `.env` 最少配置

```ini
PHONE_NUMBER=你的手机号
PASSWORD=你的密码
LOGIN_FALLBACK=qrcode
DB_TYPE=sqlite
FETCH_PAYMENT_RECORDS=true
```

### 运行

```powershell
.\.venv\Scripts\Activate.ps1
cd scripts
python run_fetch_payment.py
```

流程：登录（失败会走扫码）→ 各户号进交费页 → 点「最近1年」→ 分页拉取 → 写入 `payment_records`（重复跳过；库内已有最新缴费时间则增量截止）。

### 查看结果

```powershell
# 另开终端启动 Web 控制台
cd ..
.\dev\run_dashboard.ps1
```

浏览器打开 http://127.0.0.1:8080/ ，点「交费记录」Tab 看全户报表。或查库表 `payment_records`。

调试页字段可参考 `dev/dump_payment_list.js`（Console 提取 `payLists`）。
