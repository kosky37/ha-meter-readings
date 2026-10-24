from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, time, timedelta
import re
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    STATISTIC_UNIT_TO_UNIT_CONVERTER,
    async_add_external_statistics,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_METER_TYPE,
    CONF_PRICE_PER,
    CONF_STATISTIC_ID,
    CONF_UNIT,
    DOMAIN,
    PRICE_PER_KWH,
    PRICE_PER_UNIT,
    SIGNAL_UPDATED,
    STORAGE_VERSION,
    storage_key,
)

try:
    from homeassistant.components.recorder.models import StatisticMeanType
except ImportError:
    StatisticMeanType = None

HOUR = timedelta(hours=1)

LINE_PATTERN = re.compile(
    r"^\s*(?P<date>\d{4}-\d{1,2}-\d{1,2}|\d{1,2}\.\d{1,2}\.\d{4})"
    r"(?:[ T](?P<time>\d{1,2}:\d{2}(?::\d{2})?))?"
    r"\s*[,;\t ]\s*(?P<value>\d+(?:[.,]\d+)?)\s*$"
)


@dataclass(frozen=True, order=True, slots=True)
class Reading:
    timestamp: datetime
    value: float


@dataclass(frozen=True, order=True, slots=True)
class Price:
    valid_from: datetime
    price: float
    factor: float | None = None

    @property
    def unit_price(self) -> float:
        return self.price * (self.factor or 1)


def normalize_timestamp(value: datetime | str) -> datetime:
    if isinstance(value, str):
        parsed = dt_util.parse_datetime(value.strip())
        if parsed is None:
            date = dt_util.parse_date(value.strip())
            if date is None:
                raise ServiceValidationError(f"Invalid date: {value}")
            parsed = datetime.combine(date, time())
        value = parsed
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt_util.get_default_time_zone())
    return dt_util.as_utc(value).replace(second=0, microsecond=0)


def format_local(timestamp: datetime) -> str:
    return dt_util.as_local(timestamp).strftime("%Y-%m-%d %H:%M")


def format_value(value: float, decimals: int = 3) -> str:
    return f"{value:.{decimals}f}".rstrip("0").rstrip(".")


def parse_readings(text: str) -> list[Reading]:
    readings: list[Reading] = []
    errors: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if (match := LINE_PATTERN.match(line)) is None:
            errors.append(f"line {number}: cannot read '{line.strip()}'")
            continue
        date = match["date"]
        if "." in date:
            day, month, year = date.split(".")
            date = f"{year}-{month}-{day}"
        year, month, day = (int(part) for part in date.split("-"))
        stamp = f"{year:04d}-{month:02d}-{day:02d} {match['time'] or '00:00'}"
        try:
            timestamp = normalize_timestamp(stamp)
        except ServiceValidationError:
            errors.append(f"line {number}: invalid date '{match['date']}'")
            continue
        readings.append(Reading(timestamp, float(match["value"].replace(",", "."))))
    if errors:
        raise ServiceValidationError("Could not import readings: " + "; ".join(errors))
    if not readings:
        raise ServiceValidationError("No readings found in the provided text")
    return readings


def validate_readings(readings: list[Reading], unit: str) -> None:
    for reading in readings:
        if reading.value < 0:
            raise ServiceValidationError(
                f"Reading at {format_local(reading.timestamp)} cannot be negative"
            )
    for previous, current in zip(readings, readings[1:]):
        if current.value < previous.value:
            raise ServiceValidationError(
                f"Reading {format_value(current.value)} {unit} at "
                f"{format_local(current.timestamp)} is lower than the earlier reading "
                f"{format_value(previous.value)} {unit} at "
                f"{format_local(previous.timestamp)}"
            )


def _interpolate(
    readings: list[Reading], totals: list[float], index: int, at: datetime
) -> tuple[float, float]:
    first = readings[index]
    if index + 1 >= len(readings) or at <= first.timestamp:
        return first.value, totals[index]
    second = readings[index + 1]
    if at >= second.timestamp:
        return second.value, totals[index + 1]
    fraction = (at - first.timestamp) / (second.timestamp - first.timestamp)
    return (
        first.value + fraction * (second.value - first.value),
        totals[index] + fraction * (totals[index + 1] - totals[index]),
    )


def build_statistics(readings: list[Reading]) -> list[StatisticData]:
    if not readings:
        return []
    totals = [0.0]
    for previous, current in zip(readings, readings[1:]):
        totals.append(totals[-1] + max(0.0, current.value - previous.value))
    last = readings[-1].timestamp
    hour = readings[0].timestamp.replace(minute=0)
    index = 0
    statistics: list[StatisticData] = []
    while hour <= last:
        end = min(hour + HOUR, last)
        while index + 2 < len(readings) and readings[index + 1].timestamp <= end:
            index += 1
        value, total = _interpolate(readings, totals, index, end)
        statistics.append(StatisticData(start=hour, state=value, sum=total))
        hour += HOUR
    return statistics


def price_at(prices: list[Price], at: datetime) -> Price | None:
    if not prices:
        return None
    index = bisect_right([p.valid_from for p in prices], at) - 1
    return prices[max(index, 0)]


def build_cost_statistics(
    consumption: list[StatisticData], prices: list[Price]
) -> list[StatisticData]:
    if not prices:
        return []
    starts = [p.valid_from for p in prices]
    previous_sum = 0.0
    cost = 0.0
    statistics: list[StatisticData] = []
    for row in consumption:
        price = prices[max(bisect_right(starts, row["start"]) - 1, 0)]
        cost += (row["sum"] - previous_sum) * price.unit_price
        previous_sum = row["sum"]
        statistics.append(StatisticData(start=row["start"], state=cost, sum=cost))
    return statistics


def _rounded(statistics: list[StatisticData], digits: int) -> list[StatisticData]:
    return [
        StatisticData(
            start=row["start"],
            state=round(row["state"], digits),
            sum=round(row["sum"], digits),
        )
        for row in statistics
    ]


class MeterData:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.statistic_id: str = entry.data[CONF_STATISTIC_ID]
        self.cost_statistic_id = f"{self.statistic_id}_cost"
        self.unit: str = entry.data[CONF_UNIT]
        self.meter_type: str = entry.data[CONF_METER_TYPE]
        self.price_per: str = entry.data.get(CONF_PRICE_PER, PRICE_PER_UNIT)
        self.currency: str = hass.config.currency
        self.readings: list[Reading] = []
        self.prices: list[Price] = []
        self.total_cost: float | None = None
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, storage_key(entry.entry_id)
        )

    @property
    def signal(self) -> str:
        return SIGNAL_UPDATED.format(self.entry.entry_id)

    @property
    def latest(self) -> Reading | None:
        return self.readings[-1] if self.readings else None

    @property
    def uses_factor(self) -> bool:
        return self.price_per == PRICE_PER_KWH

    @property
    def price_unit(self) -> str:
        billed = UnitOfEnergy.KILO_WATT_HOUR if self.uses_factor else self.unit
        return f"{self.currency}/{billed}"

    @property
    def unit_price_unit(self) -> str:
        return f"{self.currency}/{self.unit}"

    @property
    def factor_unit(self) -> str:
        return f"{UnitOfEnergy.KILO_WATT_HOUR}/{self.unit}"

    @property
    def current_price(self) -> Price | None:
        return price_at(self.prices, dt_util.utcnow())

    def _metadata(
        self, statistic_id: str, name: str, unit: str
    ) -> StatisticMetaData:
        metadata: dict[str, Any] = {
            "has_sum": True,
            "name": name,
            "source": DOMAIN,
            "statistic_id": statistic_id,
            "unit_of_measurement": unit,
        }
        if StatisticMeanType is None:
            metadata["has_mean"] = False
        else:
            metadata["mean_type"] = StatisticMeanType.NONE
        if "unit_class" in StatisticMetaData.__annotations__:
            converter = STATISTIC_UNIT_TO_UNIT_CONVERTER.get(unit)
            metadata["unit_class"] = converter.UNIT_CLASS if converter else None
        return metadata

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.readings = sorted(
            Reading(dt_util.parse_datetime(item["timestamp"]), float(item["value"]))
            for item in data.get("readings", [])
        )
        self.prices = sorted(
            Price(
                dt_util.parse_datetime(item["valid_from"]),
                float(item["price"]),
                item.get("factor"),
            )
            for item in data.get("prices", [])
        )
        self.total_cost = data.get("total_cost")

    def get(self, timestamp: datetime | str) -> Reading:
        normalized = normalize_timestamp(timestamp)
        for reading in self.readings:
            if reading.timestamp == normalized:
                return reading
        raise ServiceValidationError(f"No reading found at {format_local(normalized)}")

    def get_price(self, valid_from: datetime | str) -> Price:
        normalized = normalize_timestamp(valid_from)
        for price in self.prices:
            if price.valid_from == normalized:
                return price
        raise ServiceValidationError(
            f"No price found valid from {format_local(normalized)}"
        )

    def _exists(self, timestamp: datetime) -> bool:
        return any(reading.timestamp == timestamp for reading in self.readings)

    async def async_add(self, timestamp: datetime | str, value: float) -> Reading:
        normalized = normalize_timestamp(timestamp)
        if self._exists(normalized):
            raise ServiceValidationError(
                f"A reading already exists at {format_local(normalized)}, edit it instead"
            )
        reading = Reading(normalized, float(value))
        await self._async_commit(readings=[*self.readings, reading])
        return reading

    async def async_import(self, readings: list[Reading], replace: bool) -> int:
        merged = {} if replace else {r.timestamp: r for r in self.readings}
        merged.update({r.timestamp: r for r in readings})
        await self._async_commit(readings=list(merged.values()))
        return len(readings)

    async def async_update(
        self,
        timestamp: datetime | str,
        value: float | None = None,
        new_timestamp: datetime | str | None = None,
    ) -> Reading:
        current = self.get(timestamp)
        target = (
            current.timestamp
            if new_timestamp is None
            else normalize_timestamp(new_timestamp)
        )
        if target != current.timestamp and self._exists(target):
            raise ServiceValidationError(
                f"A reading already exists at {format_local(target)}"
            )
        reading = Reading(target, current.value if value is None else float(value))
        await self._async_commit(
            readings=[r for r in self.readings if r.timestamp != current.timestamp]
            + [reading]
        )
        return reading

    async def async_delete(self, timestamp: datetime | str) -> Reading:
        current = self.get(timestamp)
        await self._async_commit(
            readings=[r for r in self.readings if r.timestamp != current.timestamp]
        )
        return current

    async def async_set_price(
        self,
        valid_from: datetime | str,
        price: float | None = None,
        factor: float | None = None,
        replaces: datetime | None = None,
    ) -> Price:
        normalized = normalize_timestamp(valid_from)
        previous = next(
            (p for p in self.prices if p.valid_from == replaces), None
        ) or price_at(self.prices, normalized)
        if price is None:
            if previous is None:
                raise ServiceValidationError("Enter a price")
            price = previous.price
        if price < 0:
            raise ServiceValidationError("The price cannot be negative")
        if self.uses_factor:
            if factor is None and previous is not None:
                factor = previous.factor
            if factor is None or factor <= 0:
                raise ServiceValidationError(
                    f"Enter a conversion factor in {self.factor_unit}"
                )
        else:
            factor = None
        entry = Price(normalized, float(price), None if factor is None else float(factor))
        await self._async_commit(
            prices=[
                p
                for p in self.prices
                if p.valid_from not in (normalized, replaces)
            ]
            + [entry]
        )
        return entry

    async def async_delete_price(self, valid_from: datetime | str) -> Price:
        current = self.get_price(valid_from)
        await self._async_commit(
            prices=[p for p in self.prices if p.valid_from != current.valid_from]
        )
        return current

    async def _async_commit(
        self,
        readings: list[Reading] | None = None,
        prices: list[Price] | None = None,
    ) -> None:
        if readings is not None:
            readings = sorted(readings)
            validate_readings(readings, self.unit)
            self.readings = readings
        if prices is not None:
            self.prices = sorted(prices)
        self.async_rebuild_statistics()
        await self._store.async_save(
            {
                "readings": [
                    {"timestamp": r.timestamp.isoformat(), "value": r.value}
                    for r in self.readings
                ],
                "prices": [
                    {
                        "valid_from": p.valid_from.isoformat(),
                        "price": p.price,
                        "factor": p.factor,
                    }
                    for p in self.prices
                ],
                "total_cost": self.total_cost,
            }
        )
        async_dispatcher_send(self.hass, self.signal)

    @callback
    def async_rebuild_statistics(self) -> None:
        get_instance(self.hass).async_clear_statistics(
            [self.statistic_id, self.cost_statistic_id]
        )
        consumption = build_statistics(self.readings)
        cost = build_cost_statistics(consumption, self.prices)
        self.total_cost = round(cost[-1]["sum"], 2) if cost else None
        if consumption:
            async_add_external_statistics(
                self.hass,
                self._metadata(self.statistic_id, self.entry.title, self.unit),
                _rounded(consumption, 6),
            )
        if cost:
            async_add_external_statistics(
                self.hass,
                self._metadata(
                    self.cost_statistic_id,
                    f"{self.entry.title} "
                    f"{'koszt' if self.hass.config.language == 'pl' else 'cost'}",
                    self.currency,
                ),
                _rounded(cost, 4),
            )
