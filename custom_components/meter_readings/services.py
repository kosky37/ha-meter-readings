from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_FACTOR,
    ATTR_METER,
    ATTR_NEW_TIMESTAMP,
    ATTR_PRICE,
    ATTR_READINGS,
    ATTR_REPLACE,
    ATTR_TIMESTAMP,
    ATTR_VALID_FROM,
    ATTR_VALUE,
    DOMAIN,
)
from .meter import MeterData, parse_readings

VALUE = vol.All(vol.Coerce(float), vol.Range(min=0))

METER_SCHEMA = vol.Schema({vol.Required(ATTR_METER): cv.entity_id})

ADD_SCHEMA = METER_SCHEMA.extend(
    {
        vol.Required(ATTR_VALUE): VALUE,
        vol.Optional(ATTR_TIMESTAMP): cv.datetime,
    }
)

IMPORT_SCHEMA = METER_SCHEMA.extend(
    {
        vol.Required(ATTR_READINGS): cv.string,
        vol.Optional(ATTR_REPLACE, default=False): cv.boolean,
    }
)

UPDATE_SCHEMA = METER_SCHEMA.extend(
    {
        vol.Required(ATTR_TIMESTAMP): cv.datetime,
        vol.Optional(ATTR_VALUE): VALUE,
        vol.Optional(ATTR_NEW_TIMESTAMP): cv.datetime,
    }
)

DELETE_SCHEMA = METER_SCHEMA.extend({vol.Required(ATTR_TIMESTAMP): cv.datetime})

SET_PRICE_SCHEMA = METER_SCHEMA.extend(
    {
        vol.Optional(ATTR_PRICE): VALUE,
        vol.Optional(ATTR_FACTOR): vol.All(vol.Coerce(float), vol.Range(min=0, min_included=False)),
        vol.Optional(ATTR_VALID_FROM): cv.datetime,
    }
)

DELETE_PRICE_SCHEMA = METER_SCHEMA.extend({vol.Required(ATTR_VALID_FROM): cv.datetime})


def _meter(hass: HomeAssistant, call: ServiceCall) -> MeterData:
    entity_id = call.data[ATTR_METER]
    entity = er.async_get(hass).async_get(entity_id)
    if entity is None or entity.platform != DOMAIN or entity.config_entry_id is None:
        raise ServiceValidationError(f"{entity_id} is not a meter readings entity")
    entry = hass.config_entries.async_get_entry(entity.config_entry_id)
    if entry is None or entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(f"The meter of {entity_id} is not loaded")
    return entry.runtime_data


@callback
def async_register_services(hass: HomeAssistant) -> None:
    async def add_reading(call: ServiceCall) -> None:
        await _meter(hass, call).async_add(
            call.data.get(ATTR_TIMESTAMP, dt_util.utcnow()), call.data[ATTR_VALUE]
        )

    async def import_readings(call: ServiceCall) -> ServiceResponse:
        meter = _meter(hass, call)
        count = await meter.async_import(
            parse_readings(call.data[ATTR_READINGS]), call.data[ATTR_REPLACE]
        )
        return {"imported": count, "total": len(meter.readings)}

    async def update_reading(call: ServiceCall) -> None:
        if ATTR_VALUE not in call.data and ATTR_NEW_TIMESTAMP not in call.data:
            raise ServiceValidationError("Provide a new value or a new timestamp")
        await _meter(hass, call).async_update(
            call.data[ATTR_TIMESTAMP],
            call.data.get(ATTR_VALUE),
            call.data.get(ATTR_NEW_TIMESTAMP),
        )

    async def delete_reading(call: ServiceCall) -> None:
        await _meter(hass, call).async_delete(call.data[ATTR_TIMESTAMP])

    async def get_readings(call: ServiceCall) -> ServiceResponse:
        meter = _meter(hass, call)
        return {
            "meter": meter.entry.title,
            "unit": meter.unit,
            "statistic_id": meter.statistic_id,
            "readings": [
                {
                    "timestamp": dt_util.as_local(r.timestamp).isoformat(),
                    "value": r.value,
                }
                for r in meter.readings
            ],
            "price_unit": meter.price_unit,
            "prices": [
                {
                    "valid_from": dt_util.as_local(p.valid_from).isoformat(),
                    "price": p.price,
                    "factor": p.factor,
                    "unit_price": p.unit_price,
                }
                for p in meter.prices
            ],
            "total_cost": meter.total_cost,
        }

    async def set_price(call: ServiceCall) -> None:
        if ATTR_PRICE not in call.data and ATTR_FACTOR not in call.data:
            raise ServiceValidationError("Provide a price or a conversion factor")
        await _meter(hass, call).async_set_price(
            call.data.get(ATTR_VALID_FROM, dt_util.utcnow()),
            call.data.get(ATTR_PRICE),
            call.data.get(ATTR_FACTOR),
        )

    async def delete_price(call: ServiceCall) -> None:
        await _meter(hass, call).async_delete_price(call.data[ATTR_VALID_FROM])

    async def rebuild_statistics(call: ServiceCall) -> None:
        _meter(hass, call).async_rebuild_statistics()

    hass.services.async_register(DOMAIN, "add_reading", add_reading, ADD_SCHEMA)
    hass.services.async_register(
        DOMAIN,
        "import_readings",
        import_readings,
        IMPORT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "update_reading", update_reading, UPDATE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "delete_reading", delete_reading, DELETE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        "get_readings",
        get_readings,
        METER_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(DOMAIN, "set_price", set_price, SET_PRICE_SCHEMA)
    hass.services.async_register(
        DOMAIN, "delete_price", delete_price, DELETE_PRICE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "rebuild_statistics", rebuild_statistics, METER_SCHEMA
    )
