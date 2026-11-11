# 数据库表结构

启用数据库（`DB_TYPE=sqlite` / `mysql` / `postgresql`）后，程序自动创建以下表。

> 所有表均包含 `user_id` 和 `user_name` 字段。`user_name` 优先取自 `USER_NAMES` 自定义配置，未配置时从国网网站获取，并在每次更新时自动补充。

---

## `users` — 用户户号信息

| 字段 | 类型 | 说明 |
|------|------|------|
| user_id | TEXT | 用户户号（主键） |
| phone_number | TEXT | 登录手机号 |
| user_name | TEXT | 用户名（`USER_NAMES` 优先，否则从网站获取） |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

---

## `daily_usage` — 每日用电量（含分时）

主键：`(user_id, date)`

| 字段 | 类型 | 说明 |
|------|------|------|
| user_id | TEXT | 用户户号 |
| user_name | TEXT | 用户名 |
| date | TEXT | 日期（YYYY-MM-DD） |
| total_usage | REAL | 总用电量（kWh） |
| valley_usage | REAL | 谷时用电量（kWh） |
| flat_usage | REAL | 平时用电量（kWh） |
| peak_usage | REAL | 峰时用电量（kWh） |
| tip_usage | REAL | 尖时用电量（kWh） |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

---

## `monthly_usage` — 月度用电量（含分时和电费）

主键：`(user_id, month)`

| 字段 | 类型 | 说明 |
|------|------|------|
| user_id | TEXT | 用户户号 |
| user_name | TEXT | 用户名 |
| month | TEXT | 月份（YYYY-MM） |
| total_usage | REAL | 总用电量（kWh） |
| total_charge | REAL | 总电费（CNY） |
| valley_usage | REAL | 谷时用电量（kWh） |
| flat_usage | REAL | 平时用电量（kWh） |
| peak_usage | REAL | 峰时用电量（kWh） |
| tip_usage | REAL | 尖时用电量（kWh） |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

---

## `yearly_usage` — 年度用电量汇总

主键：`(user_id, year)`

| 字段 | 类型 | 说明 |
|------|------|------|
| user_id | TEXT | 用户户号 |
| user_name | TEXT | 用户名 |
| year | TEXT | 年份（YYYY） |
| total_usage | REAL | 总用电量（kWh） |
| total_charge | REAL | 总电费（CNY） |
| valley_usage | REAL | 谷时用电量（kWh） |
| flat_usage | REAL | 平时用电量（kWh） |
| peak_usage | REAL | 峰时用电量（kWh） |
| tip_usage | REAL | 尖时用电量（kWh） |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

---

## `balance_log` — 电费余额日志

主键：`(user_id, as_of)`

每次同步成功后会写入/更新此表。Web 控制台「运行日志」Tab 展示最近的 `balance_log` 记录，用于查看各户号余额同步历史。

| 字段 | 类型 | 说明 |
|------|------|------|
| user_id | TEXT | 用户户号 |
| user_name | TEXT | 用户名 |
| as_of | TEXT | 记录日期（YYYY-MM-DD，按天去重） |
| balance | REAL | 电费余额（CNY） |
| amount_due | REAL | 应交金额（CNY） |
| created_at | DATETIME | 创建时间 |

---

## `step_usage` — 阶梯用电量

> 仅显示名称含「住宅」的户号有阶梯用电数据；充电桩等无阶梯信息。网站户名不含「住宅」时，可用 `USER_NAMES` 自定义名称启用。

主键：`(user_id, year_month)` — **每个户号每月一条记录**。同步时 `year_month` 取当前自然月（`YYYY-MM`），同月内多次同步更新同一行；跨月后写入新行，旧月数据保留作历史。

**Web 控制台展示**：国网阶梯页通常滞后于自然月（例如 6 月仍显示 5 月统计）。`dashboard_db` 会在 API 返回时，将统计截止月之后各月的 `daily_usage` / `monthly_usage` 叠加到阶梯快照上，用于饼图与已用/剩余展示（不回写数据库）。

| 字段 | 类型 | 说明 |
|------|------|------|
| user_id | TEXT | 用户户号 |
| user_name | TEXT | 用户名 |
| year_month | TEXT | 年月（YYYY-MM） |
| used_step1 | REAL | 已用一阶电量（kWh） |
| remain_step1 | REAL | 剩余一阶电量（kWh） |
| used_step2 | REAL | 已用二阶电量（kWh） |
| remain_step2 | REAL | 剩余二阶电量（kWh） |
| used_step3 | REAL | 已用三阶电量（kWh） |
| total_usage | REAL | 累计用电量（kWh） |
| step_stage | INTEGER | 当前阶梯阶段（1/2/3） |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

---

## `payment_records` — 交费记录

主键：`(user_id, pay_date, rcv_amt, type_code, pay_mode)` — **同一缴费事件去重**；重复同步 `INSERT OR IGNORE` / `ON CONFLICT DO NOTHING`，不覆盖已有行。

抓取页：`https://95598.cn/osgweb/paymentRecord`（与登录同域，勿用 www）。进页后点「最近1年」，再按分页依次拉取；若库中已有该户最新 `pay_date`，列表倒序翻到不新于该时间的页即停止（增量）。

| 字段 | 类型 | 说明 |
|------|------|------|
| user_id | TEXT | 用户户号 |
| user_name | TEXT | 用户名 |
| pay_date | TEXT | 缴费时间（如 `2026-11-02 14:19:01`） |
| ymd | TEXT | 缴费日（YYYY-MM-DD） |
| ym | TEXT | 缴费月（YYYY-MM） |
| rcv_amt | REAL | 缴费金额（元） |
| pay_mode | TEXT | 缴费方式码 |
| pay_mode_name | TEXT | 缴费类型文案（如「社会网点交费」） |
| type_code | TEXT | 业务类型码（如 `0101` 收电费 / `0103` 收预收费） |
| type_name | TEXT | 业务类型名 |
| chan_cls | TEXT | 渠道分类（支付宝 / 网上国网） |
| chan_name | TEXT | 渠道明细 |
| remark | TEXT | 备注 |
| cons_no | TEXT | 户号 |
| cons_name | TEXT | 户名 |
| penalty | TEXT | 违约金（原文） |
| created_at | DATETIME | 入库时间 |

Web 控制台「交费记录」Tab：全户合计、分户卡片、月度堆叠柱图、渠道占比与明细表（`GET /api/payments/report`）。

---

通过 `DATA_RETENTION_DAYS` 环境变量控制数据保留天数（默认 365 天），自动清理过期的日用电、余额和交费记录。
`IGNORE_USER_ID` 中配置的户号仅跳过本次抓取，不会删除数据库中的历史数据。
