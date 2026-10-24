from __future__ import annotations

from homeassistant.components.recorder import get_instance
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import CONF_STATISTIC_ID, DOMAIN, STORAGE_VERSION, storage_key
from .meter import MeterData
from .services import async_register_services

PLATFORMS = [Platform.SENSOR, Platform.NUMBER]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type MeterConfigEntry = ConfigEntry[MeterData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: MeterConfigEntry) -> bool:
    meter = MeterData(hass, entry)
    await meter.async_load()
    entry.runtime_data = meter
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MeterConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: MeterConfigEntry) -> None:
    get_instance(hass).async_clear_statistics([entry.data[CONF_STATISTIC_ID]])
    await Store(hass, STORAGE_VERSION, storage_key(entry.entry_id)).async_remove()
