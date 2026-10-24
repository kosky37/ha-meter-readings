from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME, UnitOfEnergy
from homeassistant.core import callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.selector import (
    BooleanSelector,
    DateTimeSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)
from homeassistant.util import dt as dt_util, slugify

from .const import (
    ALL_UNITS,
    ATTR_DELETE,
    ATTR_FACTOR,
    ATTR_PRICE,
    ATTR_READING,
    ATTR_READINGS,
    ATTR_REPLACE,
    ATTR_TIMESTAMP,
    ATTR_VALID_FROM,
    ATTR_VALUE,
    CONF_METER_TYPE,
    CONF_PRICE_PER,
    CONF_STATISTIC_ID,
    CONF_UNIT,
    DOMAIN,
    METER_GAS,
    METER_TYPES,
    PRICE_PER_KWH,
    PRICE_PER_OPTIONS,
    PRICE_PER_UNIT,
    UNITS,
)
from .meter import (
    MeterData,
    Price,
    Reading,
    format_local,
    format_value,
    parse_readings,
)

TABLE_ROWS = 30


def _local_input(timestamp) -> str:
    return dt_util.as_local(timestamp).strftime("%Y-%m-%d %H:%M:%S")


class MeterReadingsConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return MeterReadingsOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            meter_type = user_input[CONF_METER_TYPE]
            unit = user_input[CONF_UNIT]
            price_per = user_input[CONF_PRICE_PER]
            if not slugify(name):
                errors[CONF_NAME] = "invalid_name"
            elif unit not in UNITS[meter_type]:
                errors[CONF_UNIT] = "invalid_unit"
            elif price_per == PRICE_PER_KWH and (
                meter_type != METER_GAS or unit == UnitOfEnergy.KILO_WATT_HOUR
            ):
                errors[CONF_PRICE_PER] = "invalid_price_per"
            else:
                statistic_id = f"{DOMAIN}:{slugify(name)}"
                await self.async_set_unique_id(statistic_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_METER_TYPE: meter_type,
                        CONF_UNIT: unit,
                        CONF_PRICE_PER: price_per,
                        CONF_STATISTIC_ID: statistic_id,
                    },
                )
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): TextSelector(),
                vol.Required(CONF_METER_TYPE, default=METER_GAS): SelectSelector(
                    SelectSelectorConfig(
                        options=METER_TYPES,
                        translation_key=CONF_METER_TYPE,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Required(CONF_UNIT, default=ALL_UNITS[0]): SelectSelector(
                    SelectSelectorConfig(
                        options=ALL_UNITS, mode=SelectSelectorMode.DROPDOWN
                    )
                ),
                vol.Required(CONF_PRICE_PER, default=PRICE_PER_UNIT): SelectSelector(
                    SelectSelectorConfig(
                        options=PRICE_PER_OPTIONS,
                        translation_key=CONF_PRICE_PER,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )


class MeterReadingsOptionsFlow(OptionsFlow):
    def __init__(self) -> None:
        self._selected: Reading | None = None
        self._selected_price: Price | None = None

    @property
    def _meter(self) -> MeterData:
        return self.config_entry.runtime_data

    def _value_selector(self) -> NumberSelector:
        return NumberSelector(
            NumberSelectorConfig(
                min=0,
                step="any",
                mode=NumberSelectorMode.BOX,
                unit_of_measurement=self._meter.unit,
            )
        )

    def _latest_text(self) -> str:
        latest = self._meter.latest
        if latest is None:
            return "no readings yet"
        return (
            f"{format_value(latest.value)} {self._meter.unit} "
            f"at {format_local(latest.timestamp)}"
        )

    def _price_text(self, price: Price | None) -> str:
        if price is None:
            return "not set"
        text = f"{format_value(price.price, 6)} {self._meter.price_unit}"
        if price.factor is not None:
            text += (
                f" × {format_value(price.factor)} {self._meter.factor_unit} = "
                f"{format_value(price.unit_price, 4)} {self._meter.unit_price_unit}"
            )
        return text

    def _price_schema(self) -> vol.Schema:
        fields: dict[Any, Any] = {
            vol.Required(ATTR_PRICE): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    step="any",
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement=self._meter.price_unit,
                )
            )
        }
        if self._meter.uses_factor:
            fields[vol.Required(ATTR_FACTOR)] = NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    step="any",
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement=self._meter.factor_unit,
                )
            )
        fields[vol.Required(ATTR_VALID_FROM)] = DateTimeSelector()
        return vol.Schema(fields)

    def _saved(self, details: str) -> ConfigFlowResult:
        return self.async_abort(
            reason="saved", description_placeholders={"details": details}
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "add_reading",
                "edit_reading",
                "import_readings",
                "add_price",
                "edit_price",
                "view_readings",
            ],
            description_placeholders={
                "name": self.config_entry.title,
                "latest": self._latest_text(),
                "count": str(len(self._meter.readings)),
                "price": self._price_text(self._meter.current_price),
            },
        )

    async def async_step_add_reading(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"latest": self._latest_text(), "error": ""}
        if user_input is not None:
            try:
                reading = await self._meter.async_add(
                    user_input[ATTR_TIMESTAMP], user_input[ATTR_VALUE]
                )
            except ServiceValidationError as err:
                errors["base"] = "invalid"
                placeholders["error"] = str(err)
            else:
                return self._saved(
                    f"Added {format_value(reading.value)} {self._meter.unit} "
                    f"at {format_local(reading.timestamp)}."
                )
        latest = self._meter.latest
        schema = vol.Schema(
            {
                vol.Required(ATTR_VALUE): self._value_selector(),
                vol.Required(ATTR_TIMESTAMP): DateTimeSelector(),
            }
        )
        suggested = user_input or {
            ATTR_TIMESTAMP: _local_input(dt_util.utcnow()),
            **({ATTR_VALUE: latest.value} if latest else {}),
        }
        return self.async_show_form(
            step_id="add_reading",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_edit_reading(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        readings = self._meter.readings
        if not readings:
            return self.async_abort(reason="no_readings")
        if user_input is not None:
            self._selected = next(
                (
                    r
                    for r in readings
                    if r.timestamp.isoformat() == user_input[ATTR_READING]
                ),
                None,
            )
            if self._selected is None:
                return self.async_abort(reason="no_readings")
            return await self.async_step_edit_selected()
        options = [
            SelectOptionDict(
                value=r.timestamp.isoformat(),
                label=f"{format_local(r.timestamp)}  —  "
                f"{format_value(r.value)} {self._meter.unit}",
            )
            for r in reversed(readings)
        ]
        return self.async_show_form(
            step_id="edit_reading",
            data_schema=vol.Schema(
                {
                    vol.Required(ATTR_READING, default=options[0]["value"]): SelectSelector(
                        SelectSelectorConfig(
                            options=options, mode=SelectSelectorMode.DROPDOWN
                        )
                    )
                }
            ),
        )

    async def async_step_edit_selected(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        selected = self._selected
        if selected is None:
            return self.async_abort(reason="no_readings")
        errors: dict[str, str] = {}
        placeholders = {
            "reading": f"{format_value(selected.value)} {self._meter.unit} "
            f"at {format_local(selected.timestamp)}",
            "error": "",
        }
        if user_input is not None and ATTR_VALUE in user_input:
            try:
                if user_input.get(ATTR_DELETE):
                    await self._meter.async_delete(selected.timestamp)
                    return self._saved(f"Deleted {placeholders['reading']}.")
                reading = await self._meter.async_update(
                    selected.timestamp,
                    user_input[ATTR_VALUE],
                    user_input[ATTR_TIMESTAMP],
                )
            except ServiceValidationError as err:
                errors["base"] = "invalid"
                placeholders["error"] = str(err)
            else:
                return self._saved(
                    f"Changed {placeholders['reading']} to "
                    f"{format_value(reading.value)} {self._meter.unit} "
                    f"at {format_local(reading.timestamp)}."
                )
        schema = vol.Schema(
            {
                vol.Required(ATTR_VALUE): self._value_selector(),
                vol.Required(ATTR_TIMESTAMP): DateTimeSelector(),
                vol.Optional(ATTR_DELETE, default=False): BooleanSelector(),
            }
        )
        suggested = (
            user_input
            if user_input and ATTR_VALUE in user_input
            else {
                ATTR_VALUE: selected.value,
                ATTR_TIMESTAMP: _local_input(selected.timestamp),
            }
        )
        return self.async_show_form(
            step_id="edit_selected",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_import_readings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"error": ""}
        if user_input is not None:
            try:
                count = await self._meter.async_import(
                    parse_readings(user_input[ATTR_READINGS]),
                    user_input[ATTR_REPLACE],
                )
            except ServiceValidationError as err:
                errors["base"] = "invalid"
                placeholders["error"] = str(err)
            else:
                return self._saved(
                    f"Imported {count} readings. The meter now has "
                    f"{len(self._meter.readings)} readings."
                )
        schema = vol.Schema(
            {
                vol.Required(ATTR_READINGS): TextSelector(
                    TextSelectorConfig(multiline=True)
                ),
                vol.Optional(ATTR_REPLACE, default=False): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="import_readings",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_add_price(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = self._meter.current_price
        placeholders = {"price": self._price_text(current), "error": ""}
        if user_input is not None:
            try:
                price = await self._meter.async_set_price(
                    user_input[ATTR_VALID_FROM],
                    user_input[ATTR_PRICE],
                    user_input.get(ATTR_FACTOR),
                )
            except ServiceValidationError as err:
                errors["base"] = "invalid"
                placeholders["error"] = str(err)
            else:
                return self._saved(
                    f"Saved price {self._price_text(price)} "
                    f"valid from {format_local(price.valid_from)}."
                )
        suggested = user_input or {
            ATTR_VALID_FROM: _local_input(dt_util.utcnow()),
            **({ATTR_PRICE: current.price} if current else {}),
            **(
                {ATTR_FACTOR: current.factor}
                if current and current.factor is not None
                else {}
            ),
        }
        return self.async_show_form(
            step_id="add_price",
            data_schema=self.add_suggested_values_to_schema(
                self._price_schema(), suggested
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_edit_price(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        prices = self._meter.prices
        if not prices:
            return self.async_abort(reason="no_prices")
        if user_input is not None:
            self._selected_price = next(
                (
                    p
                    for p in prices
                    if p.valid_from.isoformat() == user_input[ATTR_PRICE]
                ),
                None,
            )
            if self._selected_price is None:
                return self.async_abort(reason="no_prices")
            return await self.async_step_edit_selected_price()
        options = [
            SelectOptionDict(
                value=p.valid_from.isoformat(),
                label=f"{format_local(p.valid_from)}  —  {self._price_text(p)}",
            )
            for p in reversed(prices)
        ]
        return self.async_show_form(
            step_id="edit_price",
            data_schema=vol.Schema(
                {
                    vol.Required(ATTR_PRICE, default=options[0]["value"]): SelectSelector(
                        SelectSelectorConfig(
                            options=options, mode=SelectSelectorMode.DROPDOWN
                        )
                    )
                }
            ),
        )

    async def async_step_edit_selected_price(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        selected = self._selected_price
        if selected is None:
            return self.async_abort(reason="no_prices")
        errors: dict[str, str] = {}
        described = (
            f"{self._price_text(selected)} valid from {format_local(selected.valid_from)}"
        )
        placeholders = {"price": described, "error": ""}
        if user_input is not None and ATTR_VALID_FROM in user_input:
            try:
                if user_input.get(ATTR_DELETE):
                    await self._meter.async_delete_price(selected.valid_from)
                    return self._saved(f"Deleted price {described}.")
                price = await self._meter.async_set_price(
                    user_input[ATTR_VALID_FROM],
                    user_input[ATTR_PRICE],
                    user_input.get(ATTR_FACTOR),
                    replaces=selected.valid_from,
                )
            except ServiceValidationError as err:
                errors["base"] = "invalid"
                placeholders["error"] = str(err)
            else:
                return self._saved(
                    f"Saved price {self._price_text(price)} "
                    f"valid from {format_local(price.valid_from)}."
                )
        schema = self._price_schema().extend(
            {vol.Optional(ATTR_DELETE, default=False): BooleanSelector()}
        )
        suggested = (
            user_input
            if user_input and ATTR_VALID_FROM in user_input
            else {
                ATTR_PRICE: selected.price,
                ATTR_VALID_FROM: _local_input(selected.valid_from),
                **(
                    {ATTR_FACTOR: selected.factor}
                    if selected.factor is not None
                    else {}
                ),
            }
        )
        return self.async_show_form(
            step_id="edit_selected_price",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_view_readings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return await self.async_step_init()
        readings = self._meter.readings
        unit = self._meter.unit
        if not readings:
            table = "No readings yet."
        else:
            rows = [
                "| Date | Reading | Change | Per day |",
                "|:--|--:|--:|--:|",
            ]
            pairs = list(zip([None, *readings], readings))[-TABLE_ROWS:]
            for previous, current in reversed(pairs):
                change = per_day = ""
                if previous is not None:
                    delta = current.value - previous.value
                    days = (
                        current.timestamp - previous.timestamp
                    ).total_seconds() / 86400
                    change = f"+{format_value(delta)}"
                    per_day = f"{delta / days:.3f}" if days > 0 else ""
                rows.append(
                    f"| {format_local(current.timestamp)} | "
                    f"{format_value(current.value)} {unit} | {change} | {per_day} |"
                )
            table = "\n".join(rows)
        if self._meter.prices:
            price_rows = [
                "| Valid from | Price | Unit price |",
                "|:--|--:|--:|",
            ]
            price_rows.extend(
                f"| {format_local(p.valid_from)} | {self._price_text(p)} | "
                f"{format_value(p.unit_price, 4)} {self._meter.unit_price_unit} |"
                for p in reversed(self._meter.prices)
            )
            prices = "\n".join(price_rows)
        else:
            prices = "No prices yet."
        total_cost = (
            "not available"
            if self._meter.total_cost is None
            else f"{self._meter.total_cost:.2f} {self._meter.currency}"
        )
        return self.async_show_form(
            step_id="view_readings",
            data_schema=vol.Schema({}),
            description_placeholders={
                "table": table,
                "prices": prices,
                "total_cost": total_cost,
                "count": str(len(readings)),
                "shown": str(min(len(readings), TABLE_ROWS)),
            },
        )
