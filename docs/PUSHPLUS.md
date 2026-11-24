# PushPlus 推送配置

通过 [PushPlus](https://www.pushplus.plus/) 发送**电费余额不足**提醒（微信 / 其他通道由 PushPlus 账号侧配置）。

本渠道当前仅用于余额提醒；同步汇总、抓取失败告警、登录二维码请使用 [企业微信](WEWORK.md)、[Bark](BARK.md) 或 [自定义 Webhook](WEBHOOK.md)。

---

## 快速配置

1. 打开 [pushplus.plus](https://www.pushplus.plus/) 登录并获取 **token**
2. 在 `.env` 中填写：

```env
PUSH_TYPE=pushplus
BALANCE=50
PUSHPLUS_TOKEN=your_token_here
```

3. 多接收人可将多个 token 用逗号拼接：

```env
PUSHPLUS_TOKEN=token1,token2
```

4. 重启后，当某户余额低于 `BALANCE` 时会 POST 到 PushPlus。

HA Add-on：`push_type=pushplus`，填写 `pushplus_token`。

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PUSH_TYPE` | `none` | 设为 `pushplus` |
| `BALANCE` | `10` | 余额低于该值（元）时提醒 |
| `PUSHPLUS_TOKEN` | — | **必填**。一个或多个 token（逗号分隔） |
| `PUSHPLUS_TITLE` | `电费余额不足提醒` | 通知标题 |
| `PUSHPLUS_CONTENT_TEMPLATE` | 见下方 | 正文模板 |
| `PUSHPLUS_TEMPLATE` | `html` | PushPlus 模板类型，如 `html` / `txt` / `json` / `markdown` |
| `PUSHPLUS_TOPIC` | 空 | 群组编码（一对多）；填写后按话题推送 |
| `PUSHPLUS_CHANNEL` | 空 | 发送渠道，留空用账号默认 |
| `PUSHPLUS_API` | `https://www.pushplus.plus/send` | API 地址，一般无需改 |
| `PUSH_TIMEOUT` | `10` | HTTP 超时秒数 |

### 正文模板占位符

`PUSHPLUS_CONTENT_TEMPLATE` 可用：`{label}`、`{user_id}`、`{user_name}`、`{balance}`。

默认：

```text
用户 {label} 的当前电费余额为：{balance}元，请及时充值。
```

---

## 请求说明

程序使用 **POST JSON** 调用 PushPlus（避免 GET 中文编码问题），字段包括 `token`、`title`、`content`、`template`，以及可选的 `topic`、`channel`。

---

## 排障

- 收不到：在 PushPlus 控制台查看发送记录；确认微信已关注对应公众号 / 通道已绑定
- `code` 非 200：检查 token 是否过期、`topic` 是否有权限
- 仅余额提醒触发：请确认当时余额确实低于 `BALANCE`（日志有「检查电费余额」一行）

更多接口说明见 [PushPlus 文档](https://www.pushplus.plus/doc/)。
