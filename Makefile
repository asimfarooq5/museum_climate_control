VENV     := $(PWD)/venv
PYTHON   := $(VENV)/bin/python3
PI_IP    ?= 192.168.0.218
PI_USER  ?= pi
PI_PASS  ?= 1234
REPO     := /home/pi/museum_climate_control
SSH_KEY  := $(HOME)/.ssh/museum_pi
SSH      := ssh -i $(SSH_KEY) -o StrictHostKeyChecking=no
RSYNC    := rsync -az --progress -e "ssh -i $(SSH_KEY) -o StrictHostKeyChecking=no"

.PHONY: help deploy restart status logs logs-dashboard test-sensors test-actuators \
        stop start enable disable influxdb-setup clean

help:
	@echo ""
	@echo "Museum Climate Control — make targets"
	@echo "--------------------------------------"
	@echo "  make install           Run full installer on Pi"
	@echo "  make deploy            Push code to Pi and restart services"
	@echo "  make restart           Restart both services on Pi"
	@echo "  make start             Start both services"
	@echo "  make stop              Stop both services"
	@echo "  make status            Show service status on Pi"
	@echo "  make logs              Tail museum-sensors log"
	@echo "  make logs-dashboard    Tail museum-dashboard log"
	@echo "  make test-sensors      Run sensor hardware test on Pi"
	@echo "  make test-actuators    Run actuator hardware test on Pi"
	@echo "  make influxdb-setup    (Re)run InfluxDB initial setup"
	@echo "  make clean             Remove local __pycache__ files"
	@echo ""
	@echo "  PI_IP=$(PI_IP)  PI_USER=$(PI_USER)"
	@echo ""

# ── Deploy ──────────────────────────────────────────────────────────────────
deploy:
	@echo "Syncing code to $(PI_USER)@$(PI_IP):$(REPO) ..."
	@$(RSYNC) \
		--exclude '__pycache__' \
		--exclude '*.pyc' \
		--exclude 'venv' \
		--exclude '.git' \
		--exclude '.idea' \
		$(PWD)/src/ $(PI_USER)@$(PI_IP):$(REPO)/src/
	@$(RSYNC) $(PWD)/config/ $(PI_USER)@$(PI_IP):$(REPO)/config/
	@$(SSH) $(PI_USER)@$(PI_IP) "echo '$(PI_PASS)' | sudo -S systemctl restart museum-sensors museum-dashboard 2>/dev/null; sleep 3; systemctl is-active museum-sensors museum-dashboard"
	@echo "Deploy done. Dashboard: http://$(PI_IP):5000"

# ── Service control ─────────────────────────────────────────────────────────
restart:
	$(SSH) $(PI_USER)@$(PI_IP) "echo '$(PI_PASS)' | sudo -S systemctl restart museum-sensors museum-dashboard 2>/dev/null"

start:
	$(SSH) $(PI_USER)@$(PI_IP) "echo '$(PI_PASS)' | sudo -S systemctl start museum-sensors museum-dashboard 2>/dev/null"

stop:
	$(SSH) $(PI_USER)@$(PI_IP) "echo '$(PI_PASS)' | sudo -S systemctl stop museum-sensors museum-dashboard 2>/dev/null"

enable:
	$(SSH) $(PI_USER)@$(PI_IP) "echo '$(PI_PASS)' | sudo -S systemctl enable museum-sensors museum-dashboard 2>/dev/null"

disable:
	$(SSH) $(PI_USER)@$(PI_IP) "echo '$(PI_PASS)' | sudo -S systemctl disable museum-sensors museum-dashboard 2>/dev/null"

status:
	@ssh $(PI_USER)@$(PI_IP) "systemctl status museum-sensors museum-dashboard --no-pager 2>/dev/null"

# ── Logs ────────────────────────────────────────────────────────────────────
logs:
	$(SSH) $(PI_USER)@$(PI_IP) "journalctl -u museum-sensors -f --no-pager 2>/dev/null"

logs-dashboard:
	$(SSH) $(PI_USER)@$(PI_IP) "journalctl -u museum-dashboard -f --no-pager 2>/dev/null"

# ── Hardware tests ───────────────────────────────────────────────────────────
test-sensors:
	$(SSH) $(PI_USER)@$(PI_IP) "cd $(REPO)/src && $(REPO)/venv/bin/python3 sensor_reader.py"

test-actuators:
	$(SSH) $(PI_USER)@$(PI_IP) "cd $(REPO)/src && $(REPO)/venv/bin/python3 actuators.py"

# ── InfluxDB ─────────────────────────────────────────────────────────────────
install:
	$(SSH) $(PI_USER)@$(PI_IP) "cd $(REPO) && bash install.sh"

influxdb-setup:
	@ssh $(PI_USER)@$(PI_IP) 'curl -s http://localhost:8086/api/v2/setup | python3 -c "import sys,json; d=json.load(sys.stdin); print(\"Allowed:\",d.get(\"allowed\"))"'

# ── Local cleanup ────────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.pyc' -delete 2>/dev/null || true
