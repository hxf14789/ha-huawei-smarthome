"""User-contributed protocol for Huawei product 20Q0 (三思柔光护眼圆盘台灯).

设备类型: 智能台灯 (Table Lamp), 型号 C22RL-TD06
制造商: 上海三思 (Sansi)

核心服务:
    switch.on                    bool RW  开关 (1=开, 0=关)
    brightness.brightness        int  RW  亮度 1-100
    cct.colorTemperature         int  RW  色温 2700-4000
    colourMode.mode              enum R   颜色模式(1=冷暖光,4=设备预置模式)
    lightMode.mode               enum RW  灯光模式
                                  (100=浪漫烛光,101=晚宴美妆,102=自拍达人)
    tomatoClk.enable             bool RW  番茄钟开关
    tomatoClk.status             enum R   番茄钟状态(0=工作中,1=休息中)
    tomatoClk.num                int  RW  番茄钟循环次数 1-6
    writing.state                bool RW  书写模式
    reading.state                bool RW  阅读模式
    relax.state                  bool RW  休闲模式
    loving.state                 bool RW  自定义模式

未暴露:
    timer/delay  复杂数组服务(定时器/倒计时)
    update       App 专用 OTA 升级
    netInfo      网络诊断信息

本适配器暴露:
    1.  switch        开关
    2.  number        亮度
    3.  number        色温
    4.  sensor        颜色模式
    5.  select        灯光模式
    6.  switch        番茄钟
    7.  sensor        番茄钟状态
    8.  number        番茄钟循环次数
    9.  switch        书写
    10. switch        阅读
    11. switch        休闲
    12. switch        自定义
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext


# ---- 枚举映射 ------------------------------------------------------------

_LIGHT_MODE_OPTIONS = ["浪漫烛光", "晚宴美妆", "自拍达人"]
_LIGHT_MODE_VALUES = [100, 101, 102]
_MODE_NAME_TO_VAL = dict(zip(_LIGHT_MODE_OPTIONS, _LIGHT_MODE_VALUES))
_MODE_VAL_TO_NAME = dict(zip(_LIGHT_MODE_VALUES, _LIGHT_MODE_OPTIONS))

_COLOUR_MODE_TEXT = {
    1: "冷暖光",
    4: "设备预置模式",
}

_TOMATO_STATUS_TEXT = {
    0: "工作中",
    1: "休息中",
}


# ---- 工具函数 ------------------------------------------------------------

def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, str):
        try:
            return int(round(float(value.strip())))
        except (TypeError, ValueError):
            return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.casefold() in {"1", "true", "on"}:
            return True
        if value.casefold() in {"0", "false", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


# ---- 动作函数 ------------------------------------------------------------

async def _turn_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 1})


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 0})


async def _set_brightness(context: DeviceContext, data: Mapping[str, Any]) -> None:
    value = _as_int(data.get("value"))
    if value is None:
        return
    value = max(1, min(100, value))
    await context.async_send_service("brightness", {"brightness": value})


async def _set_color_temp(context: DeviceContext, data: Mapping[str, Any]) -> None:
    value = _as_int(data.get("value"))
    if value is None:
        return
    value = max(2700, min(4000, value))
    await context.async_send_service("cct", {"colorTemperature": value})


async def _select_light_mode(context: DeviceContext, data: Mapping[str, Any]) -> None:
    val = _MODE_NAME_TO_VAL.get(str(data.get("option")))
    if val is None:
        raise ValueError(f"unsupported light mode: {data.get('option')}")
    await context.async_send_service("lightMode", {"mode": val})


async def _set_tomato_num(context: DeviceContext, data: Mapping[str, Any]) -> None:
    value = _as_int(data.get("value"))
    if value is None:
        return
    value = max(1, min(6, value))
    await context.async_send_service("tomatoClk", {"num": value})


def _scene_toggle_actions(sid: str, field: str) -> dict[str, Any]:
    # 平台约定: switch 平台调用 turn_on/turn_off 时传入空 data,
    # 方向必须由闭包本身携带, 不能从 data 读取。
    async def _turn_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
        await context.async_send_service(sid, {field: 1})

    async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
        await context.async_send_service(sid, {field: 0})

    return {"turn_on": _turn_on, "turn_off": _turn_off}


# ---- 适配器 --------------------------------------------------------------

class Product20Q0Adapter:
    """20Q0 三思柔光护眼圆盘台灯适配器。"""

    prod_id = "20Q0"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("switch"):
            return ()

        # ---- 状态读取 ----------------------------------------------------

        def power_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"is_on": _as_bool(device.value("switch", "on"))}

        def brightness_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"native_value": _as_int(device.value("brightness", "brightness"))}

        def color_temp_state(device: DeviceContext) -> Mapping[str, Any]:
            return {
                "native_value": _as_int(device.value("cct", "colorTemperature"))
            }

        def colour_mode_state(device: DeviceContext) -> Mapping[str, Any]:
            val = _as_int(device.value("colourMode", "mode"))
            return {"native_value": _COLOUR_MODE_TEXT.get(val, "未知")}

        def light_mode_state(device: DeviceContext) -> Mapping[str, Any]:
            val = _as_int(device.value("lightMode", "mode"))
            return {
                "current_option": _MODE_VAL_TO_NAME.get(
                    val, _LIGHT_MODE_OPTIONS[0]
                )
            }

        def tomato_enable_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"is_on": _as_bool(device.value("tomatoClk", "enable"))}

        def tomato_status_state(device: DeviceContext) -> Mapping[str, Any]:
            val = _as_int(device.value("tomatoClk", "status"))
            return {"native_value": _TOMATO_STATUS_TEXT.get(val, "未知")}

        def tomato_num_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"native_value": _as_int(device.value("tomatoClk", "num"))}

        def writing_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"is_on": _as_bool(device.value("writing", "writing"))}

        def reading_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"is_on": _as_bool(device.value("reading", "reading"))}

        def relax_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"is_on": _as_bool(device.value("relax", "relax"))}

        def loving_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"is_on": _as_bool(device.value("loving", "loving"))}

        # ---- 实体列表 ----------------------------------------------------

        result = [
            EntitySpec(
                platform="switch",
                key="power",
                name="开关",
                state=power_state,
                actions={"turn_on": _turn_on, "turn_off": _turn_off},
            ),
        ]
        if context.has_service("brightness"):
            result.append(
                EntitySpec(
                    platform="number",
                    key="brightness",
                    name="亮度",
                    state=brightness_state,
                    metadata={"min": 1, "max": 100, "step": 1, "unit": "%"},
                    actions={"set_value": _set_brightness},
                )
            )
        if context.has_service("cct"):
            result.append(
                EntitySpec(
                    platform="number",
                    key="color_temp",
                    name="色温",
                    state=color_temp_state,
                    metadata={"min": 2700, "max": 4000, "step": 20, "unit": "K"},
                    actions={"set_value": _set_color_temp},
                )
            )
        if context.has_service("colourMode"):
            result.append(
                EntitySpec(
                    platform="sensor",
                    key="colour_mode",
                    name="颜色模式",
                    state=colour_mode_state,
                    metadata={"icon": "mdi:palette"},
                )
            )
        if context.has_service("lightMode"):
            result.append(
                EntitySpec(
                    platform="select",
                    key="light_mode",
                    name="灯光模式",
                    state=light_mode_state,
                    metadata={"options": _LIGHT_MODE_OPTIONS},
                    actions={"select_option": _select_light_mode},
                )
            )
        if context.has_service("tomatoClk"):
            result.extend(
                (
                    EntitySpec(
                        platform="switch",
                        key="tomato_enable",
                        name="番茄钟",
                        state=tomato_enable_state,
                        actions=_scene_toggle_actions("tomatoClk", "enable"),
                        metadata={"icon": "mdi:timer-sand"},
                    ),
                    EntitySpec(
                        platform="sensor",
                        key="tomato_status",
                        name="番茄钟状态",
                        state=tomato_status_state,
                        metadata={"icon": "mdi:timer-outline"},
                    ),
                    EntitySpec(
                        platform="number",
                        key="tomato_num",
                        name="番茄钟循环次数",
                        state=tomato_num_state,
                        metadata={"min": 1, "max": 6, "step": 1},
                        actions={"set_value": _set_tomato_num},
                    ),
                )
            )
        scene_services = (
            ("writing", "writing", "书写", writing_state),
            ("reading", "reading", "阅读", reading_state),
            ("relax", "relax", "休闲", relax_state),
            ("loving", "loving", "自定义", loving_state),
        )
        for sid, key, name, state in scene_services:
            if not context.has_service(sid):
                continue
            result.append(
                EntitySpec(
                    platform="switch",
                    key=key,
                    name=name,
                    state=state,
                    actions=_scene_toggle_actions(sid, sid),
                    metadata={"icon": "mdi:desk-lamp-outline"},
                )
            )
        return tuple(result)


ADAPTER = Product20Q0Adapter()
