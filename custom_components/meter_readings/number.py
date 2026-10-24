from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
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
    entities: list[NumberEntity] = [
        MeterNewReadingNumber(meter),
        MeterPriceNumber(meter),
    ]
    if meter.uses_factor:
        entities.append(MeterFactorNumber(meter))
    async_add_entities(entities)


class MeterNewReadingNumber(MeterEntity, NumberEntity):
    _attr_translation_key = "new_reading"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 999_999_999
    _attr_native_step = 0.001

    def __init__(self, meter: MeterData) -> None:
        super().__init__(meter, "new_reading")
        self._attr_device_class = (
            NumberDeviceClass.GAS
            if meter.meter_type == METER_GAS
            else NumberDeviceClass.WATER
        )
        self._attr_native_unit_of_measurement = meter.unit

    @property
    def native_value(self) -> float | None:
        latest = self._meter.latest
        return latest.value if latest else None

    async def async_set_native_value(self, value: float) -> None:
        await self._meter.async_add(dt_util.utcnow(), value)


class MeterPriceNumber(MeterEntity, NumberEntity):
    _attr_translation_key = "price"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 100_000
    _attr_native_step = 0.000001

    def __init__(self, meter: MeterData) -> None:
        super().__init__(meter, "price")
        self._attr_native_unit_of_measurement = meter.price_unit

    @property
    def native_value(self) -> float | None:
        price = self._meter.current_price
        return price.price if price else None

    async def async_set_native_value(self, value: float) -> None:
        await self._meter.async_set_price(dt_util.utcnow(), price=value)


class MeterFactorNumber(MeterEntity, NumberEntity):
    _attr_translation_key = "factor"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0.001
    _attr_native_max_value = 1000
    _attr_native_step = 0.001

    def __init__(self, meter: MeterData) -> None:
        super().__init__(meter, "factor")
        self._attr_native_unit_of_measurement = meter.factor_unit

    @property
    def native_value(self) -> float | None:
        price = self._meter.current_price
        return price.factor if price else None

    async def async_set_native_value(self, value: float) -> None:
        await self._meter.async_set_price(dt_util.utcnow(), factor=value)
