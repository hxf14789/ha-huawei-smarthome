"""User-contributed protocol for Huawei product 21DU (汇唐光电 水母云智能灯带 Lightstrip-S).

证据（2026-09-16 实测）：Profile `.storage/huawei_smarthome/profiles/21DU.json` + 真机状态
（实测 2 台灯带：brightness 10/80、colour=240,135,20、cct=5000、lightMode.mode=7，均为真机上报值）。

字段：
  switch.on               int    RW  总开关
  brightness.brightness   int    RW  亮度 1~100
  colour.red/green/blue   int    RW  各 0~255
  cct.colorTemperature    int    RW  2000~5000 K
  lightMode.mode          enum   RW  16 种预设模式（休闲/观影/…/七彩渐变/自然醒…）
  colourMode.mode         enum   RW  枚举里只有「设备预置模式」(4)，与 colour 的联动**未验证**，先不发
  streamer.*              array  RW  流光配置，未验证，不暴露

暴露：light（开关 / 亮度 / RGB / 色温）+ select（灯光模式）。
亮度做 1~100 ↔ HA 0~255 换算；不带 color_mode（HA 会按已声明的 rgb 作为当前模式）。
预设模式生效时云端仍回报上一次的 colour/cct，属设备行为，不在这里伪造。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_SW_SID = "switch"
_SW_FIELD = "on"
_BRI_SID = "brightness"
_BRI_FIELD = "brightness"
_BRI_RANGE = (1.0, 100.0)
_RGB_SID = "colour"
_CCT_SID = "cct"
_CCT_FIELD = "colorTemperature"
_CCT_RANGE = (2000, 5000)
_MODE_SID = "lightMode"
_MODE_FIELD = "mode"

# Profile enumList 的「值 → 中文名」，顺序按 Profile
_MODE_VALUES: tuple[tuple[str, int], ...] = (
    ("休闲模式", 1),
    ("观影模式", 2),
    ("用餐模式", 3),
    ("浪漫模式", 5),
    ("工作模式", 6),
    ("睡眠模式", 7),
    ("阅读模式", 8),
    ("光闹", 100),
    ("日出", 101),
    ("七彩渐变", 102),
    ("七彩跳变", 103),
    ("粉红可爱", 104),
    ("温暖喜庆", 105),
    ("海洋蓝", 106),
    ("自然醒", 107),
    ("伴睡", 108),
)


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


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _to_ha_brightness(raw: Any) -> int | None:
    """设备 1~100 → HA 0~255。"""

    value = _number(raw)
    if value is None:
        return None
    return int(round(_clamp(value, *_BRI_RANGE) * 255 / 100))


def _to_device_brightness(raw: Any) -> int | None:
    """HA 0~255 → 设备 1~100。"""

    value = _number(raw)
    if value is None:
        return None
    if value <= 0:
        value = 1
    return int(round(_clamp(value * 100 / 255, *_BRI_RANGE)))


def _rgb(device: DeviceContext) -> tuple[int, ...] | None:
    parts = tuple(_number(device.value(_RGB_SID, name)) for name in ("red", "green", "blue"))
    if any(part is None for part in parts):
        return None
    return tuple(int(_clamp(part, 0, 255)) for part in parts if part is not None)


def _light_state(device: DeviceContext) -> Mapping[str, Any]:
    return {
        "is_on": _flag(device.value(_SW_SID, _SW_FIELD)),
        "brightness": _to_ha_brightness(device.value(_BRI_SID, _BRI_FIELD)),
        "rgb_color": _rgb(device),
        "color_temp_kelvin": (_number(device.value(_CCT_SID, _CCT_FIELD))),
    }


async def _turn_on(device: DeviceContext, data: Mapping[str, Any]) -> None:
    await device.async_send_service(_SW_SID, {_SW_FIELD: 1})

    brightness = _to_device_brightness(data.get("brightness"))
    if brightness is not None:
        await device.async_send_service(_BRI_SID, {_BRI_FIELD: brightness})

    rgb = data.get("rgb_color")
    if isinstance(rgb, (tuple, list)) and len(rgb) == 3:
        red, green, blue = (int(_clamp(_number(part) or 0, 0, 255)) for part in rgb)
        await device.async_send_service(
            _RGB_SID, {"red": red, "green": green, "blue": blue}
        )

    kelvin = _number(data.get("color_temp_kelvin"))
    if kelvin is not None:
        await device.async_send_service(
            _CCT_SID, {_CCT_FIELD: int(round(_clamp(kelvin, *_CCT_RANGE)))}
        )


async def _turn_off(device: DeviceContext, _data: Mapping[str, Any]) -> None:
    await device.async_send_service(_SW_SID, {_SW_FIELD: 0})


def _light_spec() -> EntitySpec:
    return EntitySpec(
        platform="light",
        key="light",
        name=None,
        state=_light_state,
        metadata={
            "supported_color_modes": {"rgb", "color_temp"},
            "min_color_temp_kelvin": _CCT_RANGE[0],
            "max_color_temp_kelvin": _CCT_RANGE[1],
        },
        actions={"turn_on": _turn_on, "turn_off": _turn_off},
    )


def _mode_state(device: DeviceContext) -> Mapping[str, Any]:
    value = _number(device.value(_MODE_SID, _MODE_FIELD))
    for label, raw in _MODE_VALUES:
        if value == raw:
            return {"current_option": label}
    return {"current_option": None}


async def _set_mode(device: DeviceContext, data: Mapping[str, Any]) -> None:
    option = str(data.get("option"))
    for label, raw in _MODE_VALUES:
        if label == option:
            await device.async_send_service(_MODE_SID, {_MODE_FIELD: raw})
            return
    raise ValueError(f"unknown light mode: {option}")


def _mode_spec() -> EntitySpec:
    return EntitySpec(
        platform="select",
        key="light_mode",
        name="灯光模式",
        state=_mode_state,
        metadata={"options": [label for label, _ in _MODE_VALUES]},
        actions={"select_option": _set_mode},
    )


class Product21DUAdapter:
    """水母云灯带：一个 light（开关/亮度/RGB/色温）+ 一个 select（灯光模式）。"""

    prod_id = "21DU"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service(_SW_SID):
            return ()

        specs: list[EntitySpec] = []
        if context.has_service(_BRI_SID) or context.has_service(_CCT_SID) or context.has_service(_RGB_SID):
            specs.append(_light_spec())
        if context.has_service(_MODE_SID):
            specs.append(_mode_spec())
        return tuple(specs)


ADAPTER = Product21DUAdapter()
