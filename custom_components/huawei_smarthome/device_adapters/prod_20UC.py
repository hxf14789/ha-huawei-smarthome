"""User-contributed protocol for Huawei product 20UC (领普双键墙壁开关 Q3D-HW-W2).

证据（2026-09-16 实测）：集成状态文件 `.storage/huawei_smarthome.<entry>.state`
+ 产品 Profile `.storage/huawei_smarthome/profiles/20UC.json`。

字段：
  switch.on          int  RW  面板总开关
  switch1..2.on      int  RW  分键继电器（Profile 是双键，只有 switch1/switch2）
  switch1..2.name    str  RW  按键名字（真机上报如 床头灯 / 灯带；未接线的键不上报）
  led.brightness     int  RW  面板背光/指示灯亮度 0~100（**不是**灯亮度，同义实现见 prod_2mh8）

暴露：总开关 + 每个分键一个 switch + 一个 number（指示灯亮度）。
按键列表以 **Profile** 为准：云端会多播一个没有名字的 switch3，但 20UC 是双键产品，
按运行时状态枚举会建出打不开的幽灵实体，故只认 Profile 声明的 switch1/switch2。
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
    """上报的 0/1（或 bool/字符串）→ bool；其它值保持未知。"""

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
    """面板指示灯亮度（0~100），写 `led.brightness`。"""

    def state(device: DeviceContext) -> Mapping[str, Any]:
        return {"native_value": _number(device.value(_LED_SID, _LED_FIELD))}

    async def set_value(device: DeviceContext, data: Mapping[str, Any]) -> None:
        value = _number(data.get("value"))
        if value is None:
            raise ValueError("backlight brightness is required")
        await device.async_send_service(
            _LED_SID, {_LED_FIELD: int(round(value))}
        )

    return EntitySpec(
        platform="number",
        key="led_brightness",
        name="指示灯亮度",
        state=state,
        metadata={"min": _LED_RANGE[0], "max": _LED_RANGE[1], "step": 1},
        actions={"set_value": set_value},
    )


class Product20UCAdapter:
    """领普双键面板：总开关 + 2 路按键 + 指示灯亮度。"""

    prod_id = "20UC"

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


ADAPTER = Product20UCAdapter()
