# 国家电网电费数据获取 - Home Assistant Add-on

将国家电网 95598 的电费、用电量、分时电量数据同步到 Home Assistant（支持 REST API 和 MQTT Discovery）。

## 使用前准备

- 一个可登录的国家电网 95598 账号，并且已经绑定户号
- Home Assistant 已生成长期访问令牌（个人资料页底部创建）或已启用 MQTT 集成

## 安装

1. Home Assistant 进入 `设置` → `加载项` → `加载项商店`
2. 右上角 `...` → `仓库`，添加：

```text
https://github.com/Poiig/sgcc_electricity
```

3. 找到 `国家电网电费数据获取` 并安装
4. 在 `配置` 页面填写账号、密码
5. 配置推送方式：填写 `hass_url` + `hass_token`（REST API）或 `mqtt_host`（MQTT）
6. 启动 add-on，查看日志确认运行状态

## 配置项

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| phone_number | 95598 登录手机号 | 必填 |
| password | 95598 登录密码 | 必填 |
| hass_url | Home Assistant 地址（REST API 方式） | `http://homeassistant:8123/` |
| hass_token | HA 长期访问令牌（REST API 方式） | 选填 |
| mqtt_host | MQTT Broker 地址（MQTT 方式） | 选填 |
| mqtt_port | MQTT 端口 | 1883 |
| job_start_time | 每天同步开始时间 | `07:00` |
| republish_interval_minutes | 缓存重推 HA 间隔（分钟，0=禁用） | `10` |
| fetch_fail_alert | 连续多日抓取失败推送企微告警 | `true` |
| fetch_fail_alert_days | 连续失败天数阈值 | `2` |
| fetch_health_check_time | 日终健康巡检时间 | `22:30` |
| db_type | 数据库类型（sqlite / mysql / postgresql） | sqlite |
| data_retention_days | 数据保留天数 | 365 |
| daily_fetch_days | 每日获取天数 | 7 |
| login_fallback | 登录失败备选 | qrcode |

完整配置项在 add-on 配置页面中都有说明。

## Web 控制台

Add-on 默认启用 Web 控制台，可通过 `http://homeassistant.local:8080` 访问，查看运行日志、户号数据、图表，并支持手动触发同步。

### 集成到 Home Assistant 界面

通过 HA 的 **Webpage 仪表盘** 功能，可将 Web 控制台嵌入左侧菜单：

1. **设置** → **仪表盘** → **添加仪表盘**
2. 选择 **Webpage（网页）**
3. 名称填 `国家电网电费数据`，图标选 `mdi:lightning-bolt`
4. URL 填写 Web 控制台地址（纯内网用 `http://内网IP:8080`）
5. 创建后左侧菜单即可看到入口

> **注意**：如果 HA 通过 HTTPS（公网 / Nginx 反代）访问，需要通过 Nginx 反代 Web 控制台使其也走 HTTPS，否则浏览器会阻止加载。详见 [面板集成指南](../../docs/HA_PANEL.md)。

## 说明

- **REST API 方式**：需要在 `configuration.yaml` 中配置 template 实体，详见 [REST API 配置指南](../../docs/HA_CONFIG.md)
- **MQTT 方式**（推荐）：实体自动创建，无需手动配置，详见 [MQTT 使用指南](../../docs/MQTT.md)
