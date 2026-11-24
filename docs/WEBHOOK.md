# 自定义 Webhook 推送配置

`PUSH_TYPE=urlpush` 时，程序向你自建的 HTTP 接口 **POST JSON**，用于余额不足提醒；另可用 `PUSH_QRCODE_URL` 接收登录二维码图片（与 `PUSH_TYPE` 无关，扫码流程触发时发送）。

适合对接 n8n、飞书自定义机器人中转、自建通知网关等。

---

## 余额提醒（urlpush）

### 快速配置

```env
PUSH_TYPE=urlpush
BALANCE=50
PUSH_URL=http://192.168.1.10:5678/webhook/sgcc-balance
```

HA Add-on：`push_type=urlpush`，填写 `push_url`。

### 请求格式

- **方法**：`POST`
- **Content-Type**：`application/json`
- **超时**：`PUSH_TIMEOUT`（默认 10 秒）
- **成功判定**：HTTP 状态码 `200`

Body 示例：

```json
{
  "user_id": "1234567890123",
  "user_name": "我家住宅",
  "balance": 12.34,
  "threshold": 50.0,
  "title": "电费余额不足提醒"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `user_id` | string | 户号 |
| `user_name` | string | 户名（可能为空） |
| `balance` | number | 当前余额（元） |
| `threshold` | number | 触发阈值，即 `BALANCE` |
| `title` | string | 固定标题文案 |

仅当 `balance < BALANCE` 时才会请求。

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PUSH_TYPE` | `none` | 设为 `urlpush` |
| `BALANCE` | `10` | 余额阈值（元） |
| `PUSH_URL` | — | **必填**。接收余额 JSON 的 URL |
| `PUSH_TIMEOUT` | `10` | HTTP 超时秒数 |

---

## 登录二维码 {#登录二维码}

扫码登录（`LOGIN_METHOD=qrcode` 或密码失败后 `LOGIN_FALLBACK=qrcode`）拿到二维码图后，若配置了 `PUSH_QRCODE_URL`，会以 **multipart/form-data** 上传：

| 项 | 值 |
|----|-----|
| 字段名 | `file` |
| 文件名 | `qrcode.png` |
| MIME | `image/png` |

```env
PUSH_QRCODE_URL=http://192.168.1.10:5678/webhook/sgcc-qrcode
```

说明：

- `PUSH_TYPE=wework` 时优先走企微发图，可不配本项
- `PUSH_TYPE=bark` 时 Bark 只发文字，图片仍依赖本项或 Web 控制台
- 接口需返回 HTTP `200` 视为成功

---

## 对接示例（n8n / 任意 HTTP）

1. 新建 Webhook 节点，复制 Production URL 填入 `PUSH_URL`
2. 下游用表达式读取 `{{ $json.user_id }}`、`{{ $json.balance }}` 再转发到 Telegram / 邮件等
3. 二维码另建一个 Webhook，接收 binary `file` 后转发

---

## 排障

- 日志出现 `PUSH_URL 未配置`：检查环境变量名是否为 `PUSH_URL`
- `URL 推送 HTTP 失败`：看对端状态码与响应体；需返回 200
- 内网 Docker 访问宿主机：Linux 常用 `http://172.17.0.1:...`，macOS Docker Desktop 可用 `http://host.docker.internal:...`
