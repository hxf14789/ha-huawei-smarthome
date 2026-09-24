"""Profile-based adapter for the DALEN Smart table lamp 2i (2AQO).

The public Profile exposes only a switch and a 1..100 brightness value.  The
adapter is intentionally limited to that contract; timers, OTA and network
diagnostics are left to the Huawei app.

This mapping is derived from the Profile and the existing DALEN lamp
adapters.  It has not been verified on a physical 2AQO device.
本适配器由开发者依据 Profile 完成适配，未经真实设备验证。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext


def _field(
    profile: Mapping[str, Any], sid: str, name: str
) -> Mapping[str, Any] | None:
    for service in profile.get("services", ()):
        if not isinstance(service, Mapping) or service.get("serviceId") != sid:
            continue
        for field in service.get("characteristics", ()):
            if isinstance(field, Mapping) and field.get("characteristicName") == name:
                return field
    return None


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.strip().casefold() in {"1", "true", "on"}:
            return True
        if value.strip().casefold() in {"0", "false", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _range(field: Mapping[str, Any] | None) -> tuple[float, float] | None:
    if field is None:
        return None
    minimum = _number(field.get("min"))
    maximum = _number(field.get("max"))
    if minimum is None or maximum is None or maximum <= minimum:
        return None
    return float(minimum), float(maximum)


def _payload_number(value: Any, field: Mapping[str, Any]) -> Any:
    number = _number(value)
    if number is None:
        return value
    if str(field.get("characteristicType") or "").casefold() in {
        "int",
        "integer",
        "enum",
    }:
        return int(round(number))
    return number


def _device_brightness_to_ha(value: Any, field: Mapping[str, Any]) -> int | None:
    number = _number(value)
    value_range = _range(field)
    if number is None or value_range is None:
        return None
    minimum, maximum = value_range
    number = min(max(float(number), minimum), maximum)
    return round(1 + (number - minimum) * 254 / (maximum - minimum))


def _ha_brightness_to_device(value: Any, field: Mapping[str, Any]) -> Any:
    number = _number(value)
    value_range = _range(field)
    if number is None or value_range is None:
        raise ValueError("2AQO brightness range is missing from the Profile")
    minimum, maximum = value_range
    number = min(max(float(number), 1.0), 255.0)
    raw = minimum + (number - 1) * (maximum - minimum) / 254
    return _payload_number(raw, field)


async def _turn_on(context: DeviceContext, data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 1})
    if data.get("brightness") is not None:
        field = _field(context.profile or {}, "brightness", "brightness")
        if field is not None:
            await context.async_send_service(
                "brightness",
                {"brightness": _ha_brightness_to_device(data["brightness"], field)},
            )


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 0})


class Product2AQOAdapter:
    """DALEN Smart table lamp 2i (DL-01W)."""

    prod_id = "2AQO"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()
        switch = _field(profile, "switch", "on")
        if switch is None:
            return ()

        brightness = _field(profile, "brightness", "brightness")
        brightness_range = _range(brightness)
        mode = "brightness" if brightness_range is not None else "onoff"

        def light_state(device: DeviceContext) -> Mapping[str, Any]:
            return {
                "is_on": _bool(device.value("switch", "on")),
                "brightness": (
                    _device_brightness_to_ha(
                        device.value("brightness", "brightness"), brightness or {}
                    )
                    if brightness_range is not None
                    else None
                ),
                "color_mode": mode,
            }

        return (
            EntitySpec(
                platform="light",
                key="light",
                name=None,
                state=light_state,
                metadata={"supported_color_modes": {mode}},
                actions={"turn_on": _turn_on, "turn_off": _turn_off},
            ),
        )


ADAPTER = Product2AQOAdapter()
