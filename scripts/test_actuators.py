import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import actuators
import time

actuators.setup()

try:
    print("Testing BUZZER — 2 short beeps ...")
    actuators.buzzer_beep(0.5)
    time.sleep(0.5)
    actuators.buzzer_beep(0.5)
    print("Buzzer OK\n")

    print("Testing FAN RELAY — ON for 3 s ...")
    actuators.fan_on()
    time.sleep(3)
    actuators.fan_off()
    print("Fan relay OK\n")

    print("All actuator tests passed.")
finally:
    actuators.cleanup()
