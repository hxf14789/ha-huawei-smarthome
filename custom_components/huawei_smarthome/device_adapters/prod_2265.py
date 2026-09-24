"""Read-only adapter for the Kaadas HK600 smart lock (2265).

The Profile describes lockStatus as read-only, so no remote lock/unlock
command is invented.  Credential lists, temporary ciphers and user data are
also deliberately not exposed.  The entities below are limited to state and
diagnostic fields whose meaning is explicit in the Profile.

This mapping is derived from the public Profile and has not been verified on a
physical device.
本适配器由开发者依据 Profile 完成适配，未经真实设备验证。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..domain.models import parse_remote_timestamp
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


def _enum_label(field: Mapping[str, Any], value: Any) -> str | None:
    number = _number(value)
    for option in field.get("enumList", ()):
        if not isinstance(option, Mapping):
            continue
        if number is not None and _number(option.get("enumVal")) == number:
            label = option.get("descCh") or option.get("descEn")
            if label:
                return str(label)
    return None


class Product2265Adapter:
    """Kaadas Smart Lock HK600 (凯迪仕智能门锁 HK600)."""

    prod_id = "2265"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()
        status_field = _field(profile, "lockStatus", "status")
        if status_field is None:
            return ()

        def lock_state(device: DeviceContext) -> Mapping[str, Any]:
            status = _number(device.value("lockStatus", "status"))
            if status in {0, 2}:
                return {"is_locked": True}
            if status == 1:
                return {"is_locked": False}
            return {"is_locked": None}

        def status_state(device: DeviceContext) -> Mapping[str, Any]:
            raw = device.value("lockStatus", "status")
            return {
                "native_value": _enum_label(status_field, raw)
                or (str(raw) if raw is not None else None)
            }

        specs: list[EntitySpec] = [
            EntitySpec(
                platform="lock",
                key="lock",
                name="门锁",
                state=lock_state,
            ),
            EntitySpec(
                platform="sensor",
                key="lock_status",
                name="门锁状态",
                state=status_state,
            ),
        ]

        battery = _field(profile, "battery", "level")
        if battery is not None:

            def battery_state(device: DeviceContext) -> Mapping[str, Any]:
                value = _number(device.value("battery", "level"))
                return {"native_value": None if value == -1 else value}

            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="battery",
                    name="电池电量",
                    state=battery_state,
                    metadata={
                        "unit": "%",
                        "device_class": "battery",
                        "state_class": "measurement",
                    },
                )
            )

        alarm = _field(profile, "lockAlarm", "alarm")
        if alarm is not None:
            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="alarm",
                    name="门锁告警",
                    state=lambda device: {
                        "native_value": _enum_label(
                            alarm, device.value("lockAlarm", "alarm")
                        )
                    },
                )
            )

        event = _field(profile, "event", "event")
        if event is not None:
            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="last_event",
                    name="最近开锁方式",
                    state=lambda device: {
                        "native_value": _enum_label(
                            event, device.value("event", "event")
                        )
                    },
                )
            )

        last_action = _field(profile, "lastActionTime", "time")
        if last_action is not None:

            def action_time(device: DeviceContext) -> Mapping[str, Any]:
                raw = device.value("lastActionTime", "time")
                return {
                    "native_value": parse_remote_timestamp(raw)
                    if isinstance(raw, str)
                    else None
                }

            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="last_action_time",
                    name="最近操作时间",
                    state=action_time,
                    metadata={"device_class": "timestamp"},
                )
            )
        return tuple(specs)


ADAPTER = Product2265Adapter()
