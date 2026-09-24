"""User-contributed protocol for Huawei product 2BMO (海雀 智能门铃 DB001).

Profile（profiles/2BMO.json）+ 真机上报（2026-09-16）：
  doorBell.ringDoorBell   R  0=未按铃 1=按门铃
  doorBell.humanBodyAlarm R  0=没有匹配到人形 1=匹配到人形 2=持续一段时间内匹配到人形
  doorBell.lowPower       R  0=电量充足 1=低电状态（<20%）
  doorBell.doorBellState  R  0=休眠 1=在线
  call.call               RW 0=没有呼叫 1=呼叫       ← 写命令（主动呼叫室内机），无真机证据 → 不暴露
  strangerFace / face1..3 R  人脸匹配（enable/id/faceName/matched）← 属门铃自身配置，不暴露

暴露 4 个 binary_sensor：按铃 / 有人 / 低电 / 在线。
⚠️ 门铃是**电池设备、平时休眠**，`online=false` 是常态（真机就是这样）；状态以
   `doorBell.doorBellState` 为准，不要拿集成层面的 online 当故障。

⚠️⚠️ `ringDoorBell` 是**锁存值，不能当按铃用**（2026-09-17 真机实测）：
   一次按铃后它一直是 1、从不归零（17 小时里连一次 0 都没报过），而门铃每次被
   「人形逗留」唤醒都会把这块旧状态重报一遍（`humanBodyAlarm=2`、`repeaterCall=0`、
   `call=0` 一起带上来）→ 若按它建实体，则每次唤醒（集成把休眠设备标 offline→再上报）
   都会把实体从「不可用」翻成「开」，自动化于是反复误推「有人按门铃」。
   实测：07:25、07:39 两次逗留唤醒各误推一次，而 App 记录里那两条是「有人逗留」不是「呼叫」。
   真正只出现在按铃当时的瞬时字段是：
     call.call / call.calling  1=呼叫/通话中          （按铃=门铃主动呼叫）
     doorBell.repeaterCall     1=触发室内机响铃 / 2=停止（按铃才会响室内机）
   所以「按铃」= 上面这几项任一为活动态；它们会自己回到 0，不会锁存。
用途：`按铃` 这条可以直接配 HA 自动化 → 有人按门铃就推手机/企微。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_DOORBELL_SID = "doorBell"
_RING_FIELD = "ringDoorBell"          # 锁存值，仅供诊断，不用于「按铃」判定
_HUMAN_FIELD = "humanBodyAlarm"
_LOW_POWER_FIELD = "lowPower"
_ONLINE_FIELD = "doorBellState"
_CALL_SID = "call"
_REPEATER_FIELD = "repeaterCall"


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


def _binary(sid: str, field: str, key: str, name: str, truthy: frozenset[int]) -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        code = _as_int(device.value(sid, field))
        return {"is_on": None if code is None else code in truthy}

    return EntitySpec(platform="binary_sensor", key=key, name=name, state=state)


def _ring_state(device: DeviceContext) -> Mapping[str, Any]:
    """按铃：只认「正在呼叫 / 正在响铃」的瞬时字段（`ringDoorBell` 是锁存值，见模块注释）。"""

    values = [
        _as_int(device.value(_CALL_SID, "call")),
        _as_int(device.value(_CALL_SID, "calling")),
        _as_int(device.value(_DOORBELL_SID, _REPEATER_FIELD)),
    ]
    call, calling, repeater = values
    if call == 1 or calling == 1 or repeater in (1, 2):
        return {"is_on": True}
    if all(v is None for v in values):
        return {"is_on": None}          # 字段一个都没上报 → 未知，不假装「没按」
    return {"is_on": False}


class Product2BMOAdapter:
    """2BMO 海雀门铃：4 个只读 binary_sensor。"""

    prod_id = "2BMO"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service(_DOORBELL_SID):
            return ()

        return (
            EntitySpec(platform="binary_sensor", key="ring", name="门铃按铃", state=_ring_state),
            _binary(_DOORBELL_SID, _HUMAN_FIELD, "human", "有人", frozenset({1, 2})),
            _binary(_DOORBELL_SID, _LOW_POWER_FIELD, "low_power", "低电量", frozenset({1})),
            _binary(_DOORBELL_SID, _ONLINE_FIELD, "online", "在线", frozenset({1})),
        )


ADAPTER = Product2BMOAdapter()
