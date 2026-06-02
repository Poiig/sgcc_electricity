# Web 控制台



浏览器可视化查看运行日志、各户号用电数据与图表，并支持手动触发同步。



## 访问地址



| 环境 | 地址 |

|------|------|

| Docker | `http://<主机IP>:8080/` |

| 本地 | `http://127.0.0.1:8080/` |



打开后需先**登录**（默认密码 `password`，请在 `.env` 中修改）。



## 功能



- **登录**：`WEB_DASHBOARD_PASSWORD`（默认 `password`）

- **监控**：户号概览、日用电+分时组合图、阶梯用电与月用电并排、仅读数据库

- **运行日志**：数据库 `balance_log` 余额同步记录 + `app.log`

- **环境配置**：Web 页编辑 `.env`

- **立即同步**：后台启动 `run_fetch_once.py`



> 报表数据全部来自数据库。`DB_TYPE=none` 时页面会提示并隐藏图表。



## 配置



```env

WEB_DASHBOARD=true

WEB_DASHBOARD_PORT=8080

WEB_DASHBOARD_PASSWORD=password

FETCH_COOLDOWN_MINUTES=30

DB_TYPE=mysql

```



## 数据来源



| 数据 | 来源 |

|------|------|

| 户号 / 日 / 月 / 年 / 余额 / 阶梯 | SQLite / MySQL |

| 运行记录 | `balance_log`（按户号分组，每户最近 5 条，时间为同步完成 `created_at`） |

| 应用日志 | `data/app.log` |

