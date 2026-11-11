# 本地开发

本目录包含**本地开发/调试**用的脚本与文档，不影响 Docker 生产部署。

## Web 控制台（只读数据库）

让浏览器中的 dashboard 通过 API 读取 `.env` 所配置的数据库。

> 不要直接双击 `scripts/static/dashboard/index.html`，须通过 `http://127.0.0.1:8080/` 访问。

### 1. 安装依赖

```bash
pip install -r dev/requirements-dashboard.txt
```

`requirements-dashboard.txt` 仅含 ASCII 注释，避免 Windows 下 pip 编码错误。

### 2. 配置 `.env`

至少配置 `DB_TYPE` 及对应连接（SQLite / MySQL / PostgreSQL），示例见项目根目录 `example.env`。

### 3. 启动

**Windows**

```powershell
.\dev\run_dashboard.ps1
```

**macOS / Linux**

```bash
chmod +x dev/run_dashboard.sh
./dev/run_dashboard.sh
```

浏览器打开 **http://127.0.0.1:8080/**。

### 常见问题

| 现象 | 处理 |
|------|------|
| pip 安装失败 | 确认使用 `dev/requirements-dashboard.txt`，勿含中文注释 |
| 数据库连接失败 | 检查 `.env` 中 `DB_TYPE` 与连接参数 |
| 阶梯饼图不显示 | 确认 `step_usage` 表有该户号记录；电动车/充电桩户不展示 |
| 户号列表为空 | 需先执行一次国网数据同步 |

## 完整本地开发（含浏览器抓取）

见 [LOCAL_DEV_GUIDE.md](./LOCAL_DEV_GUIDE.md)。

## 仅测交费记录

```powershell
cd scripts
python run_fetch_payment.py
```

详见 [LOCAL_DEV_GUIDE.md §9](./LOCAL_DEV_GUIDE.md)。浏览器 Console 调试脚本：`dump_payment_list.js` / `dump_vue_state.js`。

## 生产环境 Web 控制台

见 [docs/WEB_DASHBOARD.md](../docs/WEB_DASHBOARD.md)。
