import time
import logging
import signal
import threading

import actuators
import notifier
from sensor_reader import SensorReader
from mqtt_client   import MQTTClient
from influx_writer import InfluxWriter
from config        import Config, load_thresholds, save_thresholds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

_INTERVAL        = Config.settings["sampling"]["interval_seconds"]
_BUZZER_DURATION = Config.settings["sampling"]["alert_buzzer_duration_seconds"]

_active_alerts:  dict[str, str] = {}
_thresholds:     dict = load_thresholds()
_paused:         bool = False
_shutdown_event: threading.Event = threading.Event()


# ── MQTT callbacks ────────────────────────────────────────────────────────────

def _on_threshold_change(topic: str, payload: dict):
    global _thresholds
    param = payload.get("parameter")
    if param not in _thresholds:
        logger.warning("Unknown threshold parameter: %s", param)
        return
    if "min" in payload:
        _thresholds[param]["min"] = float(payload["min"])
    if "max" in payload:
        _thresholds[param]["max"] = float(payload["max"])
    save_thresholds(_thresholds)
    logger.info("Threshold updated: %s → min=%.1f max=%.1f",
                param, _thresholds[param]["min"], _thresholds[param]["max"])


def _on_control_command(topic: str, payload: dict):
    global _paused
    cmd = payload.get("command", "")
    if cmd == "pause":
        _paused = True
        logger.info("Sensor loop PAUSED (hardware-test mode)")
        actuators.fan_off()
        actuators.humidifier_off()
        actuators.blind_open()
        actuators.buzzer_off()
    elif cmd == "resume":
        _paused = False
        logger.info("Sensor loop RESUMED")
    elif cmd == "fan_on":
        actuators.fan_on()
        logger.info("Fan → on (manual)")
    elif cmd == "fan_off":
        actuators.fan_off()
        logger.info("Fan → off (manual)")
    elif cmd == "humidifier_on":
        actuators.humidifier_on()
        logger.info("Humidifier → on (manual)")
    elif cmd == "humidifier_off":
        actuators.humidifier_off()
        logger.info("Humidifier → off (manual)")
    elif cmd == "blind_closed":
        actuators.blind_close()
        logger.info("Blind → closed (manual)")
    elif cmd == "blind_open":
        actuators.blind_open()
        logger.info("Blind → open (manual)")
    elif cmd == "buzzer_beep":
        actuators.buzzer_pulse_start()
        threading.Timer(_BUZZER_DURATION, actuators.buzzer_pulse_stop).start()
        logger.info("Buzzer → pulse (manual)")


# ── Actuator logic ────────────────────────────────────────────────────────────

def _update_actuators(alerts: dict, mqtt: MQTTClient):
    """Set fan/humidifier/blind based on *alerts* (the current breach dict)."""
    needs_fan        = bool(alerts)
    needs_humidifier = alerts.get("humidity") == "low"
    needs_blind      = alerts.get("light")    == "high"

    if needs_fan:
        actuators.fan_on()
        mqtt.publish_actuator("fan", "on")
    else:
        actuators.fan_off()
        mqtt.publish_actuator("fan", "off")

    if needs_humidifier:
        actuators.humidifier_on()
        mqtt.publish_actuator("humidifier", "on")
    else:
        actuators.humidifier_off()
        mqtt.publish_actuator("humidifier", "off")

    if needs_blind:
        actuators.blind_close()
        mqtt.publish_actuator("blind", "closed")
    else:
        actuators.blind_open()
        mqtt.publish_actuator("blind", "open")

    # Buzzer: pulsing tic-tic while any alert active
    if needs_fan:
        actuators.buzzer_pulse_start()
        mqtt.publish_actuator("buzzer", "on")
    else:
        actuators.buzzer_pulse_stop()
        mqtt.publish_actuator("buzzer", "off")


# ── Threshold evaluation (pure logic, no side effects) ────────────────────────

def _evaluate_thresholds(readings: dict) -> dict[str, str]:
    alerts: dict[str, str] = {}
    for param, value in readings.items():
        if param not in _thresholds:
            continue
        t_min = _thresholds[param]["min"]
        t_max = _thresholds[param]["max"]
        if value < t_min:
            alerts[param] = "low"
        elif value > t_max:
            alerts[param] = "high"
    return alerts


def _detect_state_changes(new_alerts: dict) -> tuple[set, set]:
    """Return ``(newly_breached_params, recovered_params)`` by comparing
    *new_alerts* against the global ``_active_alerts`` snapshot."""
    newly_breached = {
        p for p, d in new_alerts.items()
        if p not in _active_alerts or _active_alerts[p] != d
    }
    recovered = set(_active_alerts) - set(new_alerts)
    return newly_breached, recovered


def _handle_new_breaches(newly_breached: set, new_alerts: dict,
                         readings: dict, mqtt: MQTTClient):
    """Publish MQTT alerts and send notifications for newly breached params."""
    for param in newly_breached:
        direction  = new_alerts[param]
        t_boundary = (_thresholds[param]["max"] if direction == "high"
                      else _thresholds[param]["min"])
        value      = readings[param]

        logger.warning("ALERT: %s=%.2f is %s threshold=%.2f",
                       param, value, direction, t_boundary)
        mqtt.publish_alert(param, value, t_boundary, direction)
        notifier.send_alert(param, value, t_boundary, direction)


def _handle_recoveries(recovered: set, new_alerts: dict,
                       readings: dict, mqtt: MQTTClient):
    """Log recovered parameters."""
    for param in recovered:
        logger.info("RECOVERY: %s is back within safe range", param)

    for param, direction in new_alerts.items():
        if param not in recovered:
            logger.info("Ongoing alert: %s=%.2f (%s)",
                        param, readings[param], direction)


# ── Main loop ─────────────────────────────────────────────────────────────────

def _main_loop(sensors, mqtt, db):
    """Single iteration: read, publish, store, check thresholds."""
    readings = sensors.read_all()
    logger.info(
        "Readings — Temp:%.1f°C  Hum:%.1f%%  "
        "Press:%.1f hPa  Light:%.0f lux",
        readings["temperature"],
        readings["humidity"],
        readings["pressure"],
        readings["light"],
    )

    for param, value in readings.items():
        mqtt.publish_sensor(param, value)

    try:
        db.write(**readings)
    except Exception as db_exc:
        logger.error("InfluxDB write failed: %s", db_exc)

    # ── Alert logic ───────────────────────────────────────────────────────────
    new_alerts = _evaluate_thresholds(readings)
    newly_breached, recovered = _detect_state_changes(new_alerts)

    # Drive actuators based on current alerts (every cycle)
    _update_actuators(new_alerts, mqtt)

    if newly_breached:
        _handle_new_breaches(newly_breached, new_alerts, readings, mqtt)

    if recovered:
        _handle_recoveries(recovered, new_alerts, readings, mqtt)

    # Persist new alert state
    _active_alerts.clear()
    _active_alerts.update(new_alerts)


def main():
    actuators.setup()

    mqtt = MQTTClient()
    mqtt.connect()
    mqtt.subscribe("thresholds", _on_threshold_change)
    mqtt.subscribe("control",    _on_control_command)

    def _signal_handler(sig, frame):
        logger.info("Shutdown signal received ...")
        _shutdown_event.set()

    signal.signal(signal.SIGINT,  _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    logger.info("Museum Climate System started — sampling every %ds", _INTERVAL)

    with SensorReader() as sensors, InfluxWriter() as db:
        while not _shutdown_event.is_set():
            if _paused:
                _shutdown_event.wait(1)
                continue
            try:
                _main_loop(sensors, mqtt, db)
            except Exception as exc:
                logger.error("Sensor loop error: %s", exc, exc_info=True)

            _shutdown_event.wait(_INTERVAL)

    # ── Graceful shutdown ─────────────────────────────────────────────────────
    logger.info("Shutting down — cleaning up actuators and connections ...")
    actuators.buzzer_pulse_stop()
    actuators.fan_off()
    actuators.humidifier_off()
    actuators.blind_open()
    mqtt.disconnect()
    actuators.cleanup()
    logger.info("Shutdown complete.")


if __name__ == "__main__":
    main()
