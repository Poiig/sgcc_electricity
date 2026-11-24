# iOS Bark 推送配置

通过 [Bark](https://github.com/Finb/Bark) 将**余额不足提醒**、**同步汇总**、**抓取失败告警**、**扫码登录文字提醒**推送到 iPhone。

Bark 官方推送 API 不支持图片附件；登录二维码图片请另配 [`PUSH_QRCODE_URL`](WEBHOOK.md#登录二维码) 或使用 [企业微信](WEWORK.md)。

---

## 快速配置

1. App Store 安装 **Bark**，打开后复制推送 URL（形如 `https://api.day.app/xxxxxxxx`）
2. 在 `.env` 中填写：

```env
PUSH_TYPE=bark
BALANCE=50
BARK_KEY=xxxxxxxx
# 或直接填完整 URL：
# BARK_KEY=https://api.day.app/xxxxxxxx
```

3. 重启容器 / Add-on。余额低于 `BALANCE` 时应收到推送。

HA Add-on：配置页将 `push_type` 设为 `bark`，填写 `bark_key`（及可选的 `bark_server` / `bark_group` / `bark_sound` / `bark_level`）。

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PUSH_TYPE` | `none` | 设为 `bark` 启用本渠道 |
| `BALANCE` | `10` | 余额低于该值（元）时发送不足提醒 |
| `BARK_KEY` | — | **必填**。device_key；多个用逗号分隔；也可填完整推送 URL |
| `BARK_SERVER` | `https://api.day.app` | 自建 [bark-server](https://github.com/Finb/bark-server) 时改成你的地址（不含末尾 key） |
| `BARK_GROUP` | 空 | 通知分组，便于在 App 内按组查看 |
| `BARK_SOUND` | 空 | 铃声名，见 [Bark 参数说明](https://github.com/Finb/Bark/blob/master/docs/en-us/tutorial.md) |
| `BARK_ICON` | 空 | 自定义图标 URL（iOS 15+） |
| `BARK_LEVEL` | 空 | `active` / `timeSensitive` / `passive` / `critical` |
| `BARK_CLICK_URL` | 空 | 点击通知后跳转的 URL（如 Web 控制台地址） |
| `BARK_TITLE` | `电费余额不足提醒` | 余额提醒标题 |
| `BARK_BODY_TEMPLATE` | 见下方 | 余额提醒正文模板 |
| `BARK_PUSH_SUMMARY` | `true` | 抓取成功后是否推送户号汇总 |
| `BARK_SUMMARY_TITLE` | `国家电网数据同步完成` | 汇总通知标题 |
| `BARK_CALL` | `false` | `true` 时铃声持续约 30 秒 |
| `BARK_AUTO_COPY` | `false` | `true` 时自动复制 `BARK_COPY` |
| `BARK_COPY` | 空 | 可复制内容 |
| `BARK_IS_ARCHIVE` | `false` | `true` 时归档保存 |
| `BARK_BADGE` | 空 | App 角标数字 |
| `BARK_VOLUME` | 空 | `critical` 等级时的音量 |
| `PUSH_TIMEOUT` | `10` | HTTP 超时秒数 |

### 正文模板占位符

`BARK_BODY_TEMPLATE` 可用：

| 占位符 | 含义 |
|--------|------|
| `{label}` | 户名（户号），如 `我家（1234…）` |
| `{user_id}` | 户号 |
| `{user_name}` | 户名 |
| `{balance}` | 当前余额 |
| `{threshold}` | `BALANCE` 阈值 |

默认正文：

```text
户名：{label}
当前余额：{balance} 元
提醒阈值：{threshold} 元
请及时充值。
```

---

## 自建 Server

```env
PUSH_TYPE=bark
BARK_SERVER=https://bark.example.com
BARK_KEY=your_device_key
```

若 `BARK_KEY` 已是完整 URL（含 server 与 key），则不再使用 `BARK_SERVER`。

---

## 能力对照

| 能力 | 是否支持 | 说明 |
|------|----------|------|
| 余额不足 | ✅ | `BALANCE` 阈值 |
| 同步汇总 | ✅ | `BARK_PUSH_SUMMARY` |
| 抓取失败告警 | ✅ | 需 `FETCH_FAIL_ALERT=true` |
| 扫码文字提醒 | ✅ | 提示去 Web 控制台或自定义 URL |
| 二维码图片 | ❌ | 请配 `PUSH_QRCODE_URL` 或企微 |

---

## 排障

- 收不到推送：确认 `PUSH_TYPE=bark`、`BARK_KEY` 正确，手机 Bark 允许通知；自建 server 检查 HTTPS 与网络
- 多设备：`BARK_KEY=key1,key2` 或写多个完整 URL（逗号分隔）
- 关键模式收不到：将 `BARK_LEVEL=timeSensitive` 或 `critical`（critical 需系统权限）

官方文档：[Bark 教程](https://github.com/Finb/Bark) · [API V2](https://github.com/Finb/bark-server/blob/master/docs/API_V2.md)
