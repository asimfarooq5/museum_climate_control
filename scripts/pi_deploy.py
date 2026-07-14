#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
import pexpect

PI_HOST = "192.168.0.100"
PI_USER = "pi"
PI_PASS = "1234"
PI_REPO = "/home/pi/museum_climate_control"

LOCAL_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PYTHON_DEPS = (
    "RPi.GPIO smbus2 bme280 paho-mqtt "
    "influxdb-client fastapi 'uvicorn[standard]' "
    "jinja2 python-multipart twilio plyer"
)

VENV_PYTHON = f"{PI_REPO}/venv/bin/python3"
VENV_PIP    = f"{PI_REPO}/venv/bin/pip"

SETTINGS_TEMPLATE = {
    "mqtt": {
        "broker_host": "localhost",
        "broker_port": 1883,
        "client_id": "museum_main",
        "keepalive": 60,
        "topics": {
            "temperature": "museum/sensors/temperature",
            "humidity":    "museum/sensors/humidity",
            "pressure":    "museum/sensors/pressure",
            "light":       "museum/sensors/light",
            "alerts":      "museum/alerts",
            "fan":         "museum/actuators/fan",
            "buzzer":      "museum/actuators/buzzer",
            "humidifier":  "museum/actuators/humidifier",
            "blind":       "museum/actuators/blind",
            "thresholds":  "museum/thresholds/set",
            "control":     "museum/control"
        }
    },
    "influxdb": {
        "url":         "http://localhost:8086",
        "token":       "REPLACE_WITH_YOUR_INFLUXDB_TOKEN",
        "org":         "museum",
        "bucket":      "museum_climate",
        "measurement": "climate_readings",
        "location":    "gallery_1"
    },
    "gpio": {
        "buzzer_pin":         17,
        "relay_fan_pin":      27,
        "relay_humidifier_pin": 22,
        "relay_blind_pin":    24,
        "relay_active_low":   True,
        "buzzer_active_high": True
    },
    "i2c": {
        "bme280_address": "0x76",
        "bh1750_address": "0x23",
        "bus": 1
    },
    "email": {
        "enabled":          False,
        "smtp_host":        "smtp.gmail.com",
        "smtp_port":        587,
        "sender":           "your_email@gmail.com",
        "password":         "YOUR_APP_PASSWORD_HERE",
        "recipients":       ["curator@museum.org"],
        "cooldown_minutes": 15
    },
    "sms": {
        "enabled":       False,
        "account_sid":   "YOUR_TWILIO_SID",
        "auth_token":    "YOUR_TWILIO_AUTH_TOKEN",
        "from_number":   "+1XXXXXXXXXX",
        "to_number":     "+1XXXXXXXXXX",
        "cooldown_minutes": 15
    },
    "sampling": {
        "interval_seconds":            10,
        "alert_buzzer_duration_seconds": 5
    },
    "dashboard": {
        "host":  "0.0.0.0",
        "port":  5000,
        "debug": False
    }
}

SENSOR_SERVICE = """\
[Unit]
Description=Museum Climate Sensor Loop
After=network.target mosquitto.service

[Service]
ExecStart={venv_python} {repo}/src/main.py
WorkingDirectory={repo}/src
Restart=always
RestartSec=10
User=pi
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""

DASHBOARD_SERVICE = """\
[Unit]
Description=Museum Climate FastAPI Dashboard
After=network.target mosquitto.service

[Service]
ExecStart={venv_python} -m uvicorn dashboard.app:app --host 0.0.0.0 --port 5000
WorkingDirectory={repo}/src
Restart=always
RestartSec=5
User=pi
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""


def ssh_run(child, cmd, timeout=120, expect_prompt="\\$"):
    print(f"  $ {cmd[:80]}")
    child.sendline(cmd)
    child.expect(expect_prompt, timeout=timeout)
    out = child.before.decode(errors="replace").strip()
    if out:
        lines = out.splitlines()
        for line in lines[-5:]:
            print(f"    {line}")
    return out


def connect():
    print(f"\n[SSH] Connecting to {PI_USER}@{PI_HOST} ...")
    child = pexpect.spawn(
        f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 "
        f"{PI_USER}@{PI_HOST}",
        encoding=None,
        timeout=30,
    )
    i = child.expect(["password:", "\\$", pexpect.EOF, pexpect.TIMEOUT])
    if i == 0:
        child.sendline(PI_PASS)
        child.expect("\\$", timeout=15)
    elif i == 2:
        print("ERROR: SSH connection refused")
        sys.exit(1)
    elif i == 3:
        print("ERROR: SSH timed out")
        sys.exit(1)
    print("[SSH] Connected.")
    return child


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host",     default=PI_HOST)
    parser.add_argument("--password", default=PI_PASS)
    args = parser.parse_args()

    child = connect()

    print("\n[1/8] Setting up repo directory on Pi ...")
    ssh_run(child, f"mkdir -p {PI_REPO}/{{config,src/dashboard/{{templates,static}},scripts,grafana}}")

    print("\n[2/8] Uploading source files ...")
    _upload_files(child)

    print("\n[3/8] Installing Python dependencies in venv ...")
    ssh_run(child, f"python3 -m venv {PI_REPO}/venv", timeout=60)
    ssh_run(child, f"{VENV_PIP} install --upgrade pip -q", timeout=120)
    ssh_run(child, f"{VENV_PIP} install -q {PYTHON_DEPS}", timeout=300)

    print("\n[4/8] Creating settings.json ...")
    settings_json = json.dumps(SETTINGS_TEMPLATE, indent=2)
    settings_json_escaped = settings_json.replace("'", "'\\''")
    ssh_run(child,
        f"test -f {PI_REPO}/config/settings.json || "
        f"echo '{settings_json_escaped}' > {PI_REPO}/config/settings.json"
    )

    print("\n[5/8] Enabling I2C ...")
    ssh_run(child, "sudo raspi-config nonint do_i2c 0 2>/dev/null || echo 'raspi-config not available'")
    ssh_run(child, "sudo modprobe i2c-dev 2>/dev/null || true")

    print("\n[6/8] Configuring Mosquitto ...")
    ssh_run(child,
        "echo 'listener 1883\\nallow_anonymous true' | "
        "sudo tee /etc/mosquitto/conf.d/museum.conf > /dev/null"
    )
    ssh_run(child, "sudo systemctl enable --now mosquitto")
    ssh_run(child, "sudo systemctl restart mosquitto")

    print("\n[7/8] Starting Grafana ...")
    ssh_run(child, "sudo systemctl enable --now grafana-server 2>/dev/null || echo 'Grafana not installed'")

    print("\n[8/8] Installing and starting systemd services ...")
    _install_services(child)

    ssh_run(child, "sudo systemctl daemon-reload")
    ssh_run(child, "sudo systemctl enable museum-sensors museum-dashboard")
    ssh_run(child, "sudo systemctl restart museum-sensors museum-dashboard")

    print("\n[STATUS] Service status:")
    ssh_run(child, "sudo systemctl is-active museum-sensors museum-dashboard mosquitto")
    ssh_run(child, f"curl -s http://localhost:5000/ | head -5 2>/dev/null || echo 'Dashboard not yet ready'")

    child.sendline("exit")

    print(f"""
╔══════════════════════════════════════════════════════╗
║  Museum Climate System — Deployed Successfully!       ║
╠══════════════════════════════════════════════════════╣
║  FastAPI Dashboard : http://{PI_HOST}:5000            ║
║  Grafana           : http://{PI_HOST}:3000            ║
║  InfluxDB UI       : http://{PI_HOST}:8086            ║
║  MQTT Broker       : {PI_HOST}:1883                   ║
╠══════════════════════════════════════════════════════╣
║  NEXT: Open InfluxDB UI, copy token to               ║
║        {PI_REPO}/config/settings.json               ║
╚══════════════════════════════════════════════════════╝
""")


def _upload_files(child):
    files_to_upload = []
    for root, dirs, files in os.walk(LOCAL_REPO):
        dirs[:] = [d for d in dirs if d not in {".git", "venv", "__pycache__"}]
        for fname in files:
            local_path = os.path.join(root, fname)
            rel_path   = os.path.relpath(local_path, LOCAL_REPO)
            remote_path = f"{PI_REPO}/{rel_path}"
            files_to_upload.append((local_path, remote_path))

    for local_path, remote_path in files_to_upload:
        try:
            with open(local_path, "rb") as f:
                content = f.read()
            import base64
            b64 = base64.b64encode(content).decode()
            remote_dir = os.path.dirname(remote_path)
            ssh_run(child, f"mkdir -p {remote_dir}")
            ssh_run(child, f"echo '{b64}' | base64 -d > {remote_path}")
            print(f"    uploaded {os.path.relpath(local_path, LOCAL_REPO)}")
        except Exception as e:
            print(f"    WARN: could not upload {local_path}: {e}")


def _install_services(child):
    sensor_svc = SENSOR_SERVICE.format(venv_python=VENV_PYTHON, repo=PI_REPO)
    dash_svc   = DASHBOARD_SERVICE.format(venv_python=VENV_PYTHON, repo=PI_REPO)

    for name, content in [
        ("museum-sensors",   sensor_svc),
        ("museum-dashboard", dash_svc),
    ]:
        import base64
        b64 = base64.b64encode(content.encode()).decode()
        ssh_run(child,
            f"echo '{b64}' | base64 -d | sudo tee /etc/systemd/system/{name}.service > /dev/null"
        )


if __name__ == "__main__":
    main()
