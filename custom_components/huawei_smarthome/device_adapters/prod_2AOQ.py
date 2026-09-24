"""User-contributed protocol for Huawei product 2AOQ (杜亚 DH6 电动窗帘).

证据（2026-09-16 实测）：集成状态文件 `.storage/huawei_smarthome.<entry>.state`
+ 产品 Profile `.storage/huawei_smarthome/profiles/2AOQ.json`。

字段：
  mode.mode           enum RW  0=关 1=开 2=暂停          （Profile enumList 明确）
  opener.current      int  R   0~100 当前开合度（0=闭合, 100=全开）
  opener.target       int  RW  0~100 目标开合度

暴露一个 cover：打开 / 关闭 / 暂停 / 指定位置。
注: current 0~100 默认按「0=闭合、100=全开」映射到 HA；
    若实测方向相反, 将 _POS_REVERSED 置 True 即可。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_POS_MIN = 0
_POS_MAX = 100

# 若实测开合度方向与 HA 相反(HA: 0=关 100=开), 置 True 取反
_POS_REVERSED = False

# mode.mode 枚举（Profile）
_MODE_CLOSE = 0
_MODE_OPEN = 1
_MODE_STOP = 2


def _number(value: Any) -> int | None:
    """容忍 int / 数字字符串 / bool；非数值返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(round(number))


def _position(value: Any) -> int | None:
    position = _number(value)
    if position is None:
        return None
    position = min(max(position, _POS_MIN), _POS_MAX)
    return _POS_MAX - position if _POS_REVERSED else position


class Product2AOQAdapter:
    """杜亚 DH6：一个 cover 实体。"""

    prod_id = "2AOQ"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("opener"):
            return ()

        def cover_state(device: DeviceContext) -> Mapping[str, Any]:
            position = _position(device.value("opener", "current"))
            return {
                "current_position": position,
                "is_closed": position == 0 if position is not None else None,
            }

        async def _send_mode(device: DeviceContext, mode: int) -> None:
            await device.async_send_service("mode", {"mode": mode})

        async def open_cover(device: DeviceContext, _data: Mapping[str, Any]) -> None:
            await _send_mode(device, _MODE_OPEN)

        async def close_cover(device: DeviceContext, _data: Mapping[str, Any]) -> None:
            await _send_mode(device, _MODE_CLOSE)

        async def stop_cover(device: DeviceContext, _data: Mapping[str, Any]) -> None:
            await _send_mode(device, _MODE_STOP)

        async def set_position(device: DeviceContext, data: Mapping[str, Any]) -> None:
            raw = _number(data.get("position"))
            if raw is None:
                raise ValueError("position is required")
            position = min(max(raw, _POS_MIN), _POS_MAX)
            await device.async_send_service(
                "opener", {"target": _POS_MAX - position if _POS_REVERSED else position}
            )

        actions = {"open": open_cover, "close": close_cover}
        if context.has_service("mode"):
            actions["stop"] = stop_cover
        if context.has_service("opener"):
            actions["set_position"] = set_position

        return (
            EntitySpec(
                platform="cover",
                key="curtain",
                name=None,
                state=cover_state,
                actions=actions,
            ),
        )


ADAPTER = Product2AOQAdapter()
