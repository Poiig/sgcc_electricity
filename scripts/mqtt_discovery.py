"""MQTT 发现模块，用于通过 MQTT Discovery 协议自动创建 Home Assistant 实体。"""
import json
import logging
import os
import time
from typing import Optional

import paho.mqtt.client as mqtt


class MQTTDiscoveryClient:
    """MQTT 发现客户端，支持通过 MQTT Discovery 自动创建 Home Assistant 实体。"""

    def __init__(self):
        self.mqtt_host = os.getenv("MQTT_HOST", "").strip()
        self.mqtt_port = int(os.getenv("MQTT_PORT", "1883"))
        self.mqtt_username = os.getenv("MQTT_USERNAME", "").strip()
        self.mqtt_password = os.getenv("MQTT_PASSWORD", "").strip()
        self.mqtt_client_id = os.getenv("MQTT_CLIENT_ID", "ha_sgcc_electricity").strip()
        self.mqtt_topic_prefix = os.getenv("MQTT_TOPIC_PREFIX", "homeassistant").strip()
        self.device_id = os.getenv("MQTT_DEVICE_ID", "ha_sgcc_electricity").strip()
        self.device_name = os.getenv("MQTT_DEVICE_NAME", "国家电网电费数据").strip()

        self.client: Optional[mqtt.Client] = None
        self.connected = False
        self._discovered_entities: set = set()

        if not self.mqtt_host:
            logging.info("MQTT_HOST 未配置，MQTT 功能已禁用")
            return

        self._init_client()

    def _init_client(self):
        """初始化 MQTT 客户端连接。"""
        try:
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=self.mqtt_client_id,
            )
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect

            if self.mqtt_username and self.mqtt_password:
                self.client.username_pw_set(self.mqtt_username, self.mqtt_password)

            self.client.reconnect_delay_set(min_delay=1, max_delay=30)
            self.client.connect(self.mqtt_host, self.mqtt_port, 60)
            self.client.loop_start()
            logging.info("正在连接 MQTT Broker: %s:%s", self.mqtt_host, self.mqtt_port)

            # 等待连接建立（最多 10 秒）
            for _ in range(100):
                if self.connected:
                    break
                time.sleep(0.1)
            if not self.connected:
                logging.warning("MQTT 连接尚未建立，后续操作将在连接就绪后执行")
                return

            # 清除旧版本遗留的双重 sensor/sensor. 路径的 retain 消息
            self._cleanup_legacy_topics()
        except Exception as e:
            logging.error("MQTT 客户端初始化失败: %s", e)

    def _cleanup_legacy_topics(self):
        """清除旧版本（entity_id 含 sensor. 前缀）遗留的 discovery retain 消息。

        通过订阅 MQTT wildcard topic 动态发现所有旧格式的 config topic，
        即 homeassistant/sensor/sensor.xxx/config 模式的残留消息，
        然后发送空 payload 清除 retain。
        """
        if not self.client or not self.connected:
            return

        legacy_topics = []

        def _on_legacy_message(client, userdata, msg):
            if msg.payload:
                topic = msg.topic
                # 只收集旧格式 topic（第三段以 sensor. 开头）
                parts = topic.split("/")
                if len(parts) == 4 and parts[2].startswith("sensor."):
                    legacy_topics.append(topic)

        # 使用 MQTT 单级通配符 + 匹配第三段
        wildcard = f"{self.mqtt_topic_prefix}/sensor/+/config"
        self.client.subscribe(wildcard)
        self.client.message_callback_add(wildcard, _on_legacy_message)

        # 等待 retain 消息到达
        time.sleep(3)

        # 取消订阅和回调
        self.client.unsubscribe(wildcard)
        self.client.message_callback_remove(wildcard)

        cleaned = 0
        for topic in legacy_topics:
            # 清除 config / state / attributes 三类 topic
            base_topic = topic[:-len("/config")]
            self.client.publish(topic, "", retain=True)
            self.client.publish(f"{base_topic}/state", "", retain=True)
            self.client.publish(f"{base_topic}/attributes", "", retain=True)
            cleaned += 1
        if cleaned:
            logging.info("已清除 %d 组旧版 MQTT Discovery retain 消息", cleaned)

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        """MQTT 连接成功回调。"""
        self.connected = True
        logging.info("MQTT 连接成功 (reason_code: %s)", reason_code)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        """MQTT 断开连接回调。"""
        self.connected = False
        if reason_code != 0:
            logging.warning("MQTT 意外断开连接 (reason_code: %s)，将自动重连", reason_code)

    def _get_device_info(self, user_id: str, user_name: str = "") -> dict:
        """获取设备信息。"""
        name = (user_name or "").strip()
        if name and name != user_id:
            display_name = f"{name}（{user_id[-4:]}）"
        else:
            display_name = f"国家电网电费-{user_id[-4:]}"

        return {
            "identifiers": [f"{self.device_id}_{user_id}"],
            "name": display_name,
            "model": "国家电网电费数据获取",
            "manufacturer": "SGCC",
            "sw_version": os.getenv("VERSION", "latest"),
        }

    def _get_sensor_config(
        self,
        entity_id: str,
        name: str,
        unit: str,
        device_class: str,
        state_class: str,
        user_id: str,
        user_name: str = "",
        icon: str = None,
        attributes: dict = None,
    ) -> dict:
        """生成传感器配置消息（HA MQTT Discovery 格式）。

        同时设置 object_id（兼容 HA <= 2025.10）和 default_entity_id（HA >= 2025.10），
        确保所有 HA 版本都能正确生成英文 entity_id，而不是从中文 name 拼音化。
        """
        object_id = entity_id.replace("sensor.", "")
        config = {
            "name": name,
            "unique_id": entity_id,
            "object_id": object_id,
            "default_entity_id": entity_id,
            "state_topic": f"{self.mqtt_topic_prefix}/sensor/{object_id}/state",
            "device": self._get_device_info(user_id, user_name),
        }

        if unit:
            config["unit_of_measurement"] = unit
        if device_class:
            config["device_class"] = device_class
        if state_class:
            config["state_class"] = state_class
        if icon:
            config["icon"] = icon
        if attributes:
            config["json_attributes_topic"] = f"{self.mqtt_topic_prefix}/sensor/{object_id}/attributes"

        return config

    def publish_sensor_discovery(
        self,
        entity_id: str,
        name: str,
        unit: str,
        device_class: str,
        state_class: str,
        user_id: str,
        user_name: str = "",
        icon: str = None,
        last_reset: str = None,
        attributes: dict = None,
    ) -> bool:
        """发布传感器发现配置。同一实体只发送一次配置，减少不必要的 MQTT 消息。"""
        if not self.client or not self.connected:
            logging.warning("MQTT 未连接，跳过发布发现配置: %s", entity_id)
            return False

        # 每个 entity_id 只发送一次 discovery 配置（除非 HA 重启或 MQTT broker 丢失 retain）
        if entity_id in self._discovered_entities:
            return True

        try:
            config = self._get_sensor_config(
                entity_id, name, unit, device_class, state_class, user_id, user_name, icon, attributes
            )
            object_id = entity_id.replace("sensor.", "")
            config_topic = f"{self.mqtt_topic_prefix}/sensor/{object_id}/config"
            self.client.publish(config_topic, json.dumps(config, ensure_ascii=False), retain=True)
            self._discovered_entities.add(entity_id)
            logging.info("已发布 MQTT 发现配置: %s", entity_id)
            return True
        except Exception as e:
            logging.error("发布 MQTT 发现配置失败 %s: %s", entity_id, e)
            return False

    def publish_sensor_state(self, entity_id: str, state, attributes: dict = None) -> bool:
        """发布传感器状态值和属性。"""
        if not self.client or not self.connected:
            logging.warning("MQTT 未连接，跳过发布状态: %s", entity_id)
            return False

        try:
            object_id = entity_id.replace("sensor.", "")
            state_topic = f"{self.mqtt_topic_prefix}/sensor/{object_id}/state"
            self.client.publish(state_topic, str(state), retain=True)

            if attributes:
                attrs_topic = f"{self.mqtt_topic_prefix}/sensor/{object_id}/attributes"
                self.client.publish(attrs_topic, json.dumps(attributes, ensure_ascii=False), retain=True)

            logging.debug("已发布 MQTT 状态: %s = %s", entity_id, state)
            return True
        except Exception as e:
            logging.error("发布 MQTT 状态失败 %s: %s", entity_id, e)
            return False

    def disconnect(self):
        """断开 MQTT 连接。"""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            logging.info("MQTT 连接已断开")

    def __del__(self):
        self.disconnect()
