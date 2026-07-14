import json
import time
import logging
import paho.mqtt.client as mqtt
from config import Config

logger = logging.getLogger(__name__)

_CFG    = Config.settings["mqtt"]
TOPICS  = _CFG["topics"]


class MQTTClient:
    def __init__(self, client_id: str = None):
        self._client = mqtt.Client(
            client_id=client_id or _CFG["client_id"],
            clean_session=True,
        )
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message    = self._on_message
        self._message_callbacks: dict[str, callable] = {}

    def connect(self):
        self._client.connect(
            host=_CFG["broker_host"],
            port=_CFG["broker_port"],
            keepalive=_CFG["keepalive"],
        )
        self._client.loop_start()

    def disconnect(self):
        self._client.loop_stop()
        self._client.disconnect()

    def publish_sensor(self, parameter: str, value: float):
        topic = TOPICS.get(parameter)
        if not topic:
            logger.warning("Unknown parameter: %s", parameter)
            return
        payload = json.dumps({
            "value": value,
            "parameter": parameter,
            "ts": int(time.time()),
        })
        self._client.publish(topic, payload, qos=1, retain=False)

    def publish_alert(self, parameter: str, value: float,
                      threshold: float, direction: str):
        payload = json.dumps({
            "parameter":  parameter,
            "value":      value,
            "threshold":  threshold,
            "direction":  direction,
            "ts":         int(time.time()),
        })
        self._client.publish(TOPICS["alerts"], payload, qos=1, retain=False)

    def publish_actuator(self, actuator: str, state: str):
        topic = TOPICS.get(actuator)
        if topic:
            self._client.publish(
                topic,
                json.dumps({"state": state, "ts": int(time.time())}),
                qos=1,
            )

    def subscribe(self, topic_key: str, callback: callable):
        topic = TOPICS.get(topic_key, topic_key)
        self._message_callbacks[topic] = callback
        self._client.subscribe(topic, qos=1)

    def publish(self, topic: str, payload: str, qos: int = 1) -> None:
        """Publish a raw string *payload* to an arbitrary *topic*.

        This is a low-level helper for dashboard routes that need to
        publish to topics such as ``control`` or ``thresholds`` without
        going through the higher-level ``publish_sensor`` / ``publish_alert``
        APIs.
        """
        self._client.publish(topic, payload, qos=qos)

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("MQTT connected to %s:%s",
                        _CFG["broker_host"], _CFG["broker_port"])
            for topic in list(self._message_callbacks):
                client.subscribe(topic, qos=1)
        else:
            logger.error("MQTT connection failed, rc=%s", rc)

    def _on_disconnect(self, client, userdata, rc):
        if rc != 0:
            logger.warning("MQTT unexpected disconnect rc=%s — will auto-reconnect", rc)

    def _on_message(self, client, userdata, msg):
        cb = self._message_callbacks.get(msg.topic)
        if cb:
            try:
                payload = json.loads(msg.payload.decode())
                cb(msg.topic, payload)
            except Exception as exc:
                logger.error("MQTT message handler error: %s", exc)
