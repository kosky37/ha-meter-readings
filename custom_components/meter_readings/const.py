from homeassistant.const import UnitOfEnergy, UnitOfVolume

DOMAIN = "meter_readings"
STORAGE_VERSION = 1

CONF_METER_TYPE = "meter_type"
CONF_UNIT = "unit"
CONF_STATISTIC_ID = "statistic_id"
CONF_PRICE_PER = "price_per"

PRICE_PER_UNIT = "unit"
PRICE_PER_KWH = "kwh"
PRICE_PER_OPTIONS = [PRICE_PER_UNIT, PRICE_PER_KWH]

ATTR_METER = "meter"
ATTR_VALUE = "value"
ATTR_TIMESTAMP = "timestamp"
ATTR_NEW_TIMESTAMP = "new_timestamp"
ATTR_READINGS = "readings"
ATTR_REPLACE = "replace"
ATTR_DELETE = "delete"
ATTR_READING = "reading"
ATTR_PRICE = "price"
ATTR_FACTOR = "factor"
ATTR_VALID_FROM = "valid_from"

METER_GAS = "gas"
METER_WATER = "water"
METER_TYPES = [METER_GAS, METER_WATER]

UNITS = {
    METER_GAS: [
        UnitOfVolume.CUBIC_METERS,
        UnitOfVolume.CUBIC_FEET,
        UnitOfEnergy.KILO_WATT_HOUR,
    ],
    METER_WATER: [
        UnitOfVolume.CUBIC_METERS,
        UnitOfVolume.LITERS,
        UnitOfVolume.CUBIC_FEET,
        UnitOfVolume.GALLONS,
    ],
}
ALL_UNITS = list(dict.fromkeys(unit for units in UNITS.values() for unit in units))

SIGNAL_UPDATED = "meter_readings_updated_{}"


def storage_key(entry_id: str) -> str:
    return f"{DOMAIN}.{entry_id}"
