# 豆包大模型验证码识别

登录国家电网时可能遇到腾讯**点选**或**滑块**验证码。设置 `CAPTCHA_SOLVER=llm` 后，程序通过火山引擎豆包大模型的 OpenAI 兼容接口自动解算。

参考上游方案：[ARC-MX/sgcc_electricity_new](https://github.com/ARC-MX/sgcc_electricity_new)

---

## 快速配置

在 `.env` 或 HA Add-on 配置中填写：

```env
CAPTCHA_SOLVER=llm
LLM_API_KEY=your-api-key-here
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_MODEL=doubao-seed-2-0-pro-260215
```

重启后日志应显示：`验证码识别模式: LLM 大模型`

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_API_KEY` | — | **必填**。火山方舟 API Key |
| `LLM_BASE_URL` | `https://ark.cn-beijing.volces.com/api/v3` | OpenAI 兼容 API 地址 |
| `LLM_MODEL` | `doubao-seed-2-0-pro-260215` | 多模态视觉模型 |

---

## 注册与获取 API Key

### 1. 注册火山引擎账号

访问 [火山引擎官网](https://www.volcengine.com/)，使用手机号注册并完成**实名认证**（个人或企业均可）。

实名认证：<https://console.volcengine.com/user/authentication/detail/>

### 2. 开通豆包大模型

登录 [火山方舟控制台](https://console.volcengine.com/ark/)，进入 **在线推理** → **创建推理接入点**：

- 选择模型：**Doubao-Seed-2.0-pro-260215**（或其他支持视觉的多模态模型）
- 接入点 ID（如 `ep-2025xxxxxx-xxxxx`）供控制台查阅，程序默认按模型名调用

### 3. 创建 API Key

方舟控制台 → **API Key 管理** → **创建 API Key** → 复制 Key。

管理入口：<https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey>

---

## 使用的模型

默认调用 **`doubao-seed-2-0-pro-260215`**，具备多模态视觉能力：

- **点选验证码**：识别 3 个参考图标在网格大图中的位置，返回 JSON 坐标
- **滑块验证码**：识别背景图缺口位置，计算拖拽距离

程序将验证码图片以 data URI 形式发送给模型，单次 API 调用完成识别。

---

## 日志说明

大模型识别过程中会输出分步日志，便于排查耗时问题：

```
步骤 1/4: 下载参考图标条...
步骤 2/4: 拆分参考图标...
步骤 3/4: 下载主图并编码...
步骤 4/4: 调用大模型识别坐标...
正在请求大模型 API (JSON 模式): .../chat/completions, model=doubao-seed-2-0-pro-260215
大模型推理中，已等待 5s...
大模型推理中，已等待 10s...
大模型 API 响应完成 (62.3s)
大模型响应: {"coords":[[0.17, 0.41],[0.05, 0.42],[0.53, 0.74]]}
```

豆包视觉推理通常需要 **30~90 秒**，等待期间每 5 秒会输出心跳日志，属正常现象。

---

## 费用说明

豆包系列模型按 token 计费，每次验证码解算消耗约数百 token。新用户注册通常有免费额度，个人家庭使用基本免费。

详见 [火山引擎官方定价](https://www.volcengine.com/docs/82379/1099320)。

---

## 注意事项

- **API Key 勿泄露**，不要提交到 Git 或公开渠道
- 国网每天有**登录次数限制**，验证码识别成功也可能因超限无法登录（RK001），请勿频繁重启测试
- 大模型**仅用于验证码识别**，不影响用电量、电费等其他数据抓取逻辑
- 本地 OCR 无法满足时切换 `CAPTCHA_SOLVER=llm`；也可使用 `LOGIN_METHOD=qrcode` 扫码登录绕过验证码

---

## Home Assistant Add-on

在加载项配置页设置：

| 配置项 | 说明 |
|--------|------|
| `captcha_solver` | 选择 `llm` |
| `llm_api_key` | 火山方舟 API Key |

模型与 API 地址使用程序内置默认值，一般无需修改。
