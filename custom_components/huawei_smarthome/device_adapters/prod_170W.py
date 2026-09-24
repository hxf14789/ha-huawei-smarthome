"""User-contributed protocol for Huawei product 170W (720 全效空气净化器 S(C400)).

Profile（`device/guide/170W/170W.json`，deviceTypeId 013）+ 真机上报（2026-09-16）：
  switch.on                       bool RW  1=开 0=关
  airPurifying.mode               int  RW  0=手动 1=自动 2=睡眠
  airPurifying.filterReplaceAlarm int  RW  0=无 1=有（滤芯到期告警）
  wind.windSpeed                  int  RW  1档/2档/3档（枚举按 Profile 动态读，别写死）
  pm2p5.pm2p5Value                int  R   PM2.5 数值（真机 14）
  filterElement.leftPer           int  R   滤芯剩余 %（真机 71）

暴露：switch（开关）+ select（模式）+ select（风速）+ sensor（PM2.5 / 滤芯剩余）
      + binary_sensor（滤芯告警）。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            return int(round(float(value.strip())))
        except (TypeError, ValueError):
            return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _flag(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.casefold() in {"1", "true", "on"}:
            return True
        if value.casefold() in {"0", "false", "off"}:
            return False
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _enum_map(profile: Any, sid: str, field: str) -> dict[str, str]:
    """从 Profile 读某字段的 enumList → {值(str): 中文标签}。"""
    for service in (profile.get("services") or []) if isinstance(profile, Mapping) else ():
        if not isinstance(service, Mapping) or service.get("serviceId") != sid:
            continue
        for ch in service.get("characteristics") or ():
            if isinstance(ch, Mapping) and ch.get("characteristicName") == field:
                return {
                    str(o.get("enumVal")): str(o.get("descCh") or o.get("enumVal"))
                    for o in (ch.get("enumList") or ())
                    if isinstance(o, Mapping)
                }
    return {}


class Product170WAdapter:
    """170W 净化器：开关 / 模式 / 风速 / PM2.5 / 滤芯。"""

    prod_id = "170W"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("switch"):
            return ()

        mode_labels = _enum_map(context.profile, "airPurifying", "mode")
        speed_labels = _enum_map(context.profile, "wind", "windSpeed")

        def switch_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"is_on": _flag(device.value("switch", "on"))}

        def mode_state(device: DeviceContext) -> Mapping[str, Any]:
            code = _as_int(device.value("airPurifying", "mode"))
            return {"current_option": mode_labels.get(str(code)) if code is not None else None}

        def speed_state(device: DeviceContext) -> Mapping[str, Any]:
            code = _as_int(device.value("wind", "windSpeed"))
            return {"current_option": speed_labels.get(str(code)) if code is not None else None}

        def pm_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"native_value": _as_int(device.value("pm2p5", "pm2p5Value"))}

        def filter_state(device: DeviceContext) -> Mapping[str, Any]:
            value = _as_int(device.value("filterElement", "leftPer"))
            return {"native_value": None if value is None else float(value)}

        def alarm_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"is_on": _flag(device.value("airPurifying", "filterReplaceAlarm"))}

        async def turn_on(device: DeviceContext, _data: Mapping[str, Any]) -> None:
            await device.async_send_service("switch", {"on": 1})

        async def turn_off(device: DeviceContext, _data: Mapping[str, Any]) -> None:
            await device.async_send_service("switch", {"on": 0})

        async def set_mode(device: DeviceContext, data: Mapping[str, Any]) -> None:
            label = str(data.get("option"))
            value = next((v for v, l in mode_labels.items() if l == label), None)
            if value is None:
                raise ValueError(f"unsupported purifier mode: {label}")
            await device.async_send_service("airPurifying", {"mode": int(value)})

        async def set_speed(device: DeviceContext, data: Mapping[str, Any]) -> None:
            label = str(data.get("option"))
            value = next((v for v, l in speed_labels.items() if l == label), None)
            if value is None:
                raise ValueError(f"unsupported fan speed: {label}")
            await device.async_send_service("wind", {"windSpeed": int(value)})

        specs: list[EntitySpec] = [
            EntitySpec(
                platform="switch",
                key="switch",
                name=None,
                state=switch_state,
                actions={"turn_on": turn_on, "turn_off": turn_off},
            )
        ]
        if mode_labels:
            specs.append(
                EntitySpec(
                    platform="select",
                    key="mode",
                    name="模式",
                    state=mode_state,
                    metadata={"options": list(mode_labels.values())},
                    actions={"select_option": set_mode},
                )
            )
        if speed_labels:
            specs.append(
                EntitySpec(
                    platform="select",
                    key="wind_speed",
                    name="风速",
                    state=speed_state,
                    metadata={"options": list(speed_labels.values())},
                    actions={"select_option": set_speed},
                )
            )
        if context.has_service("pm2p5"):
            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="pm25",
                    name="PM2.5",
                    state=pm_state,
                    metadata={"unit": "µg/m³", "device_class": "pm25", "state_class": "measurement"},
                )
            )
        if context.has_service("filterElement"):
            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="filter_left",
                    name="滤芯剩余",
                    state=filter_state,
                    metadata={"unit": "%", "state_class": "measurement"},
                )
            )
        if context.has_service("airPurifying"):
            specs.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="filter_alarm",
                    name="滤芯告警",
                    state=alarm_state,
                )
            )
        return tuple(specs)


ADAPTER = Product170WAdapter()
