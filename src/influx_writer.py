import logging
from datetime import datetime, timezone
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from config import Config

logger = logging.getLogger(__name__)

_CFG = Config.settings["influxdb"]


class InfluxWriter:
    def __init__(self):
        self._client    = None
        self._write_api = None

    def __enter__(self):
        self._client = InfluxDBClient(
            url=_CFG["url"],
            token=_CFG["token"],
            org=_CFG["org"],
        )
        self._write_api = self._client.write_api(write_options=SYNCHRONOUS)
        return self

    def __exit__(self, *_):
        if self._client:
            self._client.close()

    def write(self, temperature: float, humidity: float,
              pressure: float, light: float):
        point = (
            Point(_CFG["measurement"])
            .tag("location",  _CFG["location"])
            .tag("sensor_id", "bme280_bh1750")
            .field("temperature", temperature)
            .field("humidity",    humidity)
            .field("pressure",    pressure)
            .field("light",       light)
            .time(datetime.now(timezone.utc), "s")
        )
        try:
            self._write_api.write(
                bucket=_CFG["bucket"],
                org=_CFG["org"],
                record=point,
            )
            logger.debug("InfluxDB write OK — temp=%.1f hum=%.1f lux=%.1f",
                         temperature, humidity, light)
        except Exception as exc:
            logger.error("InfluxDB write failed: %s", exc)
