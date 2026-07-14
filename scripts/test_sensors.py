import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sensor_reader import SensorReader
import time

print("Scanning I2C bus for devices ...")
os.system("i2cdetect -y 1")
print()

print("Reading sensors (5 samples at 2 s intervals) ...\n")
with SensorReader() as sr:
    for i in range(5):
        r = sr.read_all()
        print(f"[{i+1}] Temp={r['temperature']:5.2f}°C  "
              f"Hum={r['humidity']:5.2f}%  "
              f"Press={r['pressure']:7.2f} hPa  "
              f"Light={r['light']:6.1f} lux")
        time.sleep(2)

print("\nSensor test complete. Check values look plausible.")
