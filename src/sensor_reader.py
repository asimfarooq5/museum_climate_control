import os
import time
import math
import logging
import random

logger = logging.getLogger(__name__)

try:
    import smbus2
    import bme280
    _HW_AVAILABLE = True
except ImportError:
    _HW_AVAILABLE = False

from config import Config

_I2C_BUS        = Config.settings["i2c"]["bus"]
_BME280_ADDR    = int(Config.settings["i2c"]["bme280_address"], 16)
_BH1750_ADDR    = int(Config.settings["i2c"]["bh1750_address"], 16)
_SIMULATE       = os.environ.get("SIMULATE", "").lower() in ("1", "true", "yes")

_BH1750_CONT_H_RES = 0x10

_BMx280_CHIP_ID_REG = 0xD0
_BME280_CHIP_ID     = 0x60
_BMP280_CHIP_IDS    = (0x56, 0x57, 0x58)


def _init_bme280(bus):
    return bme280.load_calibration_params(bus, _BME280_ADDR)


def _is_bme280(bus) -> bool:
    try:
        chip_id = bus.read_byte_data(_BME280_ADDR, _BMx280_CHIP_ID_REG)
        if chip_id in _BMP280_CHIP_IDS:
            logger.warning(
                "Chip ID 0x%02X at 0x%02X is BMP280 (no humidity sensor). "
                "Humidity will be simulated.", chip_id, _BME280_ADDR)
            return False
        return True
    except Exception:
        return True


def _read_bme280(bus, calibration) -> dict:
    data = bme280.sample(bus, _BME280_ADDR, calibration)
    return {
        "temperature": round(data.temperature, 2),
        "humidity":    round(data.humidity,    2),
        "pressure":    round(data.pressure,    2),
    }


def _read_bh1750(bus) -> float:
    bus.write_byte(_BH1750_ADDR, _BH1750_CONT_H_RES)
    time.sleep(0.18)
    data = bus.read_i2c_block_data(_BH1750_ADDR, 0, 2)
    return round((data[0] << 8 | data[1]) / 1.2, 1)


_sim_t   = 21.0
_sim_rh  = 52.0
_sim_lux = 120.0
_sim_hpa = 1013.0


def _sim_step():
    global _sim_t, _sim_rh, _sim_lux, _sim_hpa

    t_now = time.time()
    phase = t_now / 120.0

    _sim_t   = 21.0  + 3.5 * math.sin(phase)           + random.uniform(-0.3, 0.3)
    _sim_rh  = 52.0  + 10.0 * math.sin(phase + 2.0)    + random.uniform(-0.5, 0.5)
    _sim_lux = 150.0 + 70.0  * abs(math.sin(phase * 0.7)) + random.uniform(-5, 5)
    _sim_hpa = 1013.0 + 3.0  * math.sin(phase * 0.3)   + random.uniform(-0.5, 0.5)

    return {
        "temperature": round(_sim_t,   2),
        "humidity":    round(_sim_rh,  2),
        "pressure":    round(_sim_hpa, 2),
        "light":       round(max(0, _sim_lux), 1),
    }


class SensorReader:
    def __init__(self):
        self._bus        = None
        self._calib      = None
        self._mock       = False
        self._has_bh1750 = False
        self._has_hum    = True

    def __enter__(self):
        if _SIMULATE or not _HW_AVAILABLE:
            self._mock = True
            logger.warning("Sensor simulation mode active (SIMULATE env or hardware absent)")
            return self

        try:
            self._bus   = smbus2.SMBus(_I2C_BUS)
            self._calib = _init_bme280(self._bus)
            self._has_hum = _is_bme280(self._bus)
            logger.info("%s initialised at 0x%02X on I2C bus %d",
                        "BME280" if self._has_hum else "BMP280",
                        _BME280_ADDR, _I2C_BUS)
        except Exception as exc:
            logger.warning("BMx280 not available (%s) — falling back to simulation", exc)
            if self._bus:
                self._bus.close()
                self._bus = None
            self._mock = True
            return self

        try:
            self._bus.write_byte(_BH1750_ADDR, _BH1750_CONT_H_RES)
            self._has_bh1750 = True
            logger.info("BH1750 initialised at 0x%02X on I2C bus %d",
                        _BH1750_ADDR, _I2C_BUS)
        except Exception as exc:
            logger.warning("BH1750 not detected at 0x%02X (%s) — light channel simulated",
                           _BH1750_ADDR, exc)

        return self

    def __exit__(self, *_):
        if self._bus:
            self._bus.close()

    def read_all(self) -> dict:
        if self._mock:
            readings = _sim_step()
            logger.debug("[SIM] %s", readings)
            return readings

        env = _read_bme280(self._bus, self._calib)

        if not self._has_hum:
            env["humidity"] = round(52.0 + 10.0 * math.sin(time.time() / 300.0), 1)

        if self._has_bh1750:
            env["light"] = _read_bh1750(self._bus)
        else:
            env["light"] = round(150.0 + 70.0 * abs(math.sin(time.time() / 120.0)), 1)
        return env


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Testing sensors (5 samples) ...\n")
    with SensorReader() as sr:
        for i in range(5):
            r = sr.read_all()
            print(f"[{i+1}] Temp={r['temperature']:5.2f}°C  "
                  f"Hum={r['humidity']:5.2f}%  "
                  f"Press={r['pressure']:7.2f} hPa  "
                  f"Light={r['light']:6.1f} lux")
            time.sleep(2)
