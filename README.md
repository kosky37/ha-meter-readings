# Meter Readings

A Home Assistant integration for utility meters you read by hand (gas, water). Type in the number from the meter every now and then and Home Assistant graphs it as if it came from a smart meter.

## Features

- One device per meter, created from the UI.
- Readings are turned into hourly long-term statistics, interpolated between readings, so the Energy dashboard and Statistics graph cards show consumption like an automatic integration would.
- Add a reading with the current time from a dashboard (`number.<meter>_new_reading`), or with any date from the integration's **Configure** menu.
- Import historical readings in bulk, one per line (`2025-01-15 08:30, 1234.567`, `2025-02-15;1250,1` or `15.03.2025 1263.9`).
- Correct or delete any reading. Statistics are rebuilt from the stored readings after every change.
- Prices with a history (valid-from dates). Gas can be priced per kWh with a conversion factor (kWh/m³). A cost statistic is computed hour by hour with the price valid at that time.
- Readings and prices are stored in `/config/.storage`, so they survive restarts, updates and are part of backups.

## Entities

| Entity | Purpose |
|:--|:--|
| `sensor.<meter>` | Latest meter value |
| `sensor.<meter>_last_reading` | When the meter was last read |
| `sensor.<meter>_unit_price` | Current price per meter unit |
| `sensor.<meter>_total_cost` | Cost of all consumption since the first reading |
| `number.<meter>_new_reading` | Type a value to record a reading now |
| `number.<meter>_price` | Type a value to set a new price from now |
| `number.<meter>_conversion_factor` | Gas priced per kWh only |

## Statistics

| Statistic | Use |
|:--|:--|
| `meter_readings:<meter>` | Energy dashboard gas or water consumption |
| `meter_readings:<meter>_cost` | Energy dashboard "Use an entity tracking the total costs" |

## Services

`meter_readings.add_reading`, `import_readings`, `update_reading`, `delete_reading`, `set_price`, `delete_price`, `get_readings`, `rebuild_statistics`.

## Installation

HACS → Custom repositories → add this repository as type *Integration*, install **Meter Readings**, restart Home Assistant, then add the integration under Settings → Devices & services.
