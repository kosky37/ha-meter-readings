from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, METER_GAS
from .meter import MeterData


class MeterEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, meter: MeterData, key: str) -> None:
        self._meter = meter
        self._attr_unique_id = f"{meter.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, meter.entry.entry_id)},
            name=meter.entry.title,
            manufacturer="Manual readings",
            model="Gas meter" if meter.meter_type == METER_GAS else "Water meter",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, self._meter.signal, self.async_write_ha_state
            )
        )
