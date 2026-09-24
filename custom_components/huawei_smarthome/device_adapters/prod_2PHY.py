"""Profile-based adapter for the Haque Quedan Max camera (2PHY).

This PLUGIN profile has no stream URL that this integration can consume.  The
adapter therefore exposes only explicit switches, alarm states, phone/preset
triggers and RSSI.  Cloud identifiers, log collection and OTA are omitted.

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


def _payload_value(value: Any, field: Mapping[str, Any]) -> Any:
    number = _number(value)
    if number is None:
        return value
    if str(field.get("characteristicType") or "").casefold() in {
        "int",
        "integer",
        "enum",
        "bool",
    }:
        return int(round(number))
    return number


def _switch_spec(
    profile: Mapping[str, Any], sid: str, key: str, name: str
) -> EntitySpec | None:
    field = _field(profile, sid, "on")
    if field is None or "W" not in str(field.get("method") or ""):
        return None

    async def turn_on(device: DeviceContext, _data: Mapping[str, Any]) -> None:
        await device.async_send_service(sid, {"on": _payload_value(1, field)})

    async def turn_off(device: DeviceContext, _data: Mapping[str, Any]) -> None:
        await device.async_send_service(sid, {"on": _payload_value(0, field)})

    return EntitySpec(
        platform="switch",
        key=key,
        name=name,
        state=lambda device: {"is_on": _bool(device.value(sid, "on"))},
        actions={"turn_on": turn_on, "turn_off": turn_off},
    )


def _binary_spec(
    profile: Mapping[str, Any], sid: str, field_name: str, name: str, **metadata: Any
) -> EntitySpec | None:
    if _field(profile, sid, field_name) is None:
        return None
    return EntitySpec(
        platform="binary_sensor",
        key=f"{sid}_{field_name}",
        name=name,
        state=lambda device: {"is_on": _bool(device.value(sid, field_name))},
        metadata=metadata,
    )


def _button_spec(
    profile: Mapping[str, Any], sid: str, field_name: str, name: str
) -> EntitySpec | None:
    field = _field(profile, sid, field_name)
    if field is None or "W" not in str(field.get("method") or ""):
        return None

    async def press(device: DeviceContext, _data: Mapping[str, Any]) -> None:
        await device.async_send_service(
            sid, {field_name: _payload_value(1, field)}
        )

    return EntitySpec(
        platform="button",
        key=f"{sid}_{field_name}",
        name=name,
        state=lambda _device: {},
        actions={"press": press},
    )


class Product2PHYAdapter:
    """Haque Quedan Max 64GB (AZ08H)."""

    prod_id = "2PHY"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()
        specs: list[EntitySpec] = []

        for sid, key, name in (
            ("switch", "camera", "摄像头"),
            ("videoSwitch", "video", "摄像开关"),
            ("shootSwitch", "shoot", "拍照开关"),
            ("cruiseSwitch", "cruise", "全景巡航"),
            ("localMode", "local_mode", "本地模式"),
        ):
            spec = _switch_spec(profile, sid, key, name)
            if spec is not None:
                specs.append(spec)

        for field_name, name, device_class in (
            ("alarm", "综合告警", None),
            ("babyCryAlarm", "婴儿哭声", "sound"),
            ("humanBodyAlarm", "人形侦测", "motion"),
            ("audioAlarm", "声音告警", "sound"),
            ("videoAlarm", "移动侦测", "motion"),
            ("animalAlarm", "动物侦测", "motion"),
        ):
            metadata = {"device_class": device_class} if device_class else {}
            spec = _binary_spec(profile, "alarmEvent", field_name, name, **metadata)
            if spec is not None:
                specs.append(spec)

        for sid, field_name, name in (
            ("strangerFaceAlarm", "alarm", "陌生人脸告警"),
            ("familiarFaceAlarm", "alarm", "熟悉人脸告警"),
        ):
            spec = _binary_spec(profile, sid, field_name, name)
            if spec is not None:
                specs.append(spec)

        calling = _binary_spec(profile, "voip", "calling", "视频通话中")
        if calling is not None:
            specs.append(calling)
        call = _button_spec(profile, "voip", "voipCall", "视频通话")
        if call is not None:
            specs.append(call)

        for service in profile.get("services", ()):
            if not isinstance(service, Mapping):
                continue
            sid = service.get("serviceId")
            if not isinstance(sid, str) or not sid.startswith("visitPoint"):
                continue
            suffix = sid.removeprefix("visitPoint")
            spec = _button_spec(profile, sid, "move", f"预置点{suffix}")
            if spec is not None:
                specs.append(spec)

        if _field(profile, "netInfo", "RSSI") is not None:
            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="rssi",
                    name="信号强度 RSSI",
                    state=lambda device: {
                        "native_value": _number(device.value("netInfo", "RSSI"))
                    },
                    metadata={
                        "unit": "dBm",
                        "device_class": "signal_strength",
                        "state_class": "measurement",
                    },
                )
            )
        return tuple(specs)


ADAPTER = Product2PHYAdapter()
