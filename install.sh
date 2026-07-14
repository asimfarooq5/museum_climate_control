#!/bin/bash
# One-shot installer for Museum Climate Control System
# Run as the pi user: bash install.sh
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$REPO_DIR/venv"
PI_USER="${SUDO_USER:-$USER}"

echo "=========================================="
echo " Museum Climate Control — Installer"
echo " Repo: $REPO_DIR"
echo "=========================================="

# ── 1. System packages ──────────────────────────────────────────────────────
echo ""
echo "[1/6] Installing system packages ..."
sudo apt-get update -q
sudo apt-get install -y -q \
    python3 python3-pip python3-venv python3-smbus \
    i2c-tools mosquitto mosquitto-clients \
    curl wget

# ── 2. I2C ──────────────────────────────────────────────────────────────────
echo ""
echo "[2/6] Enabling I2C ..."
sudo raspi-config nonint do_i2c 0
grep -qxF 'dtparam=i2c_arm=on' /boot/firmware/config.txt 2>/dev/null || \
    echo 'dtparam=i2c_arm=on' | sudo tee -a /boot/firmware/config.txt
echo "I2C enabled."

# ── 3. Python venv ──────────────────────────────────────────────────────────
echo ""
echo "[3/6] Setting up Python virtual environment ..."
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet \
    RPi.GPIO \
    smbus2 \
    "RPi.bme280" \
    "paho-mqtt>=1.6,<2" \
    "influxdb-client>=1.36" \
    "fastapi>=0.100" \
    "uvicorn[standard]>=0.23" \
    "jinja2>=3.1" \
    "python-multipart"
echo "Venv ready: $VENV"

# ── 4. Mosquitto ────────────────────────────────────────────────────────────
echo ""
echo "[4/6] Configuring Mosquitto MQTT broker ..."
sudo tee /etc/mosquitto/conf.d/museum.conf > /dev/null <<'EOF'
listener 1883
allow_anonymous true
EOF
sudo systemctl enable mosquitto
sudo systemctl restart mosquitto
echo "Mosquitto running on port 1883."

# ── 5. InfluxDB ─────────────────────────────────────────────────────────────
echo ""
echo "[5/6] Setting up InfluxDB 2.x ..."
if ! command -v influx &>/dev/null; then
    ARCH=$(dpkg --print-architecture)  # arm64 on Pi 4/5
    INFLUX_DEB="influxdb2-2.7.1-${ARCH}.deb"
    wget -q -O /tmp/influxdb.deb \
        "https://dl.influxdata.com/influxdb/releases/${INFLUX_DEB}"
    sudo dpkg -i /tmp/influxdb.deb
    rm /tmp/influxdb.deb
fi

# Ensure InfluxDB uses /var/lib/influxdb (not root home)
if [ ! -f /etc/influxdb/config.toml ]; then
    sudo mkdir -p /etc/influxdb
    sudo tee /etc/influxdb/config.toml > /dev/null <<'EOF'
bolt-path   = "/var/lib/influxdb/influxd.bolt"
engine-path = "/var/lib/influxdb/engine"
sqlite-path = "/var/lib/influxdb/influxd.sqlite"
http-bind-address = ":8086"
reporting-disabled = true
EOF
    sudo chown -R influxdb:influxdb /var/lib/influxdb
fi
sudo systemctl enable influxdb
sudo systemctl restart influxdb

# Wait for InfluxDB to be ready then auto-setup
echo "Waiting for InfluxDB ..."
for i in $(seq 1 15); do
    if curl -s http://localhost:8086/health | grep -q '"status":"pass"'; then
        break
    fi
    sleep 2
done

INFLUX_SETUP=$(curl -s http://localhost:8086/api/v2/setup)
if echo "$INFLUX_SETUP" | grep -q '"allowed":true'; then
    echo "Running InfluxDB initial setup ..."
    SETUP_RESP=$(curl -s -X POST http://localhost:8086/api/v2/setup \
        -H 'Content-Type: application/json' \
        -d '{"username":"admin","password":"museum2024","org":"museum","bucket":"museum_climate","retentionPeriodSeconds":0}')
    TOKEN=$(echo "$SETUP_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['auth']['token'])" 2>/dev/null || echo "")
    if [ -n "$TOKEN" ]; then
        echo "InfluxDB configured. Updating settings.json with token ..."
        python3 - "$TOKEN" "$REPO_DIR/config/settings.json" <<'PYEOF'
import sys, json
token, path = sys.argv[1], sys.argv[2]
cfg = json.load(open(path))
cfg['influxdb']['token'] = token
json.dump(cfg, open(path, 'w'), indent=2)
PYEOF
        echo "Token saved to config/settings.json."
    fi
else
    echo "InfluxDB already configured (skipping setup)."
fi
echo "InfluxDB running on port 8086."

# ── 6. Systemd services ──────────────────────────────────────────────────────
echo ""
echo "[6/6] Installing systemd services ..."

sudo tee /etc/systemd/system/museum-sensors.service > /dev/null <<EOF
[Unit]
Description=Museum Climate Sensor Loop
After=network.target mosquitto.service influxdb.service

[Service]
ExecStart=${VENV}/bin/python3 ${REPO_DIR}/src/main.py
WorkingDirectory=${REPO_DIR}/src
Restart=always
RestartSec=10
User=${PI_USER}
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
ExecStart=${VENV}/bin/python3 -m uvicorn dashboard.app:app --host 0.0.0.0 --port 5000
WorkingDirectory=${REPO_DIR}/src
Restart=always
RestartSec=5
User=${PI_USER}
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable museum-sensors museum-dashboard
sudo systemctl restart museum-sensors museum-dashboard

echo ""
echo "=========================================="
echo " Installation complete!"
echo "=========================================="
echo ""
IP=$(hostname -I | awk '{print $1}')
echo "  Dashboard  → http://${IP}:5000"
echo "  Test page  → http://${IP}:5000/test"
echo "  InfluxDB   → http://${IP}:8086"
echo ""
echo "  View logs:"
echo "    sudo journalctl -u museum-sensors -f"
echo "    sudo journalctl -u museum-dashboard -f"
echo ""
echo "  Quick test:"
echo "    cd $REPO_DIR && make test-sensors"
echo "    cd $REPO_DIR && make test-actuators"
echo ""
