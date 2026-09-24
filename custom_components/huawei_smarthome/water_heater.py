"""Generic Home Assistant water heater registration for product adapters."""

from __future__ import annotations

from typing import Any

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity_helpers import AdapterEntityMixin, iter_specs


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up water heater entities declared by product adapters."""

    del hass
    async_add_entities(
        HuaweiAdapterWaterHeater(context, spec)
        for context, spec in iter_specs(entry.runtime_data, "water_heater")
    )


class HuaweiAdapterWaterHeater(AdapterEntityMixin, WaterHeaterEntity):
    """Expose one adapter-defined water heater entity."""

    def __init__(self, context: Any, spec: Any) -> None:
        self._init_adapter_entity(context, spec)
        metadata = spec.metadata
        features = WaterHeaterEntityFeature(0)
        if "set_temperature" in spec.actions:
            features |= WaterHeaterEntityFeature.TARGET_TEMPERATURE
        if "set_operation_mode" in spec.actions:
            features |= WaterHeaterEntityFeature.OPERATION_MODE
        if {"turn_on", "turn_off"} <= spec.actions.keys():
            features |= WaterHeaterEntityFeature.ON_OFF
        self._attr_supported_features = features
        self._attr_min_temp = metadata.get("min_temp")
        self._attr_max_temp = metadata.get("max_temp")
        self._attr_target_temperature_step = metadata.get("target_temp_step")
        self._attr_operation_list = list(metadata.get("operation_modes", ()))
        self._attr_temperature_unit = metadata.get(
            "temperature_unit",
            UnitOfTemperature.CELSIUS,
        )

    @property
    def current_temperature(self) -> float | None:
        return self._state_value("current_temperature")

    @property
    def target_temperature(self) -> float | None:
        return self._state_value("target_temperature")

    @property
    def current_operation(self) -> str | None:
        return self._state_value("current_operation")

    async def async_set_temperature(self, **kwargs: Any) -> None:
        await self._run_action(
            "set_temperature",
            {"temperature": kwargs.get(ATTR_TEMPERATURE)},
        )

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        await self._run_action(
            "set_operation_mode",
            {"operation_mode": operation_mode},
        )

    async def async_turn_on(self) -> None:
        await self._run_action("turn_on", {})

    async def async_turn_off(self) -> None:
        await self._run_action("turn_off", {})
