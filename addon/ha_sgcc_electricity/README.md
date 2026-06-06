# 国家电网电费数据获取 - Home Assistant Add-on

将国家电网 95598 的电费、用电量、分时电量数据通过 REST API 同步到 Home Assistant。

## 使用前准备

- 一个可登录的国家电网 95598 账号，并且已经绑定户号
- Home Assistant 已生成长期访问令牌（个人资料页底部创建）

## 安装

1. Home Assistant 进入 `设置` → `加载项` → `加载项商店`
2. 右上角 `...` → `仓库`，添加：

```text
https://github.com/Poiig/ha_sgcc_electricity
```

3. 找到 `国家电网电费数据获取` 并安装
4. 在 `配置` 页面填写账号、密码和 Home Assistant 信息
5. 启动 add-on，查看日志确认运行状态

## 配置项

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| phone_number | 95598 登录手机号 | 必填 |
| password | 95598 登录密码 | 必填 |
| hass_url | Home Assistant 地址 | `http://homeassistant:8123/` |
| hass_token | HA 长期访问令牌 | 必填 |
| job_start_time | 每天同步开始时间 | `07:00` |
| db_type | 数据库类型 | sqlite |
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

本 add-on 通过 REST API 将数据推送到 Home Assistant，需要在 `configuration.yaml` 中配置 template 实体。详见主项目 README。
