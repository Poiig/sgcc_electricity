"""MQTT 传感器更新器，通过 MQTT Discovery 协议自动创建和更新 Home Assistant 实体。"""
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from mqtt_discovery import MQTTDiscoveryClient
from const import *


class MQTTSensorUpdator:

    def __init__(self):
        self.mqtt_client = MQTTDiscoveryClient()
        # 缓存重推时为 True：传感器数值等详情只打 DEBUG，INFO 只保留成功摘要
        self._quiet = False
        self._init_balance_notify()

    def _init_balance_notify(self):
        push_type = os.getenv("PUSH_TYPE", "None").strip().lower()
        if push_type == "pushplus":
            from notify import PushplusNotify
            self.balance_notify = PushplusNotify()
        elif push_type == "urlpush":
            from notify import UrlPushNotify
            self.balance_notify = UrlPushNotify()
        elif push_type == "wework":
            from notify import WeworkNotify
            self.balance_notify = WeworkNotify()
        else:
            self.balance_notify = None

    def _detail(self, msg: str, *args) -> None:
        """传感器数值等明细日志：缓存重推时降为 DEBUG，正式抓取仍为 INFO。"""
        if self._quiet:
            logging.debug(msg, *args)
        else:
            logging.info(msg, *args)

    @staticmethod
    def _sensor_name(base: str, postfix: str) -> str:
        return base + postfix

    @staticmethod
    def _sensor_label(base: str) -> str:
        return SENSOR_LABELS.get(base, base)

    def _log_skip(self, base: str, postfix: str):
        name = self._sensor_name(base, postfix)
        label = self._sensor_label(base)
        self._detail("跳过更新 %s 【%s】，状态一致", label, name)

    def _log_updated(self, base: str, postfix: str, value, unit: str):
        name = self._sensor_name(base, postfix)
        label = self._sensor_label(base)
        self._detail("%s 【%s】 已更新: %s %s", label, name, value, unit)

    def _publish_sensor(
        self,
        sensor_name: str,
        label: str,
        state,
        unit: str,
        device_class: str,
        state_class: str,
        user_id: str,
        user_name: str = "",
        icon: str = None,
        last_reset: str = None,
        attributes: dict = None,
    ) -> bool:
        """发送发现配置和状态值。"""
        if not self.mqtt_client.mqtt_host:
            return False

        self.mqtt_client.publish_sensor_discovery(
            entity_id=sensor_name,
            name=label,
            unit=unit,
            device_class=device_class,
            state_class=state_class,
            user_id=user_id,
            user_name=user_name,
            icon=icon,
            last_reset=last_reset,
            attributes=attributes,
        )

        # 合并 last_reset 到 attributes
        state_attrs = dict(attributes) if attributes else {}
        if last_reset:
            state_attrs["last_reset"] = last_reset

        return self.mqtt_client.publish_sensor_state(
            sensor_name, state, state_attrs if state_attrs else None
        )

    def update_one_userid(
        self,
        user_id: str,
        balance: float,
        last_daily_date: str,
        last_daily_usage: float,
        yearly_charge: float,
        yearly_usage: float,
        month_charge: float,
        month_usage: float,
        tou_data: dict = None,
        enhanced_balance: dict = None,
        step_data: dict = None,
        user_name: str = "",
        notify=True,
    ):
        self._detail("[%s] 开始通过 MQTT 更新 Home Assistant 数据...", user_id)
        self._save_to_cache(
            user_id, balance, last_daily_date, last_daily_usage,
            yearly_charge, yearly_usage, month_charge, month_usage,
            tou_data, enhanced_balance, step_data=step_data, user_name=user_name,
        )
        postfix = f"_{user_id[-4:]}"
        if balance is not None:
            if notify and self.balance_notify is not None:
                self.balance_notify(user_id, balance, user_name)
            self.update_balance(postfix, balance, user_id, user_name, enhanced_balance)
        if last_daily_usage is not None:
            self.update_last_daily_usage(postfix, last_daily_date, last_daily_usage, user_id, user_name)
        if yearly_usage is not None:
            self.update_yearly_data(postfix, yearly_usage, usage=True, user_id=user_id, user_name=user_name)
        if yearly_charge is not None:
            self.update_yearly_data(postfix, yearly_charge, user_id=user_id, user_name=user_name)
        if month_usage is not None:
            self.update_month_data(postfix, month_usage, usage=True, user_id=user_id, user_name=user_name)
        if month_charge is not None:
            self.update_month_data(postfix, month_charge, user_id=user_id, user_name=user_name)

        self._update_tou_sensors(user_id, postfix, tou_data, user_name)

        if step_data:
            self._update_step_sensors(postfix, step_data, user_id, user_name)

        if enhanced_balance and enhanced_balance.get("amount_due") is not None:
            self.update_prepay_balance(postfix, enhanced_balance["amount_due"], user_id, user_name)

        self._detail("[%s] MQTT 数据更新完成", user_id)

    # ------------------------------------------------------------------
    # 缓存
    # ------------------------------------------------------------------

    def _get_cache_file(self):
        from const import get_data_dir
        return os.path.join(get_data_dir(), 'sgcc_cache.json')

    def _save_to_cache(
        self, user_id, balance, last_daily_date, last_daily_usage,
        yearly_charge, yearly_usage, month_charge, month_usage,
        tou_data=None, enhanced_balance=None, step_data=None, user_name="",
    ):
        cache_file = self._get_cache_file()
        data = {}
        try:
            if os.path.exists(cache_file):
                with open(cache_file, 'r') as f:
                    data = json.load(f)
        except Exception as e:
            logging.warning("加载缓存文件失败: %s", e)

        cache_entry = {
            "balance": balance,
            "last_daily_date": last_daily_date,
            "last_daily_usage": last_daily_usage,
            "yearly_charge": yearly_charge,
            "yearly_usage": yearly_usage,
            "month_charge": month_charge,
            "month_usage": month_usage,
            "user_name": user_name or "",
            "timestamp": datetime.now().isoformat(),
        }
        if tou_data:
            cache_entry["tou_data"] = tou_data
        if enhanced_balance:
            cache_entry["enhanced_balance"] = enhanced_balance
        if step_data:
            cache_entry["step_data"] = step_data

        data[user_id] = cache_entry

        try:
            with open(cache_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logging.error("保存缓存文件失败 %s: %s", cache_file, e)

    def republish(self):
        """从本地缓存重推 HA 传感器。INFO 只报成功摘要，明细需 DEBUG。"""
        cache_file = self._get_cache_file()
        if not os.path.exists(cache_file):
            logging.info("未找到缓存文件 %s，跳过恢复", os.path.abspath(cache_file))
            return False

        data = {}
        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)
        except Exception as e:
            logging.error("加载缓存文件失败: %s", e)
            return False

        self._quiet = True
        try:
            for user_id, values in data.items():
                logging.debug("从缓存恢复户号 %s 的数据", user_id)
                clean_values = {k: v for k, v in values.items() if k != 'timestamp'}
                self.update_one_userid(user_id, **clean_values, notify=False)
            logging.info("缓存重推成功（%s 个户号）", len(data))
            return True
        except Exception as e:
            logging.error("从缓存恢复数据失败: %s", e)
            return False
        finally:
            self._quiet = False

    # ------------------------------------------------------------------
    # 数据库查询
    # ------------------------------------------------------------------

    @staticmethod
    def _current_month_key() -> str:
        return datetime.now().strftime("%Y-%m")

    def _query_month_tou_from_db(self, user_id: str, month: str) -> Optional[dict]:
        from db import create_db
        db = create_db()
        if db is None:
            self._detail("[%s] 未配置数据库 (DB_TYPE=none)，跳过当月分时传感器更新", user_id)
            return None
        if not db.connect_user_db(user_id):
            logging.warning("[%s] 数据库连接失败，无法查询当月分时电量", user_id)
            return None
        try:
            return db.query_month_tou_from_daily(user_id, month)
        finally:
            db.close_connect()

    # ------------------------------------------------------------------
    # 各传感器更新方法
    # ------------------------------------------------------------------

    def update_last_daily_usage(self, postfix, last_daily_date, sensor_state, user_id, user_name=""):
        base = DAILY_USAGE_SENSOR_NAME
        sensor_name = self._sensor_name(base, postfix)
        label = self._sensor_label(base)
        self._publish_sensor(
            sensor_name=sensor_name, label=label, state=sensor_state,
            unit="kWh", device_class="energy", state_class="measurement",
            user_id=user_id, user_name=user_name, icon="mdi:lightning-bolt",
            last_reset=last_daily_date,
        )
        self._log_updated(base, postfix, sensor_state, "kWh")

    def update_balance(self, postfix, sensor_state, user_id, user_name="", enhanced_balance=None):
        base = BALANCE_SENSOR_NAME
        sensor_name = self._sensor_name(base, postfix)
        label = self._sensor_label(base)
        last_reset = datetime.now().strftime("%Y-%m-%d, %H:%M:%S")

        attributes = {}
        if enhanced_balance and enhanced_balance.get("amount_due") is not None:
            attributes["amount_due"] = enhanced_balance["amount_due"]

        self._publish_sensor(
            sensor_name=sensor_name, label=label, state=sensor_state,
            unit="CNY", device_class="monetary", state_class="total",
            user_id=user_id, user_name=user_name, icon="mdi:cash",
            last_reset=last_reset,
            attributes=attributes if attributes else None,
        )
        self._log_updated(base, postfix, sensor_state, "元")

    def update_month_data(self, postfix, sensor_state, user_id, user_name="", usage=False):
        base = MONTH_USAGE_SENSOR_NAME if usage else MONTH_CHARGE_SENSOR_NAME
        sensor_name = self._sensor_name(base, postfix)
        current_date = datetime.now()
        first_day_of_current_month = current_date.replace(day=1)
        last_day_of_previous_month = first_day_of_current_month - timedelta(days=1)
        last_reset = last_day_of_previous_month.strftime("%Y-%m")
        unit = "kWh" if usage else "CNY"
        label = self._sensor_label(base)

        self._publish_sensor(
            sensor_name=sensor_name, label=label, state=sensor_state,
            unit=unit, device_class="energy" if usage else "monetary",
            state_class="measurement", user_id=user_id, user_name=user_name,
            icon="mdi:lightning-bolt" if usage else "mdi:cash",
            last_reset=last_reset,
        )
        self._log_updated(base, postfix, sensor_state, unit)

    def update_yearly_data(self, postfix, sensor_state, user_id, user_name="", usage=False):
        base = YEARLY_USAGE_SENSOR_NAME if usage else YEARLY_CHARGE_SENSOR_NAME
        sensor_name = self._sensor_name(base, postfix)
        now = datetime.now()
        if now.month == 1:
            last_reset = str(now.year - 1)
        else:
            last_reset = str(now.year)
        unit = "kWh" if usage else "CNY"
        label = self._sensor_label(base)

        self._publish_sensor(
            sensor_name=sensor_name, label=label, state=sensor_state,
            unit=unit, device_class="energy" if usage else "monetary",
            state_class="total_increasing", user_id=user_id, user_name=user_name,
            icon="mdi:lightning-bolt" if usage else "mdi:cash",
            last_reset=last_reset,
        )
        self._log_updated(base, postfix, sensor_state, unit)

    def update_prepay_balance(self, postfix, sensor_state, user_id, user_name=""):
        base = PREPAY_BALANCE_SENSOR_NAME
        sensor_name = self._sensor_name(base, postfix)
        label = self._sensor_label(base)
        last_reset = datetime.now().strftime("%Y-%m-%d, %H:%M:%S")

        self._publish_sensor(
            sensor_name=sensor_name, label=label, state=sensor_state,
            unit="CNY", device_class="monetary", state_class="total",
            user_id=user_id, user_name=user_name, icon="mdi:cash-check",
            last_reset=last_reset,
        )
        self._log_updated(base, postfix, sensor_state, "元")

    def _update_tou_sensors(self, user_id, postfix, tou_data=None, user_name=""):
        """从数据库汇总当前自然月日用电，更新谷/平/峰/尖传感器。"""
        target_month = self._current_month_key()
        summary = (tou_data or {}).get("month_tou_summary")
        if not summary:
            summary = self._query_month_tou_from_db(user_id, target_month)
        if not summary:
            self._detail("[%s] 数据库中无 %s 月日用电分时数据，跳过谷/平/峰/尖更新", user_id, target_month)
            return

        self._detail(
            "[%s] %s 月分时（数据库日用电汇总 %s 天）: 谷=%s, 平=%s, 峰=%s, 尖=%s kWh",
            user_id, target_month, summary['day_count'],
            summary['valley_usage'], summary['flat_usage'],
            summary['peak_usage'], summary['tip_usage'],
        )

        tou_fields = [
            ("valley_usage", MONTH_VALLEY_SENSOR_NAME),
            ("flat_usage", MONTH_FLAT_SENSOR_NAME),
            ("peak_usage", MONTH_PEAK_SENSOR_NAME),
            ("tip_usage", MONTH_TIP_SENSOR_NAME),
        ]
        for field_key, sensor_base in tou_fields:
            value = summary.get(field_key, 0) or 0
            sensor_name = self._sensor_name(sensor_base, postfix)
            label = self._sensor_label(sensor_base)
            self._publish_sensor(
                sensor_name=sensor_name, label=label, state=value,
                unit="kWh", device_class="energy", state_class="measurement",
                user_id=user_id, user_name=user_name, icon="mdi:lightning-bolt",
                last_reset=target_month,
            )
            self._detail("%s 【%s】 已更新: %s kWh", label, sensor_name, value)

    def _update_step_sensors(self, postfix, step_data, user_id, user_name=""):
        """更新阶梯用电传感器（仅住宅用户有数据）"""
        year_month = step_data.get("year_month") or datetime.now().strftime("%Y-%m")

        step_fields = [
            ("used_step1", STEP_USED_STEP1_SENSOR_NAME),
            ("remain_step1", STEP_REMAIN_STEP1_SENSOR_NAME),
            ("used_step2", STEP_USED_STEP2_SENSOR_NAME),
            ("remain_step2", STEP_REMAIN_STEP2_SENSOR_NAME),
            ("used_step3", STEP_USED_STEP3_SENSOR_NAME),
            ("total_usage", STEP_TOTAL_USAGE_SENSOR_NAME),
        ]
        for field_key, sensor_base in step_fields:
            if step_data.get(field_key) is None:
                continue
            value = float(step_data.get(field_key) or 0)
            sensor_name = self._sensor_name(sensor_base, postfix)
            label = self._sensor_label(sensor_base)
            self._publish_sensor(
                sensor_name=sensor_name, label=label, state=value,
                unit="kWh", device_class="energy", state_class="measurement",
                user_id=user_id, user_name=user_name, icon="mdi:stairs",
                attributes={"year_month": year_month},
            )
            self._detail("%s 【%s】 已更新: %s kWh", label, sensor_name, value)

        if step_data.get("step_stage") is not None:
            stage = int(step_data.get("step_stage") or 1)
            sensor_base = STEP_STAGE_SENSOR_NAME
            sensor_name = self._sensor_name(sensor_base, postfix)
            label = self._sensor_label(sensor_base)
            self._publish_sensor(
                sensor_name=sensor_name, label=label, state=stage,
                unit="", device_class="", state_class="measurement",
                user_id=user_id, user_name=user_name, icon="mdi:stairs",
                attributes={"year_month": year_month},
            )
            self._detail("%s 【%s】 已更新: 第%s阶段", label, sensor_name, stage)
