"""User-contributed protocol for Huawei product 25R1 (智多豚 摄像头 DPH-OP-100).

Profile（`device/guide/25R1/25R1.json`，deviceTypeId 008）+ 真机上报（2026-09-16）：
  switch.on                 bool RW  1=开 0=关（真机 1）
  alarmEvent.humanBodyAlarm bool R   0=无告警 1=有告警
  alarmEvent.videoAlarm     bool R   0=无告警 1=有告警

暴露：switch（摄像头开关）+ binary_sensor（人体告警 / 画面告警）。

⚠️ 真机还上报 `secSwitch`（移动侦测），但 **Profile 里没有这个 sid** → 不发写命令、不暴露。
   `alarmEvent.*` 在 Profile 里标的是 RW，但那多半是云端回执用的字段，主动写语义不明 → 只读。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_ALARM_SID = "alarmEvent"


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


class Product25R1Adapter:
    """25R1 摄像头：开关 + 两个告警信号。"""

    prod_id = "25R1"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("switch"):
            return ()

        def switch_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"is_on": _flag(device.value("switch", "on"))}

        async def turn_on(device: DeviceContext, _data: Mapping[str, Any]) -> None:
            await device.async_send_service("switch", {"on": 1})

        async def turn_off(device: DeviceContext, _data: Mapping[str, Any]) -> None:
            await device.async_send_service("switch", {"on": 0})

        specs: list[EntitySpec] = [
            EntitySpec(
                platform="switch",
                key="switch",
                name=None,
                state=switch_state,
                actions={"turn_on": turn_on, "turn_off": turn_off},
            )
        ]

        if context.has_service(_ALARM_SID):
            for field, key, name in (
                ("humanBodyAlarm", "human", "人体告警"),
                ("videoAlarm", "video", "画面告警"),
            ):
                def alarm_state(device: DeviceContext, _field: str = field) -> Mapping[str, Any]:
                    return {"is_on": _flag(device.value(_ALARM_SID, _field))}

                specs.append(
                    EntitySpec(
                        platform="binary_sensor",
                        key=key,
                        name=name,
                        state=alarm_state,
                    )
                )
        return tuple(specs)


ADAPTER = Product25R1Adapter()
