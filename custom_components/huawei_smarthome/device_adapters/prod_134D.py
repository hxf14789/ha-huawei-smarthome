"""Profile-based adapter for the OPPLE reading lamp (134D).

The main lamp is represented by one HA light with brightness and colour
temperature.  The Profile's night-light and indicator-light switches are
kept as separate switches.  Timer, delay and OTA services are intentionally
not projected.

This mapping is derived from the public Profile and has not been verified on a
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
    return round(1 + (number - minimum) * 254 / (maximum - minimum))


def _ha_brightness_to_device(value: Any, field: Mapping[str, Any]) -> Any:
    number = _number(value)
    value_range = _range(field)
    if number is None or value_range is None:
        raise ValueError("134D brightness range is missing from the Profile")
    minimum, maximum = value_range
    number = min(max(float(number), 1.0), 255.0)
    return _payload_number(
        minimum + (number - 1) * (maximum - minimum) / 254, field
    )


def _enum_options(field: Mapping[str, Any]) -> tuple[tuple[str, Any], ...]:
    options: list[tuple[str, Any]] = []
    for item in field.get("enumList", ()):
        if not isinstance(item, Mapping) or item.get("enumVal") is None:
            continue
        label = item.get("descCh") or item.get("descEn") or item.get("enumVal")
        options.append((str(label), item["enumVal"]))
    return tuple(options)


def _enum_label(field: Mapping[str, Any], value: Any) -> str | None:
    number = _number(value)
    for label, raw in _enum_options(field):
        if number is not None and _number(raw) == number:
            return label
    return None


async def _turn_on(context: DeviceContext, data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 1})
    profile = context.profile or {}
    brightness = _field(profile, "brightness", "brightness")
    if data.get("brightness") is not None and brightness is not None:
        await context.async_send_service(
            "brightness",
            {"brightness": _ha_brightness_to_device(data["brightness"], brightness)},
        )
    cct = _field(profile, "cct", "colorTemperature")
    if data.get("color_temp_kelvin") is not None and cct is not None:
        value_range = _range(cct)
        value = _number(data["color_temp_kelvin"])
        if value_range is not None and value is not None:
            value = min(max(value, value_range[0]), value_range[1])
            await context.async_send_service(
                "cct", {"colorTemperature": _payload_number(value, cct)}
            )


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 0})


class Product134DAdapter:
    """Huawei Smart Selection OPPLE reading lamp."""

    prod_id = "134D"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()
        specs: list[EntitySpec] = []

        switch = _field(profile, "switch", "on")
        brightness = _field(profile, "brightness", "brightness")
        cct = _field(profile, "cct", "colorTemperature")
        brightness_range = _range(brightness)
        cct_range = _range(cct)
        if switch is not None:
            mode = (
                "color_temp"
                if cct_range is not None
                else "brightness"
                if brightness_range is not None
                else "onoff"
            )

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
                    "color_temp_kelvin": (
                        _number(device.value("cct", "colorTemperature"))
                        if cct_range is not None
                        else None
                    ),
                    "color_mode": mode,
                }

            metadata: dict[str, Any] = {"supported_color_modes": {mode}}
            if cct_range is not None:
                metadata.update(
                    {
                        "min_color_temp_kelvin": int(cct_range[0]),
                        "max_color_temp_kelvin": int(cct_range[1]),
                    }
                )
            specs.append(
                EntitySpec(
                    platform="light",
                    key="light",
                    name=None,
                    state=light_state,
                    metadata=metadata,
                    actions={"turn_on": _turn_on, "turn_off": _turn_off},
                )
            )

        for sid, key, name in (
            ("nightSwitch", "night_light", "夜灯"),
            ("backlight", "backlight", "指示灯"),
        ):
            field = _field(profile, sid, "on")
            if field is None:
                continue

            async def turn_on(
                device: DeviceContext, _data: Mapping[str, Any], _sid: str = sid
            ) -> None:
                await device.async_send_service(_sid, {"on": 1})

            async def turn_off(
                device: DeviceContext, _data: Mapping[str, Any], _sid: str = sid
            ) -> None:
                await device.async_send_service(_sid, {"on": 0})

            specs.append(
                EntitySpec(
                    platform="switch",
                    key=key,
                    name=name,
                    state=lambda device, _sid=sid: {
                        "is_on": _bool(device.value(_sid, "on"))
                    },
                    actions={"turn_on": turn_on, "turn_off": turn_off},
                )
            )

        mode_field = _field(profile, "lightMode", "mode")
        options = _enum_options(mode_field) if mode_field is not None else ()
        if mode_field is not None and options:

            async def select_mode(
                device: DeviceContext, data: Mapping[str, Any]
            ) -> None:
                option = str(data.get("option"))
                for label, raw in options:
                    if label == option:
                        await device.async_send_service(
                            "lightMode", {"mode": _payload_number(raw, mode_field)}
                        )
                        return
                raise ValueError(f"134D unknown light mode: {option}")

            specs.append(
                EntitySpec(
                    platform="select",
                    key="light_mode",
                    name="灯光模式",
                    state=lambda device: {
                        "current_option": _enum_label(
                            mode_field, device.value("lightMode", "mode")
                        )
                    },
                    metadata={"options": tuple(label for label, _ in options)},
                    actions={"select_option": select_mode},
                )
            )
        return tuple(specs)


ADAPTER = Product134DAdapter()
