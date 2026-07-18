# Smart Museum Preservation System

ECMC104 IIOT for Advanced Manufacturing

A Raspberry Pi IoT system that monitors temperature, humidity, light, and
pressure in a museum environment. Alerts the curator and activates actuators
(fan, buzzer, humidifier, motorized blind) when readings drift outside safe
conservation ranges.

---

## Quick Start — Demo on a Fresh Raspberry Pi

### 1. Clone & install

```bash
git clone https://github.com/asimfarooq5/museum_climate_control.git
cd museum_climate_control
bash install.sh
```

The installer does everything automatically:
- Enables I2C
- Installs Python packages (RPi.GPIO, smbus2, bme280, paho-mqtt, fastapi, etc.)
- Installs & starts Mosquitto MQTT broker
- Installs & starts InfluxDB 2.x
- Creates `museum-sensors` and `museum-dashboard` systemd services

> **Takes ~5 minutes.** The Pi will reboot once at the end if I2C was just enabled.

### 2. Verify it's running

```bash
# Check sensor readings
curl -s http://localhost:5000/api/readings | python3 -m json.tool

# View live logs
sudo journalctl -u museum-sensors -f
```

### 3. Open the dashboard

```
http://<pi-ip-address>:5000
```

---

## Manual Step-by-Step (if install.sh fails or you want to do it yourself)

### Step 1 — System setup

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv python3-smbus i2c-tools mosquitto mosquitto-clients curl wget
sudo raspi-config nonint do_i2c 0
```

### Step 2 — Python environment

```bash
cd museum_climate_control
python3 -m venv venv
source venv/bin/activate
pip install RPi.GPIO smbus2 RPi.bme280 "paho-mqtt>=1.6,<2" "influxdb-client>=1.36" "fastapi>=0.100" "uvicorn[standard]>=0.23" "jinja2>=3.1" python-multipart
```

### Step 3 — MQTT broker

```bash
sudo tee /etc/mosquitto/conf.d/museum.conf > /dev/null <<'EOF'
listener 1883
allow_anonymous true
EOF
sudo systemctl enable --now mosquitto
sudo systemctl restart mosquitto
```

### Step 4 — InfluxDB

```bash
# Download & install
wget -q -O /tmp/influxdb.deb https://dl.influxdata.com/influxdb/releases/influxdb2-2.7.1-arm64.deb
sudo dpkg -i /tmp/influxdb.deb
sudo systemctl enable --now influxdb

# Wait for it to start, then create org + bucket
sleep 10
curl -s -X POST http://localhost:8086/api/v2/setup \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"museum2024","org":"museum","bucket":"museum_climate"}'

# Get the token from the response and paste it into config/settings.json → influxdb.token
```

### Step 5 — Start services

```bash
# Start sensor loop (with simulation mode for testing)
cd museum_climate_control
SIMULATE=true venv/bin/python3 src/main.py &

# Start dashboard
venv/bin/python3 -m uvicorn dashboard.app:app --host 0.0.0.0 --port 5000 &
```

### Step 6 — (Optional) Create systemd services for auto-start

```bash
sudo tee /etc/systemd/system/museum-sensors.service > /dev/null <<EOF
[Unit]
Description=Museum Climate Sensor Loop
After=network.target mosquitto.service influxdb.service

[Service]
ExecStart=$(pwd)/venv/bin/python3 $(pwd)/src/main.py
WorkingDirectory=$(pwd)/src
Restart=always
RestartSec=10
User=$USER
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/museum-dashboard.service > /dev/null <<EOF
[Unit]
Description=Museum Climate Dashboard
After=network.target mosquitto.service

[Service]
ExecStart=$(pwd)/venv/bin/python3 -m uvicorn dashboard.app:app --host 0.0.0.0 --port 5000
WorkingDirectory=$(pwd)/src
Restart=always
RestartSec=5
User=$USER
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now museum-sensors museum-dashboard
```

---

## Hardware Wiring

| Component | Pi Pin | GPIO |
|-----------|--------|------|
| BME280 VCC | Pin 1 (3.3V) | — |
| BME280 SDA | Pin 3 | GPIO2 |
| BME280 SCL | Pin 5 | GPIO3 |
| BME280 GND | Pin 6 | GND |
| BH1750 VCC | Pin 1 (3.3V) | — |
| BH1750 SDA | Pin 3 | GPIO2 |
| BH1750 SCL | Pin 5 | GPIO3 |
| BH1750 GND | Pin 9 | GND |
| BH1750 ADDR | Pin 9 (GND) | — (0x23) |
| Buzzer + | Pin 11 | GPIO17 |
| Buzzer - | Pin 9 | GND |
| Relay VCC | Pin 2 (5V) | — |
| Relay IN | Pin 13 | GPIO27 |
| Relay GND | Pin 14 | GND |
| Humidifier Relay IN | Pin 15 | GPIO22 |
| Blind Relay IN | Pin 18 | GPIO24 |
| LED Green + | Pin 29 | GPIO5 |
| LED Red + | Pin 31 | GPIO6 |
| LED GND | Pin 30 | GND |

---

## Demo Script — For Your Teacher

### What to show

1. **Dashboard** — open `http://<pi-ip>:5000` — show live sensor cards and charts
2. **Thresholds** — click "Thresholds" in nav, edit a value, save
3. **Hardware Test** — click "Hardware Test", pause sensing, test fan/buzzer
4. **Alerts** — force a breach:

```bash
cd museum_climate_control
SIMULATE=true venv/bin/python3 scripts/force_alert.py temperature
```

This temporarily sets the temperature max below the current reading.
Watch the dashboard — cards turn red, buzzer beeps, alert appears.

5. **Recovery** — after 30 seconds thresholds restore, alerts clear, buzzer stops.

### Acceptance criteria checklist

- [ ] Temperature/humidity/light/pressure displayed on dashboard
- [ ] Charts show 1-hour history
- [ ] Fan turns on/off from hardware test page
- [ ] Buzzer beeps from hardware test page
- [ ] Threshold editor saves changes
- [ ] Alert card turns red + animation on breach
- [ ] Alert appears in Recent Alerts table
- [ ] MQTT messages visible: `mosquitto_sub -t "museum/#" -v`

---

## Project Structure

```
museum_climate_control/
├── src/              # Python source code
│   ├── main.py       # Main sensor loop — run this
│   ├── config.py     # Configuration loader
│   ├── sensor_reader.py  # BME280 + BH1750 reading
│   ├── actuators.py  # GPIO control (fan, buzzer, etc.)
│   ├── mqtt_client.py    # MQTT publish/subscribe
│   ├── influx_writer.py  # InfluxDB writer
│   ├── notifier.py   # Email/SMS alerts
│   └── dashboard/    # FastAPI web dashboard
│       ├── app.py
│       ├── templates/  # Jinja2 HTML
│       └── static/     # CSS + Chart.js
├── config/           # JSON config files
├── scripts/          # Test & utility scripts
├── grafana/          # Grafana dashboard export
├── install.sh        # One-shot installer
├── pyproject.toml    # Python package metadata
└── README.md         # This file
```
