# Smart Museum Preservation System
### ECMC104 IIOT for Advanced Manufacturing

A Raspberry Pi IoT system that continuously monitors temperature, humidity,
and light levels in museum environments. Alerts the curator and activates a
ventilation fan automatically when readings drift outside safe conservation ranges.

---

## Hardware Required

| Component | Purpose |
|-----------|---------|
| Raspberry Pi 3B / 4 | Edge device & MQTT gateway |
| BME280 (I2C) | Temperature, humidity, pressure |
| BH1750 (I2C) | Ambient light level (lux) |
| Active Buzzer | On-site alarm |
| 5V Relay Module | Switches the fan circuit |
| 5V DC Fan | Ventilation actuator |
| Jumper wires + breadboard | Connections |

## Wiring Summary

```
BME280  VCC → Pi Pin 1  (3.3V)
BME280  SDA → Pi Pin 3  (GPIO2)
BME280  SCL → Pi Pin 5  (GPIO3)
BME280  GND → Pi Pin 6  (GND)

BH1750  VCC  → Pi Pin 1  (3.3V)  -- shares I2C bus with BME280
BH1750  SDA  → Pi Pin 3  (GPIO2)
BH1750  SCL  → Pi Pin 5  (GPIO3)
BH1750  GND  → Pi Pin 9  (GND)
BH1750  ADDR → Pi Pin 9  (GND)   -- I2C address = 0x23

Buzzer  +   → Pi Pin 11 (GPIO17) via 330Ω
Buzzer  -   → Pi Pin 9  (GND)

Relay   VCC → Pi Pin 2  (5V)
Relay   IN  → Pi Pin 13 (GPIO27)
Relay   GND → Pi Pin 14 (GND)
Relay COM/NO → Fan power circuit
```

See `PROJECT_PLAN.md` for the full ASCII wiring diagram and system architecture.

---

## Installation

```bash
git clone <repo-url> museum_climate_control
cd museum_climate_control
bash install.sh
```

The installer:
1. Enables I2C on the Pi
2. Installs all Python libraries (RPi.GPIO, smbus2, bme280, paho-mqtt, fastapi, uvicorn, influxdb-client)
3. Installs and starts Mosquitto MQTT broker
4. Installs and starts InfluxDB 2.x
5. Installs and starts Grafana
6. Registers `museum-sensors` and `museum-dashboard` as systemd services

### Post-install configuration

1. Open `http://<pi-ip>:8086` → complete InfluxDB setup (org: `museum`, bucket: `museum_climate`)
2. Copy the generated token into `config/settings.json` → `influxdb.token`
3. *(Optional)* Enable email alerts in `config/settings.json` → `email` section
4. Restart services:
   ```bash
   sudo systemctl restart museum-sensors museum-dashboard
   ```

---

## Configuration

### Thresholds — `config/thresholds.json`
```json
{
  "temperature": { "min": 18.0, "max": 24.0, "unit": "C" },
  "humidity":    { "min": 45.0, "max": 60.0, "unit": "%" },
  "light":       { "min": 0.0,  "max": 200.0,"unit": "lux" }
}
```
Edit directly **or** use the web dashboard at `http://<pi-ip>:5000`.

### Email alerts — `config/settings.json` → `email`
```json
{
  "enabled": true,
  "sender": "your@gmail.com",
  "password": "your-app-password",
  "recipients": ["curator@museum.org"],
  "cooldown_minutes": 15
}
```
Gmail requires an **App Password** (Account → Security → 2-Step Verification → App passwords).

---

## Operation

| Service | Command |
|---------|---------|
| Start all | `sudo systemctl start museum-sensors museum-dashboard` |
| Stop all | `sudo systemctl stop museum-sensors museum-dashboard` |
| View sensor log | `sudo journalctl -u museum-sensors -f` |
| View dashboard log | `sudo journalctl -u museum-dashboard -f` |

### Web interfaces

| URL | Purpose |
|-----|---------|
| `http://<pi-ip>:5000` | Live dashboard + threshold controls (FastAPI) |
| `http://<pi-ip>:3000` | Grafana charts (admin/admin) |
| `http://<pi-ip>:8086` | InfluxDB admin |

### Monitor MQTT messages
```bash
mosquitto_sub -h localhost -t "museum/#" -v
```

---

## Calibration

The BME280 is factory-calibrated — no offset adjustment is needed for typical
museum environments. If you notice a consistent offset (e.g., compared to a
calibrated reference thermometer):

1. Note the offset (e.g., +0.8°C)
2. Edit `src/sensor_reader.py` → `read_bme280()` → subtract the offset from `data.temperature`
3. Restart the sensor service

---

## Verification & Testing

```bash
# Confirm both sensors are detected on the I2C bus
python3 scripts/test_sensors.py

# Test buzzer and fan relay
python3 scripts/test_actuators.py

# Force a threshold breach for acceptance testing
python3 scripts/force_alert.py temperature
python3 scripts/force_alert.py humidity
python3 scripts/force_alert.py light
```

---

## Acceptance Criteria

- [x] Logs data continuously (systemd auto-restarts on crash)
- [x] Detects temperature breach → buzzer + fan + email
- [x] Detects humidity breach  → buzzer + fan + email
- [x] Detects light breach     → buzzer + email
- [x] Auto-recovery when readings return to safe range
- [x] Grafana dashboard with real-time charts
- [x] FastAPI dashboard for threshold adjustment without restart
- [x] All data published over MQTT (verify with `mosquitto_sub -t "museum/#" -v`)

---

## Project Structure

```
museum_climate_control/
├── PROJECT_PLAN.md       # Task plan, GPIO diagram, architecture
├── HARDWARE.md           # Detailed wiring and parts list
├── README.md             # This file
├── install.sh            # One-shot installer
├── config/
│   ├── thresholds.json   # Safe range values (curator-editable)
│   └── settings.json     # MQTT, InfluxDB, email, GPIO config
├── src/
│   ├── config.py         # Config loader
│   ├── sensor_reader.py  # BME280 + BH1750
│   ├── mqtt_client.py    # MQTT wrapper
│   ├── actuators.py      # Buzzer + relay
│   ├── influx_writer.py  # InfluxDB writer
│   ├── notifier.py       # Email alerts
│   ├── main.py           # Main sensor loop
│   └── dashboard/
│       ├── app.py        # FastAPI dashboard
│       ├── templates/
│       │   └── index.html
│       └── static/
│           └── style.css
└── scripts/
    ├── test_sensors.py   # Hardware verification
    ├── test_actuators.py # Buzzer + fan test
    └── force_alert.py    # Force breach for demo
```
