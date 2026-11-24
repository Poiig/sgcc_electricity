# 企业微信推送配置

通过企业微信**群机器人 Webhook** 发送余额不足提醒、同步汇总、抓取失败告警，以及登录二维码（文字 + 图片）。

---

## 快速配置

1. 企业微信群 → 右上角 `...` → 添加群机器人 → 复制 Webhook 地址  
2. 在 `.env` 中填写：

```env
PUSH_TYPE=wework
BALANCE=50
WEWORK_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=your-key
WEWORK_PUSH_SUMMARY=true
```

3. 重启后即可接收通知。

HA Add-on：`push_type=wework`，填写 `wework_webhook_url`。

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PUSH_TYPE` | `none` | 设为 `wework` 启用余额提醒与汇总 |
| `BALANCE` | `10` | 余额低于该值（元）时提醒 |
| `WEWORK_WEBHOOK_URL` | — | **必填**。群机器人 Webhook |
| `WEWORK_PUSH_SUMMARY` | `true` | 抓取成功后推送各户号汇总 |
| `FETCH_FAIL_ALERT` | `true` | 连续多日失败时告警（有 Webhook 即可，不强制 `PUSH_TYPE=wework`） |
| `FETCH_FAIL_ALERT_DAYS` | `2` | 连续失败自然日阈值 |
| `FETCH_HEALTH_CHECK_TIME` | `22:30` | 日终巡检时刻 |
| `PUSH_TIMEOUT` | `10` | HTTP 超时秒数 |

---

## 能力对照

| 能力 | 是否支持 | 说明 |
|------|----------|------|
| 余额不足 | ✅ | markdown 卡片 |
| 同步汇总 | ✅ | `WEWORK_PUSH_SUMMARY` |
| 抓取失败告警 | ✅ | 配置了 `WEWORK_WEBHOOK_URL` 即会发 |
| 扫码文字 + 二维码图片 | ✅ | image 消息类型 |

---

## 安全说明

- Webhook URL 含密钥，勿提交到公开仓库；Web 控制台编辑 `.env` 时会掩码显示
- 群机器人有频率限制，汇总与告警请避免过短周期反复触发

官方说明：[群机器人配置](https://developer.work.weixin.qq.com/document/path/91770)
