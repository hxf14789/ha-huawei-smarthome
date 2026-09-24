"""User-contributed protocol for Huawei product 153E (领普三键墙壁开关 Q3D-HW-W3).

与 20UC（双键 Q3D-HW-W2）/ 20GX（单键 Q3D-HW-W1）协议同构，但按键数不同，
因此各自独立成文件（仓库约定不在适配器之间共享代码）。

证据（2026-09-16 实测）：Profile `.storage/huawei_smarthome/profiles/153E.json` + 真机状态。
真机实例：2 台三键面板（含未接线的按键，不上报 `on`）。

字段：switch.on · switch1..3.on · switch1..3.name · led.brightness(0~100 面板指示灯)
暴露：总开关 + 3 路按键 switch + 一个 number（指示灯亮度）。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_MAIN_SID = "switch"
_MAIN_KEY = "sw_switch"
_MAIN_NAME = "总开关"
_LED_SID = "led"
_LED_FIELD = "brightness"
_LED_RANGE = (0.0, 100.0)


def _service_ids(profile: Any) -> tuple[str, ...]:
    """Profile 声明的服务 id，顺序保持 Profile 顺序。"""

    services = profile.get("services") if isinstance(profile, Mapping) else None
    ids: list[str] = []
    for service in services or ():
        if not isinstance(service, Mapping):
            continue
        sid = service.get("serviceId") or service.get("sid")
        if isinstance(sid, str) and sid:
            ids.append(sid)
    return tuple(ids)


def _flag(raw: Any) -> bool | None:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        if raw.casefold() in {"1", "true", "on"}:
            return True
        if raw.casefold() in {"0", "false", "off"}:
            return False
        return None
    if isinstance(raw, (int, float)):
        return bool(raw)
    return None


def _number(raw: Any) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _switch_spec(sid: str, key: str, name: str) -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        return {"is_on": _flag(device.value(sid, "on"))}

    async def turn_on(device: DeviceContext, _data: Mapping[str, Any]) -> None:
        await device.async_send_service(sid, {"on": 1})

    async def turn_off(device: DeviceContext, _data: Mapping[str, Any]) -> None:
        await device.async_send_service(sid, {"on": 0})

    return EntitySpec(
        platform="switch",
        key=key,
        name=name,
        state=state,
        actions={"turn_on": turn_on, "turn_off": turn_off},
    )


def _backlight_spec() -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        return {"native_value": _number(device.value(_LED_SID, _LED_FIELD))}

    async def set_value(device: DeviceContext, data: Mapping[str, Any]) -> None:
        value = _number(data.get("value"))
        if value is None:
            raise ValueError("backlight brightness is required")
        await device.async_send_service(_LED_SID, {_LED_FIELD: int(round(value))})

    return EntitySpec(
        platform="number",
        key="led_brightness",
        name="指示灯亮度",
        state=state,
        metadata={"min": _LED_RANGE[0], "max": _LED_RANGE[1], "step": 1},
        actions={"set_value": set_value},
    )


class Product153EAdapter:
    """领普三键面板：总开关 + 3 路按键 + 指示灯亮度。"""

    prod_id = "153E"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service(_MAIN_SID):
            return ()

        specs: list[EntitySpec] = [_switch_spec(_MAIN_SID, _MAIN_KEY, _MAIN_NAME)]
        for sid in _service_ids(context.profile):
            if not sid.startswith("switch") or sid == _MAIN_SID:
                continue
            label = context.value(sid, "name")
            specs.append(
                _switch_spec(
                    sid,
                    f"sw_{sid}",
                    str(label) if label else sid.replace("switch", "按键"),
                )
            )
        if context.has_service(_LED_SID):
            specs.append(_backlight_spec())
        return tuple(specs)


ADAPTER = Product153EAdapter()
