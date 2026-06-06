# Home Assistant 面板集成指南

将 Web 控制台直接嵌入到 Home Assistant 左侧菜单中，点击即可全屏访问。

## 配置方法（推荐：Webpage 仪表盘）

Home Assistant 2024.4+ 已移除 `panel_iframe` YAML 配置，改用 **Webpage 仪表盘**。通过 UI 操作即可完成，无需编辑 YAML。

### 配置步骤

#### 1. 打开仪表盘管理页面

在 Home Assistant 中：

1. 进入 **设置** → **仪表盘**
2. 点击右下角 **添加仪表盘**

#### 2. 创建 Webpage 仪表盘

1. 选择 **Webpage（网页）**
2. 填写配置：

| 字段 | 值 |
|------|-----|
| 名称 | `国家电网电费数据` |
| 图标 | `mdi:lightning-bolt` |
| URL | 见下方 URL 地址选择 |

3. 点击 **创建**

#### 3. 完成

创建后，左侧菜单底部会出现「国家电网电费数据」入口，点击即可全屏访问 Web 控制台。

```
┌─────────────────────────────┐
│ Home Assistant              │
├─────────────────────────────┤
│ Overview                    │
│ Dashboard                   │
│ Settings                    │
├─────────────────────────────┤
│ 国家电网电费数据             │  ← 新增入口
└─────────────────────────────┘
```

## URL 地址选择

根据你的 HA 访问方式选择正确的 URL：

### 场景一：纯内网访问（HA 用 HTTP）

HA 地址形如 `http://192.168.x.x:8123`，无 HTTPS。

| 部署方式 | URL |
|---------|-----|
| Docker Compose（同网络） | `http://容器名:8080` |
| Docker Compose（同主机） | `http://host.docker.internal:8080` |
| Add-on | `http://homeassistant.local:8080` |
| 同局域网 | `http://内网IP:8080` |

### 场景二：HA 通过 HTTPS 访问（公网 / Nginx 反代）

**如果 HA 使用 HTTPS，浏览器会阻止加载 HTTP 的 iframe（混合内容限制）。** 必须让 Web 控制台也走 HTTPS。

有两种解决方案：

#### 方案 A：通过 Nginx 反向代理 Web 控制台（推荐）

在 HA 的 Nginx 配置中增加一个 location，将 Web 控制台也通过 HTTPS 提供。

假设 HA 地址为 `https://ha.example.com:8888`，Web 控制台在内网 `192.168.1.100:8080`：

```nginx
server {
    listen 8888 ssl;
    server_name ha.example.com;

    # 已有的 HA 代理配置
    location / {
        proxy_pass http://192.168.1.100:8123;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # 新增：代理 Web 控制台
    location /sgcc/ {
        proxy_pass http://192.168.1.100:8080/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

> 请将 `ha.example.com`、`192.168.1.100`、端口号等替换为你自己的实际地址。

重载 Nginx 后：

```bash
nginx -t && nginx -s reload
```

然后在 HA 中创建 Webpage 仪表盘，URL 填写：

```
https://ha.example.com:8888/sgcc/
```

这样 Web 控制台和 HA 走同一个 HTTPS 域名，浏览器不会阻止。

#### 方案 B：给 Web 控制台单独配置 HTTPS

如果你有多个域名或通配符证书，可以为 Web 控制台配置独立的 HTTPS：

```nginx
server {
    listen 443 ssl;
    server_name sgcc.example.com;

    ssl_certificate     /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://192.168.1.100:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

URL 填写：`https://sgcc.example.com`

## 方法二：使用 iframe 卡片嵌入到现有仪表盘

如果你想在现有仪表盘页面中嵌入 Web 控制台，可以使用 iframe 卡片：

1. 进入要编辑的仪表盘页面
2. 点击右上角三点菜单 → **编辑仪表盘**
3. 点击 **添加卡片**
4. 选择 **iframe** 卡片
5. 填写 URL（同样需要满足 HTTPS 要求）
6. 保存

> **注意**：iframe 卡片同样受 HTTPS 混合内容限制。如果 HA 是 HTTPS，iframe 的 URL 也必须是 HTTPS。

## 安全性

### 设置 Web 控制台密码

在 `.env` 或 Add-on 配置中设置密码：

```env
WEB_DASHBOARD_PASSWORD=your_secure_password
```

### 限制仪表盘可见性

创建 Webpage 仪表盘时可以设置为仅管理员可见，避免其他用户看到。

## 故障排查

### 问题 1：无法加载 iframe（HTTP / HTTPS 混合内容）

**症状**：浏览器控制台报错 `Blocked loading mixed active content`，页面空白

**原因**：HA 通过 HTTPS 访问，但 Web 控制台 URL 是 HTTP。浏览器安全策略阻止在 HTTPS 页面中嵌入 HTTP 内容。

**解决方案**：
1. **推荐**：通过 Nginx 反向代理 Web 控制台，使其也通过 HTTPS 访问（见上方「方案 A」）
2. 如果只是内网使用且不在乎安全警告，可以用 HTTP 直接访问 HA（`http://内网IP:8123`），不走 Nginx

### 问题 2：无法访问 Web 控制台

**症状**：点击菜单项后显示空白或无法连接

**解决方案**：
1. 确认 Web 控制台服务是否运行：直接在浏览器访问 `http://内网IP:8080`
2. 检查 Docker 端口映射是否正确：`8080:8080`
3. 确认 URL 地址是否正确
4. 检查防火墙设置

### 问题 3：Nginx 反代后页面样式异常

**症状**：页面能加载但样式错乱或 API 请求 404

**解决方案**：

确保 `proxy_pass` 末尾有斜杠：

```nginx
# 正确
location /sgcc/ {
    proxy_pass http://192.168.1.100:8080/;
}

# 错误（缺少斜杠会导致路径拼接问题）
location /sgcc/ {
    proxy_pass http://192.168.1.100:8080;
}
```

### 问题 4：panel_iframe 报错

**症状**：`Integration 'panel_iframe' not found`

**解决方案**：

这是 Home Assistant 2024.4+ 的正常行为。`panel_iframe` 已被移除，请使用上方介绍的 **Webpage 仪表盘** 方法：

1. 从 `configuration.yaml` 中删除所有 `panel_iframe:` 相关配置
2. 重启 Home Assistant
3. 按上方「配置步骤」通过 UI 创建 Webpage 仪表盘

## 移动端

Web 控制台支持移动端访问：

1. 使用 Home Assistant Companion App 访问效果最佳
2. 仪表盘入口会自动出现在 App 侧边栏
3. 横屏查看图表效果更好
