import json
import time
import logging
import os

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import Config, load_thresholds, save_thresholds
from mqtt_client import MQTTClient

logger = logging.getLogger(__name__)

app = FastAPI(title="Museum Climate Dashboard", docs_url=None, redoc_url=None)

_DIR      = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(_DIR, "static")), name="static")

TOPICS = Config.settings["mqtt"]["topics"]

_latest: dict = {
    "temperature": "--",
    "humidity":    "--",
    "pressure":    "--",
    "light":       "--",
    "updated_at":  "--",
}
_alerts:           list[dict] = []
_fan_state:        str = "off"
_humidifier_state: str = "off"
_blind_state:      str = "open"
_buzzer_state:     str = "off"
_sensor_paused:    bool = False

mqtt_client = MQTTClient(client_id="museum_dashboard")


def _on_sensor_message(topic: str, payload: dict):
    sensor_map = {
        TOPICS["temperature"]: "temperature",
        TOPICS["humidity"]:    "humidity",
        TOPICS["pressure"]:    "pressure",
        TOPICS["light"]:       "light",
    }
    if topic in sensor_map:
        _latest[sensor_map[topic]] = payload["value"]
        _latest["updated_at"]      = time.strftime("%H:%M:%S")


def _on_alert_message(topic: str, payload: dict):
    _alerts.insert(0, {
        "parameter": payload["parameter"],
        "value":     payload["value"],
        "threshold": payload["threshold"],
        "direction": payload["direction"],
        "time":      time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    if len(_alerts) > 20:
        _alerts.pop()


def _on_actuator_message(topic: str, payload: dict):
    global _fan_state, _humidifier_state, _blind_state, _buzzer_state
    if topic == TOPICS.get("fan"):
        _fan_state = payload.get("state", "off")
    elif topic == TOPICS.get("humidifier"):
        _humidifier_state = payload.get("state", "off")
    elif topic == TOPICS.get("blind"):
        _blind_state = payload.get("state", "open")
    elif topic == TOPICS.get("buzzer"):
        _buzzer_state = payload.get("state", "off")


def _on_control_message(topic: str, payload: dict):
    global _sensor_paused
    cmd = payload.get("command", "")
    if cmd == "pause":
        _sensor_paused = True
    elif cmd == "resume":
        _sensor_paused = False


@app.on_event("startup")
def _start_mqtt():
    mqtt_client.connect()
    mqtt_client.subscribe("temperature", _on_sensor_message)
    mqtt_client.subscribe("humidity",    _on_sensor_message)
    mqtt_client.subscribe("pressure",    _on_sensor_message)
    mqtt_client.subscribe("light",       _on_sensor_message)
    mqtt_client.subscribe("alerts",      _on_alert_message)
    mqtt_client.subscribe("fan",         _on_actuator_message)
    mqtt_client.subscribe("buzzer",      _on_actuator_message)
    mqtt_client.subscribe("humidifier",  _on_actuator_message)
    mqtt_client.subscribe("blind",       _on_actuator_message)
    mqtt_client.subscribe("control",     _on_control_message)


@app.on_event("shutdown")
def _stop_mqtt():
    mqtt_client.disconnect()


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "readings":   _latest,
        "thresholds": load_thresholds(),
        "alerts":     _alerts,
    })


@app.get("/api/readings")
async def api_readings():
    return {
        **_latest,
        "fan_state":        _fan_state,
        "humidifier_state": _humidifier_state,
        "blind_state":      _blind_state,
        "buzzer_state":     _buzzer_state,
        "sensor_paused":    _sensor_paused,
        "alerts":           _alerts[:5],
    }


@app.get("/thresholds")
async def thresholds_page(request: Request):
    return templates.TemplateResponse(request, "thresholds.html", {
        "thresholds": load_thresholds(),
    })


def _publish_control(command: str):
    mqtt_client.publish(
        TOPICS["control"],
        json.dumps({"command": command, "ts": int(time.time())}),
    )


@app.post("/thresholds")
async def update_thresholds(request: Request):
    form       = await request.form()
    thresholds = load_thresholds()

    for param in thresholds:
        if f"{param}_min" in form:
            thresholds[param]["min"] = int(form[f"{param}_min"])
        if f"{param}_max" in form:
            thresholds[param]["max"] = int(form[f"{param}_max"])

    save_thresholds(thresholds)

    for param, vals in thresholds.items():
        mqtt_client.publish(
            TOPICS["thresholds"],
            json.dumps({"parameter": param, "min": vals["min"], "max": vals["max"]}),
        )
    return RedirectResponse(url="/thresholds", status_code=303)


@app.get("/test")
async def test_page(request: Request):
    return templates.TemplateResponse(request, "test.html", {
        "readings":       _latest,
        "sensor_paused":  _sensor_paused,
        "fan_state":      _fan_state,
        "humidifier_state": _humidifier_state,
        "blind_state":    _blind_state,
    })


@app.post("/api/test/sensor/{cmd}")
async def test_sensor_control(cmd: str):
    if cmd not in ("pause", "resume"):
        return JSONResponse({"error": "invalid"}, status_code=400)
    _publish_control(cmd)
    return JSONResponse({"status": "ok", "command": cmd})


@app.post("/api/test/fan/{state}")
async def test_fan(state: str):
    if state not in ("on", "off"):
        return JSONResponse({"error": "invalid"}, status_code=400)
    _publish_control(f"fan_{state}")
    return JSONResponse({"status": "ok", "state": state})


@app.post("/api/test/humidifier/{state}")
async def test_humidifier(state: str):
    if state not in ("on", "off"):
        return JSONResponse({"error": "invalid"}, status_code=400)
    _publish_control(f"humidifier_{state}")
    return JSONResponse({"status": "ok", "state": state})


@app.post("/api/test/blind/{state}")
async def test_blind(state: str):
    if state not in ("open", "closed"):
        return JSONResponse({"error": "invalid"}, status_code=400)
    cmd = "blind_closed" if state == "closed" else "blind_open"
    _publish_control(cmd)
    return JSONResponse({"status": "ok", "state": state})


@app.post("/api/test/buzzer")
async def test_buzzer():
    _publish_control("buzzer_beep")
    return JSONResponse({"status": "ok", "action": "buzzer_beep"})


@app.get("/api/test/readings")
async def test_readings():
    return JSONResponse({
        **_latest,
        "sensor_paused": _sensor_paused,
    })


@app.get("/api/history")
async def history(range: str = "1h"):
    """Return time-series data from InfluxDB for charting."""
    try:
        from influxdb_client import InfluxDBClient
        cfg = Config.settings["influxdb"]
        client = InfluxDBClient(url=cfg["url"], token=cfg["token"], org=cfg["org"])
        query_api = client.query_api()
        flux = f'''
from(bucket: "{cfg["bucket"]}")
  |> range(start: -{range})
  |> filter(fn: (r) => r._measurement == "{cfg["measurement"]}")
  |> filter(fn: (r) => r._field == "temperature" or r._field == "humidity"
                    or r._field == "pressure"    or r._field == "light")
  |> aggregateWindow(every: 1m, fn: mean, createEmpty: false)
  |> keep(columns: ["_time", "_field", "_value"])
'''
        tables = query_api.query(flux)
        client.close()

        series: dict[str, list] = {"time": [], "temperature": [], "humidity": [], "pressure": [], "light": []}
        rows: dict[str, dict] = {}

        for table in tables:
            for record in table.records:
                t = record.get_time().strftime("%H:%M")
                f = record.get_field()
                v = record.get_value()
                if t not in rows:
                    rows[t] = {}
                rows[t][f] = round(v, 2) if v is not None else None

        for t in sorted(rows):
            series["time"].append(t)
            for f in ("temperature", "humidity", "pressure", "light"):
                series[f].append(rows[t].get(f))

        return JSONResponse(series)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cfg = Config.settings.get("dashboard", {"host": "0.0.0.0", "port": 5000})
    uvicorn.run("dashboard.app:app", host=cfg["host"], port=cfg["port"], reload=False)
