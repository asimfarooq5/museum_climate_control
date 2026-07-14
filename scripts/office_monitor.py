#!/usr/bin/env python3
import argparse
import json
import sys
import time
import threading
from datetime import datetime

import paho.mqtt.client as mqtt

try:
    from plyer import notification as _plyer_notif
    _DESKTOP_NOTIFY = True
except ImportError:
    _DESKTOP_NOTIFY = False
    print("[WARN] plyer not installed — desktop notifications disabled")
    print("       pip install plyer")

TOPICS = {
    "temperature": "museum/sensors/temperature",
    "humidity":    "museum/sensors/humidity",
    "pressure":    "museum/sensors/pressure",
    "light":       "museum/sensors/light",
    "alerts":      "museum/alerts",
    "fan":         "museum/actuators/fan",
    "humidifier":  "museum/actuators/humidifier",
    "blind":       "museum/actuators/blind",
}

_state = {
    "temperature": "--",
    "humidity":    "--",
    "pressure":    "--",
    "light":       "--",
    "fan":         "off",
    "humidifier":  "off",
    "blind":       "open",
    "updated_at":  "--",
    "alerts":      [],
}
_lock = threading.Lock()


def _on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"[MQTT] Connected to broker {userdata['host']}:{userdata['port']}")
        for topic in TOPICS.values():
            client.subscribe(topic, qos=1)
    else:
        print(f"[MQTT] Connection failed (rc={rc})")
        sys.exit(1)


def _on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        topic   = msg.topic
        now     = datetime.now().strftime("%H:%M:%S")

        with _lock:
            sensor_map = {v: k for k, v in TOPICS.items()
                          if k in ("temperature", "humidity", "pressure", "light")}
            if topic in sensor_map:
                param = sensor_map[topic]
                _state[param]      = payload["value"]
                _state["updated_at"] = now

            elif topic == TOPICS["alerts"]:
                entry = {
                    "time":      now,
                    "parameter": payload["parameter"],
                    "value":     payload["value"],
                    "threshold": payload["threshold"],
                    "direction": payload["direction"],
                }
                _state["alerts"].insert(0, entry)
                if len(_state["alerts"]) > 10:
                    _state["alerts"].pop()
                _desktop_alert(entry)

            elif topic == TOPICS["fan"]:
                _state["fan"] = payload.get("state", "off")
            elif topic == TOPICS["humidifier"]:
                _state["humidifier"] = payload.get("state", "off")
            elif topic == TOPICS["blind"]:
                _state["blind"] = payload.get("state", "open")

        _render()
    except Exception as exc:
        print(f"[ERROR] Message parse error: {exc}")


def _desktop_alert(entry: dict):
    if not _DESKTOP_NOTIFY:
        return
    param     = entry["parameter"].capitalize()
    direction = "exceeded" if entry["direction"] == "high" else "fallen below"
    try:
        _plyer_notif.notify(
            title=f"MUSEUM ALERT — {param}",
            message=f"{param} {direction} safe range.\nReading={entry['value']}, Threshold={entry['threshold']}",
            app_name="Museum Climate Monitor",
            timeout=10,
        )
    except Exception:
        pass


def _render():
    with _lock:
        s = dict(_state)

    sep = "─" * 52
    lines = [
        f"\r\033[K{sep}",
        f"  Smart Museum Preservation System — Office View",
        f"  Updated: {s['updated_at']}",
        sep,
        f"  Temperature : {s['temperature']:>7} °C",
        f"  Humidity    : {s['humidity']:>7} %",
        f"  Pressure    : {s['pressure']:>7} hPa",
        f"  Light       : {s['light']:>7} lux",
        sep,
        f"  Fan         : {s['fan'].upper():<6}  "
        f"Humidifier: {s['humidifier'].upper():<6}  "
        f"Blind: {s['blind'].upper()}",
        sep,
    ]
    if s["alerts"]:
        lines.append("  Recent alerts:")
        for a in s["alerts"][:5]:
            dw = ">" if a["direction"] == "high" else "<"
            lines.append(
                f"    [{a['time']}] {a['parameter'].capitalize():12} "
                f"= {a['value']} (threshold {dw} {a['threshold']})"
            )
    else:
        lines.append("  No alerts yet.")
    lines.append(sep)

    print("\033[{}A".format(len(lines)), end="")
    for line in lines:
        print(f"\033[2K{line}")


def main():
    parser = argparse.ArgumentParser(description="Museum Office Monitor")
    parser.add_argument("--broker", default="192.168.0.100",
                        help="MQTT broker host (Pi IP)")
    parser.add_argument("--port",   type=int, default=1883)
    args = parser.parse_args()

    client = mqtt.Client(client_id="museum_office_pc",
                         userdata={"host": args.broker, "port": args.port})
    client.on_connect = _on_connect
    client.on_message = _on_message

    print(f"Connecting to MQTT broker at {args.broker}:{args.port} ...")
    print("Press Ctrl+C to exit.\n")
    print("\n" * 20)

    try:
        client.connect(args.broker, args.port, keepalive=60)
        client.loop_forever()
    except KeyboardInterrupt:
        print("\nOffice monitor stopped.")
    except Exception as exc:
        print(f"\nConnection error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
