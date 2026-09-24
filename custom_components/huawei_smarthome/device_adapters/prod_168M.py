"""Profile-based adapter for the Sansi smart panel switch (168M).

The panel has a normal switch plus a three-state night-light control.  The
night-light state is reported separately, so the latter is represented as a
select and a binary sensor rather than guessed as another switch.

This mapping is derived from the public Profile and has not been verified on
a physical device.
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


def _enum_options(field: Mapping[str, Any]) -> tuple[tuple[str, Any], ...]:
    options: list[tuple[str, Any]] = []
    for item in field.get("enumList", ()):
        if not isinstance(item, Mapping) or item.get("enumVal") is None:
            continue
        label = item.get("descCh") or item.get("descEn") or item.get("enumVal")
        options.append((str(label), item["enumVal"]))
    return tuple(options)


def _payload_value(value: Any, field: Mapping[str, Any]) -> Any:
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


class Product168MAdapter:
    """三思智能面板开关（C21HI-TP7-1.5W）."""

    prod_id = "168M"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()
        specs: list[EntitySpec] = []

        switch = _field(profile, "switch", "on")
        if switch is not None:
            specs.append(
                EntitySpec(
                    platform="switch",
                    key="power",
                    name="开关",
                    state=lambda device: {
                        "is_on": _bool(device.value("switch", "on"))
                    },
                    actions={
                        "turn_on": lambda device, _data: device.async_send_service(
                            "switch", {"on": 1}
                        ),
                        "turn_off": lambda device, _data: device.async_send_service(
                            "switch", {"on": 0}
                        ),
                    },
                )
            )

        status = _field(profile, "yedengstatus", "yedengstatus")
        if status is not None:
            def night_status(device: DeviceContext) -> Mapping[str, Any]:
                value = _number(device.value("yedengstatus", "yedengstatus"))
                return {"is_on": True if value == 1 else False if value == 0 else None}

            specs.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="night_light",
                    name="夜灯状态",
                    state=night_status,
                )
            )

        night_switch = _field(profile, "yedengsw", "yedengsw")
        if night_switch is not None:
            options = _enum_options(night_switch)
            labels = {label: raw for label, raw in options}

            def night_state(device: DeviceContext) -> Mapping[str, Any]:
                raw = device.value("yedengsw", "yedengsw")
                for label, value in options:
                    if _number(raw) == _number(value):
                        return {"current_option": label}
                return {"current_option": None}

            async def select_night(
                device: DeviceContext, data: Mapping[str, Any]
            ) -> None:
                option = str(data.get("option"))
                if option not in labels:
                    raise ValueError(f"168M unknown night-light option: {option}")
                await device.async_send_service(
                    "yedengsw",
                    {"yedengsw": _payload_value(labels[option], night_switch)},
                )

            if options:
                specs.append(
                    EntitySpec(
                        platform="select",
                        key="night_light_mode",
                        name="夜灯模式",
                        state=night_state,
                        metadata={"options": tuple(label for label, _ in options)},
                        actions={"select_option": select_night},
                    )
                )

        return tuple(specs)


ADAPTER = Product168MAdapter()
