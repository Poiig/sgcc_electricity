# 国家电网数据获取工具

[![Docker Build](https://github.com/Poiig/sgcc_electricity/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/Poiig/sgcc_electricity/actions/workflows/docker-publish.yml)

自动登录国家电网（95598），抓取电费余额、日/月/年度用电量、分时电量、阶梯用电等数据，存入数据库并支持通过 Web 控制台查看。可选推送到 Home Assistant。

## 致谢

- [ARC-MX/sgcc_electricity_new](https://github.com/ARC-MX/sgcc_electricity_new) — 项目基础框架和数据抓取逻辑
- [renxiaoyaoo/ha-95598](https://github.com/renxiaoyaoo/ha-95598) — 点选验证码识别方案参考

本项目遵循 Apache License 2.0 协议。[更新日志](docs/CHANGELOG.md)

---

## 功能亮点

- 自动登录国家电网（支持点选/滑块验证码自动识别、二维码扫码登录）
- **Web 控制台**：浏览器查看多户用电概览、阶梯用电、日/月图表、运行日志，手动触发同步
- **Home Assistant 推送**：支持 REST API 和 MQTT Discovery 两种方式（可关闭）
- 支持每日/月度/年度分时电量（谷/平/峰/尖）采集
- 支持住宅用户阶梯用电数据（一/二/三阶已用、剩余、当前阶段）
- 数据库支持 SQLite / MySQL / PostgreSQL
- 电费余额不足通知（PushPlus / URL / 企业微信）
- 适用于国家电网覆盖省份（`linux/amd64`、`linux/arm64`）

---

## Web 控制台

启用 `WEB_DASHBOARD=true` 后，访问 `http://<主机>:8080/` 查看多户用电概览、阶梯用电、日/月图表与同步记录。

**本地运行（只读数据库）**：配置好 `.env` 中的 `DB_TYPE` 后，执行 `.\dev\run_dashboard.ps1`（Windows）或 `./dev/run_dashboard.sh`，详见 [dev/README.md](dev/README.md)。

![Web 控制台登录页](docs/attachment/login.png)

![Web 控制台监控页](docs/attachment/controller.png)

---

## Home Assistant 推送

本项目支持将抓取到的数据推送到 Home Assistant，默认启用（`ENABLE_HA_PUSH=true`），可通过 `ENABLE_HA_PUSH=false` 关闭。关闭后程序仅抓取数据并存入数据库，通过 Web 控制台查看。

### 推送方式

| 对比维度 | REST API | MQTT Discovery |
|---------|---------|---------------|
| **配置复杂度** | 需配置 template | 只需配置 MQTT 地址 |
| **实体创建** | 手动配置 template | 自动发现创建 |
| **配置说明** | [REST API 配置指南](docs/HA_CONFIG.md) | [MQTT 使用指南](docs/MQTT.md) |
| **兼容性** | 所有 HA 版本 | 需要 MQTT 集成 |
| **状态保持** | 需要缓存恢复 | retain 消息自动保持 |
| **网络开销** | HTTP 协议 | 轻量级 MQTT |

> **推荐**：MQTT Discovery 方式配置更简单，实体自动创建，详见 [MQTT 使用指南](docs/MQTT.md)。
>
> REST API 方式需要在 HA 的 `configuration.yaml` 中配置 template，详见 [REST API 配置指南](docs/HA_CONFIG.md)。

### 传感器列表

开启 HA 推送后，程序会自动在 Home Assistant 中创建以下实体（`xxxx` 为户号后四位）：

| 实体 | 说明 |
|------|------|
| `sensor.electricity_charge_balance_xxxx` | 电费余额（元） |
| `sensor.last_electricity_usage_xxxx` | 最近一天用电量（kWh） |
| `sensor.yearly_electricity_usage_xxxx` | 今年总用电量（kWh） |
| `sensor.yearly_electricity_charge_xxxx` | 今年总电费（元） |
| `sensor.month_electricity_usage_xxxx` | 上月用电量（kWh） |
| `sensor.month_electricity_charge_xxxx` | 上月电费（元） |
| `sensor.month_valley_usage_xxxx` | 当月谷时用电量（kWh，**需启用数据库**） |
| `sensor.month_flat_usage_xxxx` | 当月平时用电量（kWh，**需启用数据库**） |
| `sensor.month_peak_usage_xxxx` | 当月峰时用电量（kWh，**需启用数据库**） |
| `sensor.month_tip_usage_xxxx` | 当月尖时用电量（kWh，**需启用数据库**） |
| `sensor.prepay_balance_xxxx` | 应交金额（元） |
| `sensor.step_used_step1_xxxx` | 阶梯一阶已用电量（kWh，住宅用户） |
| `sensor.step_remain_step1_xxxx` | 阶梯一阶剩余电量（kWh，住宅用户） |
| `sensor.step_used_step2_xxxx` | 阶梯二阶已用电量（kWh，住宅用户） |
| `sensor.step_remain_step2_xxxx` | 阶梯二阶剩余电量（kWh，住宅用户） |
| `sensor.step_used_step3_xxxx` | 阶梯三阶已用电量（kWh，住宅用户） |
| `sensor.step_total_usage_xxxx` | 阶梯累计用电量（kWh，住宅用户） |
| `sensor.step_stage_xxxx` | 当前阶梯阶段（1/2/3，住宅用户） |

> MQTT Discovery 方式下实体自动创建，无需手动配置。REST API 方式需在 HA 中配置 template，详见 [REST API 配置指南](docs/HA_CONFIG.md)。

### HA 相关配置参数

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ENABLE_HA_PUSH` | `true` | 是否推送到 Home Assistant，设为 `false` 则仅抓取数据不推送 |
| `MQTT_HOST` | 空 | MQTT Broker 地址（推荐方式，填写后自动使用 MQTT Discovery） |
| `MQTT_PORT` | `1883` | MQTT 端口 |
| `MQTT_USERNAME` | 空 | MQTT 用户名 |
| `MQTT_PASSWORD` | 空 | MQTT 密码 |
| `MQTT_CLIENT_ID` | `ha_sgcc_electricity` | MQTT 客户端 ID |
| `MQTT_TOPIC_PREFIX` | `homeassistant` | MQTT Discovery 主题前缀 |
| `MQTT_DEVICE_ID` | `ha_sgcc_electricity` | MQTT 设备 ID |
| `MQTT_DEVICE_NAME` | `国家电网电费数据` | MQTT 设备名称 |
| `HASS_URL` | 空 | Home Assistant REST API 地址（MQTT 未配置时使用） |
| `HASS_TOKEN` | 空 | Home Assistant 长期访问令牌 |
| `HA_SKIP_UNCHANGED` | `false` | 传感器数值未变化时跳过更新（减少 API 调用） |

> 只要不填 `MQTT_HOST` 和 `HASS_URL`，即使 `ENABLE_HA_PUSH=true` 也不会推送。

### 将 Web 控制台嵌入 Home Assistant

通过 HA 的 **Webpage 仪表盘** 功能，可将 Web 控制台直接嵌入左侧菜单。详见 [面板集成指南](docs/HA_PANEL.md) 或 [快速指南](docs/QUICK_PANEL.md)。

---

## 安装部署

### 方式一：Home Assistant Add-on（推荐）

1. 进入 `设置` → `加载项` → `加载项商店`
2. 右上角 `...` → `仓库`，添加：`https://github.com/Poiig/sgcc_electricity`
3. 刷新页面，找到 **国家电网电费数据获取** 并安装
4. 切换到 `配置` 标签，填写手机号、密码
5. 配置推送方式：填写 `hass_url` + `hass_token`（REST API）或 `mqtt_host`（MQTT）
6. 保存配置，启动 Add-on

### 方式二：Docker Compose

```bash
mkdir sgcc_electricity && cd sgcc_electricity
curl -O https://raw.githubusercontent.com/Poiig/sgcc_electricity/master/docker-compose.yml
curl -O https://raw.githubusercontent.com/Poiig/sgcc_electricity/master/example.env
cp example.env .env && vim .env
docker compose up -d --force-recreate
```

**镜像地址：**

| 来源 | 地址 |
|------|------|
| GHCR | `ghcr.io/poiig/sgcc_electricity:latest` |
| GHCR 国内加速 | `ghcr.nju.edu.cn/poiig/sgcc_electricity:latest` |
| Docker Hub | `poiigzhao/sgcc_electricity:latest` |
| Docker Hub 国内加速 | `docker.1ms.run/poiigzhao/sgcc_electricity:latest` |

### 方式三：本地运行

详见 [本地开发指南](dev/LOCAL_DEV_GUIDE.md)

---

## 环境变量

Docker Compose 方式通过 `.env` 文件配置，完整配置项见 `example.env`。

**必填：**

| 变量 | 说明 |
|------|------|
| `PHONE_NUMBER` | 95598 登录手机号 |
| `PASSWORD` | 95598 登录密码 |

**Home Assistant 推送配置见 [Home Assistant 推送](#home-assistant-推送) 章节。**

**常用可选：**

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `JOB_START_TIME` | `09:30` | 每天同步开始时间（程序会在该时间及 +12 小时各执行一次） |
| `REPUBLISH_INTERVAL_MINUTES` | `10` | 从缓存重推 HA 传感器间隔（分钟），`0` 禁用；INFO 只报成功，明细需 `LOG_LEVEL=DEBUG` |
| `FETCH_FAIL_ALERT` | `true` | 连续多日抓取失败时推送企微告警（需 `WEWORK_WEBHOOK_URL`） |
| `FETCH_FAIL_ALERT_DAYS` | `2` | 连续失败自然日达到该天数后告警，告警含近期失败原因 |
| `FETCH_HEALTH_CHECK_TIME` | `22:30` | 日终巡检时刻：当天仍未成功则按阈值告警 |
| `RUN_ON_STARTUP` | `false` | Docker 启动后立即登录抓取 |
| `CAPTCHA_SOLVER` | `local` | 验证码识别（推荐 `llm`，详见下方说明） |
| `DB_TYPE` | sqlite | 数据库类型（sqlite / mysql / postgresql） |
| `LOGIN_METHOD` | password | 登录方式（password / qrcode） |
| `LOGIN_FALLBACK` | qrcode | 登录失败备选（qrcode / none） |
| `IGNORE_USER_ID` | 空 | 忽略的户号（逗号分隔） |
| `USER_NAMES` | 空 | 户号名称，如 `户号1:我家住宅,户号2:充电桩`；未配置时从国网网站获取。名称含「住宅」的户号才会抓取阶梯用电 |
| `WEB_DASHBOARD` | true | 启用 Web 控制台 |
| `PUSH_TYPE` | none | 通知方式（none / pushplus / urlpush / wework） |
| `DATA_RETENTION_DAYS` | 365 | 数据库记录保留天数，0 表示永久保留 |

---

## 数据库

| `DB_TYPE` | 说明 |
|-----------|------|
| `sqlite` | **默认**。本地文件，适合单机 / Docker 部署 |
| `mysql` | 连接外部 MySQL |
| `postgresql` | 连接外部 PostgreSQL |

启用数据库后程序自动建表，详见 [数据库表结构说明](docs/DATABASE.md)。

---

## 验证码识别

| 模式 | 配置值 | 说明 |
|------|--------|------|
| 大模型视觉识别（**推荐**） | `llm` | 火山引擎豆包大模型，识别率高，支持点选 + 滑块 |
| 本地 OCR | `local` | 免费，基于 ddddocr + 图像匹配，适合点选验证码，存在识别失败的情况 |

> **推荐使用 `llm` 模式**：本地 OCR 方案基于图像匹配，受验证码样式变化影响较大，存在识别失败的情况。大模型方式识别率更高且同时支持点选和滑块验证码。
>
> 两种方式的详细配置说明见 [验证码接入指南](docs/LLM_CAPTCHA.md)。如不想处理验证码，可直接使用 `LOGIN_METHOD=qrcode` 扫码登录。

---

## 常见问题

详见 [常见问题文档](docs/FAQ.md)，涵盖验证码识别、传感器数据、数据库选择、HA 集成等常见问题。

---

## License

[Apache License 2.0](LICENSE)
