"""Profile-based adapter for the Jellyfishtur smart night-light plug (2BSN).

Only the plug, night light and declared live-power reading are projected.
Timer, OTA and network services are controlled by the Huawei app and are not
treated as generic Home Assistant controls.

This adapter is based on the public Profile and has not been verified on a
physical device.
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
    return round((number - minimum) * 255 / (maximum - minimum))


def _ha_brightness_to_device(value: Any, field: Mapping[str, Any]) -> Any:
    number = _number(value)
    value_range = _range(field)
    if number is None or value_range is None:
        raise ValueError("2BSN night-light brightness range is missing")
    minimum, maximum = value_range
    number = min(max(float(number), 0.0), 255.0)
    return _payload_number(minimum + number * (maximum - minimum) / 255, field)


def _switch_spec(
    context: DeviceContext,
    sid: str,
    field_name: str,
    key: str,
    name: str,
) -> EntitySpec | None:
    field = _field(context.profile or {}, sid, field_name)
    if field is None:
        return None

    async def turn_on(device: DeviceContext, _data: Mapping[str, Any]) -> None:
        await device.async_send_service(sid, {field_name: 1})

    async def turn_off(device: DeviceContext, _data: Mapping[str, Any]) -> None:
        await device.async_send_service(sid, {field_name: 0})

    return EntitySpec(
        platform="switch",
        key=key,
        name=name,
        state=lambda device: {"is_on": _bool(device.value(sid, field_name))},
        actions={"turn_on": turn_on, "turn_off": turn_off},
    )


class Product2BSNAdapter:
    """Expose the plug and its independent night light."""

    prod_id = "2BSN"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        specs: list[EntitySpec] = []
        socket = _switch_spec(context, "switch", "on", "socket", "插座")
        if socket is not None:
            specs.append(socket)

        night_switch = _field(profile, "NightLightSwitch", "NightLightSwitch")
        night_brightness = _field(
            profile, "NightLightBrightness", "NightLightBrightness"
        )
        brightness_range = _range(night_brightness)
        if night_switch is not None:

            async def night_turn_on(
                device: DeviceContext, data: Mapping[str, Any]
            ) -> None:
                await device.async_send_service(
                    "NightLightSwitch", {"NightLightSwitch": 1}
                )
                if data.get("brightness") is not None and night_brightness is not None:
                    await device.async_send_service(
                        "NightLightBrightness",
                        {
                            "NightLightBrightness": _ha_brightness_to_device(
                                data["brightness"], night_brightness
                            )
                        },
                    )

            async def night_turn_off(
                device: DeviceContext, _data: Mapping[str, Any]
            ) -> None:
                await device.async_send_service(
                    "NightLightSwitch", {"NightLightSwitch": 0}
                )

            mode = "brightness" if brightness_range is not None else "onoff"

            def night_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "is_on": _bool(
                        device.value("NightLightSwitch", "NightLightSwitch")
                    ),
                    "brightness": (
                        _device_brightness_to_ha(
                            device.value(
                                "NightLightBrightness", "NightLightBrightness"
                            ),
                            night_brightness or {},
                        )
                        if brightness_range is not None
                        else None
                    ),
                    "color_mode": mode,
                }

            specs.append(
                EntitySpec(
                    platform="light",
                    key="night_light",
                    name="夜灯",
                    state=night_state,
                    metadata={"supported_color_modes": {mode}},
                    actions={"turn_on": night_turn_on, "turn_off": night_turn_off},
                )
            )

        power_field = _field(profile, "power", "current")
        if power_field is not None:
            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="power",
                    name="实时功率",
                    state=lambda device: {
                        "native_value": _number(device.value("power", "current"))
                    },
                    metadata={
                        "unit": "W",
                        "device_class": "power",
                        "state_class": "measurement",
                    },
                )
            )
        return tuple(specs)


ADAPTER = Product2BSNAdapter()
