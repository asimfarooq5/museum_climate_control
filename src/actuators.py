import time
import logging

logger = logging.getLogger(__name__)

try:
    import RPi.GPIO as GPIO
    _MOCK = False
except (ImportError, RuntimeError):
    logger.warning("RPi.GPIO unavailable — running in simulation mode")
    _MOCK = True

from config import Config

_CFG              = Config.settings["gpio"]
BUZZER_PIN        = _CFG["buzzer_pin"]
FAN_RELAY_PIN     = _CFG["relay_fan_pin"]
HUMIDIFIER_PIN    = _CFG.get("relay_humidifier_pin", 22)
BLIND_RELAY_PIN   = _CFG.get("relay_blind_pin",   24)
RELAY_ACTIVE_LOW  = _CFG["relay_active_low"]
BUZZER_ACTIVE_HIGH = _CFG.get("buzzer_active_high", True)

if not _MOCK:
    _RELAY_ON  = GPIO.LOW  if RELAY_ACTIVE_LOW else GPIO.HIGH
    _RELAY_OFF = GPIO.HIGH if RELAY_ACTIVE_LOW else GPIO.LOW
    _BUZZER_ON  = GPIO.HIGH if BUZZER_ACTIVE_HIGH else GPIO.LOW
    _BUZZER_OFF = GPIO.LOW  if BUZZER_ACTIVE_HIGH else GPIO.HIGH
else:
    _RELAY_ON  = 0
    _RELAY_OFF = 1
    _BUZZER_ON  = 1 if BUZZER_ACTIVE_HIGH else 0
    _BUZZER_OFF = 0 if BUZZER_ACTIVE_HIGH else 1

_mock_state: dict[str, int] = {}


def _gpio_setup(pin, initial):
    if _MOCK:
        _mock_state[pin] = initial
    else:
        GPIO.setup(pin, GPIO.OUT, initial=initial)


def _gpio_output(pin, level):
    if _MOCK:
        _mock_state[pin] = level
    else:
        GPIO.output(pin, level)


def _gpio_input(pin) -> int:
    if _MOCK:
        return _mock_state.get(pin, _RELAY_OFF)
    return GPIO.input(pin)


def setup():
    if not _MOCK:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
    _gpio_setup(BUZZER_PIN,      _BUZZER_OFF)
    _gpio_setup(FAN_RELAY_PIN,   _RELAY_OFF)
    _gpio_setup(HUMIDIFIER_PIN,  _RELAY_OFF)
    _gpio_setup(BLIND_RELAY_PIN, _RELAY_OFF)
    logger.info("GPIO initialised (mock=%s)", _MOCK)


def cleanup():
    buzzer_off()
    fan_off()
    humidifier_off()
    blind_open()
    if not _MOCK:
        GPIO.cleanup()


def buzzer_on():
    _gpio_output(BUZZER_PIN, _BUZZER_ON)

def buzzer_off():
    _gpio_output(BUZZER_PIN, _BUZZER_OFF)

def buzzer_beep(duration: float = 1.0):
    buzzer_on()
    time.sleep(duration)
    buzzer_off()


def fan_on():
    _gpio_output(FAN_RELAY_PIN, _RELAY_ON)

def fan_off():
    _gpio_output(FAN_RELAY_PIN, _RELAY_OFF)

def fan_state() -> str:
    return "on" if _gpio_input(FAN_RELAY_PIN) == _RELAY_ON else "off"


def humidifier_on():
    _gpio_output(HUMIDIFIER_PIN, _RELAY_ON)

def humidifier_off():
    _gpio_output(HUMIDIFIER_PIN, _RELAY_OFF)

def humidifier_state() -> str:
    return "on" if _gpio_input(HUMIDIFIER_PIN) == _RELAY_ON else "off"


def blind_close():
    _gpio_output(BLIND_RELAY_PIN, _RELAY_ON)

def blind_open():
    _gpio_output(BLIND_RELAY_PIN, _RELAY_OFF)

def blind_state() -> str:
    return "closed" if _gpio_input(BLIND_RELAY_PIN) == _RELAY_ON else "open"


if __name__ == "__main__":
    setup()
    try:
        print("Buzzer — 2 short beeps ...")
        buzzer_beep(0.5); time.sleep(0.4); buzzer_beep(0.5)
        print("Fan — ON 2 s ...")
        fan_on(); time.sleep(2); fan_off()
        print("Humidifier — ON 2 s ...")
        humidifier_on(); time.sleep(2); humidifier_off()
        print("Blind — CLOSE 2 s then OPEN ...")
        blind_close(); time.sleep(2); blind_open()
        print("All actuator tests passed.")
    finally:
        cleanup()
