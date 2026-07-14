import sys
import os
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from config import load_thresholds, save_thresholds
from sensor_reader import SensorReader

PARAM = sys.argv[1] if len(sys.argv) > 1 else "temperature"

print(f"Force-alert test for: {PARAM}\n")

with SensorReader() as sr:
    readings = sr.read_all()

current_value = readings.get(PARAM)
if current_value is None:
    print(f"Unknown parameter: {PARAM}")
    sys.exit(1)

print(f"Current {PARAM} reading: {current_value}")

originals = load_thresholds()
forced    = load_thresholds()

forced[PARAM]["max"] = round(current_value - 1, 1)
forced[PARAM]["min"] = 0.0
save_thresholds(forced)

print(f"Thresholds temporarily set → max={forced[PARAM]['max']} (breach forced)")
print("Waiting 30 s for main.py to detect and alarm ...\n")
time.sleep(30)

save_thresholds(originals)
print(f"Thresholds restored to original values.")
print("Check logs and MQTT to confirm alarm was triggered.")
