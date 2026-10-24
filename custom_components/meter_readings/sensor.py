from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import MeterConfigEntry
from .const import METER_GAS
from .entity import MeterEntity
from .meter import MeterData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MeterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    meter = entry.runtime_data
    async_add_entities(
        [
            MeterValueSensor(meter),
            MeterLastReadingSensor(meter),
            MeterUnitPriceSensor(meter),
            MeterTotalCostSensor(meter),
        ]
    )


class MeterValueSensor(MeterEntity, SensorEntity):
    _attr_name = None
    _attr_suggested_display_precision = 3

    def __init__(self, meter: MeterData) -> None:
        super().__init__(meter, "value")
        self._attr_device_class = (
            SensorDeviceClass.GAS
            if meter.meter_type == METER_GAS
            else SensorDeviceClass.WATER
        )
        self._attr_native_unit_of_measurement = meter.unit

    @property
    def native_value(self) -> float | None:
        latest = self._meter.latest
        return latest.value if latest else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        latest = self._meter.latest
        return {
            "last_reading": dt_util.as_local(latest.timestamp).isoformat()
            if latest
            else None,
            "readings": len(self._meter.readings),
            "statistic_id": self._meter.statistic_id,
            "cost_statistic_id": self._meter.cost_statistic_id,
        }


class MeterLastReadingSensor(MeterEntity, SensorEntity):
    _attr_translation_key = "last_reading"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, meter: MeterData) -> None:
        super().__init__(meter, "last_reading")

    @property
    def native_value(self) -> datetime | None:
        latest = self._meter.latest
        return latest.timestamp if latest else None


class MeterUnitPriceSensor(MeterEntity, SensorEntity):
    _attr_translation_key = "unit_price"
    _attr_suggested_display_precision = 4

    def __init__(self, meter: MeterData) -> None:
        super().__init__(meter, "unit_price")
        self._attr_native_unit_of_measurement = meter.unit_price_unit

    @property
    def native_value(self) -> float | None:
        price = self._meter.current_price
        return round(price.unit_price, 6) if price else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        price = self._meter.current_price
        if price is None:
            return {}
        return {
            "price": price.price,
            "price_unit": self._meter.price_unit,
            "factor": price.factor,
            "valid_from": dt_util.as_local(price.valid_from).isoformat(),
        }


class MeterTotalCostSensor(MeterEntity, SensorEntity):
    _attr_translation_key = "total_cost"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_suggested_display_precision = 2

    def __init__(self, meter: MeterData) -> None:
        super().__init__(meter, "total_cost")
        self._attr_native_unit_of_measurement = meter.currency

    @property
    def native_value(self) -> float | None:
        return self._meter.total_cost
