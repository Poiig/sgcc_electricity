# 快速集成到 Home Assistant 界面

> Home Assistant 2024.4+ 已移除 `panel_iframe`，不再支持 YAML 配置。请按以下步骤通过 UI 操作。

## 3 步完成

### 1. 打开仪表盘管理

点击 **设置** → **仪表盘** → 右下角 **添加仪表盘**

### 2. 创建 Webpage 仪表盘

选择 **Webpage（网页）**，填写：

- **名称**：`国家电网电费数据`
- **图标**：`mdi:lightning-bolt`
- **URL**：见下方选择

### 3. 完成

左侧菜单底部出现「国家电网电费数据」入口，点击即可全屏访问。

## URL 怎么填

### HA 是 HTTP 访问（纯内网）

直接填内网地址即可：

```
http://192.168.1.100:8080
```

### HA 是 HTTPS 访问（公网 / Nginx 反代）

**不能直接填 `http://` 地址**，浏览器会阻止。需要通过 Nginx 反向代理解决。

在 HA 的 Nginx 配置中添加一个 location：

```nginx
location /sgcc/ {
    proxy_pass http://192.168.1.100:8080/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

> 请将 IP 和端口替换为你自己的实际地址。

重载 Nginx（`nginx -t && nginx -s reload`），然后 URL 填：

```
https://你的HA域名:端口/sgcc/
```

> 详细说明见 [HA_PANEL.md](HA_PANEL.md)。

## 如果你之前配置了 panel_iframe（报错修复）

出现 `Integration 'panel_iframe' not found` 是因为新版本已移除该集成。

**修复步骤**：

1. 编辑 `configuration.yaml`，删除所有 `panel_iframe:` 相关内容
2. 重启 Home Assistant（旧配置会自动迁移）
3. 如未自动迁移，按上面 3 步手动创建
