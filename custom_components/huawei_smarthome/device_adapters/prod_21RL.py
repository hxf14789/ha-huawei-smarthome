"""User-contributed protocol for Huawei product 21RL (德施曼 智能门锁 SHEP-SL0-DN).

Profile（profiles/21RL.json）+ 真机上报（2026-09-16）。

⚠️ **Profile 里没有「当前锁舌状态」**：`lockState.state` 是 0=休眠中 / 1=已连接 ——
   那是**连接态**而不是锁着没锁，真机也只报 `event`（谁开的锁）。所以：
   - **不建 lock 实体**（拿连接态冒充锁状态就是瞎报）
   - **不做开锁动作**：华为侧远程开锁走 `remoteCode`（cipherText W，= 下发临时密码），
     有安全含义且需要管理员密码，不碰。

暴露只读：
   sensor 电池电量     battery.level 0~100（真机 54）
   sensor 锁模式       lockMode.mode 0正常模式 / 1离家模式 / 2在家模式
   sensor 最近开锁      event.event 枚举（真机：指纹开锁）
   sensor 最近开锁时间  event.eventTime（真机 2026-09-16 20:21:15）

可用性（2026-09-18 补，对齐 KW5J 的 v3.2 兜底）：
   门锁是电池低功耗设备，**为省电常年休眠，华为云端就把它标成离线**。
   2026-09-18 实测：云上 `online=False`，但 53 个字段全在 —— 电量 54%、lockMode=1（离家模式）、
   eventTime=2026-09-17 21:02:32、lockState.state=0（休眠中）都读得到。
   若按默认的 context.available 判可用性，这 4 个实体就常年 unavailable —— 数据明明有却看不见。
   故改用 `lock_available`：**默认保持可用、显示最后一次缓存值**；只有「电量 < 5%
   且 24 小时内完全没有任何上报」才判真离线（= 真断电 / 被拆）。
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_MODE_SID, _MODE_FIELD = "lockMode", "mode"
_BATTERY_SID, _BATTERY_FIELD = "battery", "level"
_EVENT_SID, _EVENT_FIELD = "event", "event"
_EVENT_TIME_FIELD = "eventTime"
_LAST_ACTION_SID, _LAST_ACTION_FIELD = "lastActionTime", "time"

# 真离线兜底：电量低于此值 且 超过这么多小时没有任何上报，才判门锁真的不在线
_LOW_BATTERY = 5
_STALE_HOURS = 24.0

_MODE_LABELS = {0: "正常模式", 1: "离家模式", 2: "在家模式"}
_EVENT_LABELS = {
    1: "指纹开锁",
    2: "密码开锁",
    3: "华为智卡开锁",
    4: "临时密码开锁",
    5: "双重认证开锁",
}


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _fmt_time(raw: Any) -> str | None:
    """云端时间戳 ``20260916T202115Z`` → ``2026-09-16 20:21:15``；1970 = 从未发生 → None。"""
    if not isinstance(raw, str) or len(raw) < 15:
        return None
    if raw.startswith("1970"):
        return None
    return "%s-%s-%s %s:%s:%s" % (
        raw[0:4], raw[4:6], raw[6:8], raw[9:11], raw[11:13], raw[13:15]
    )


def _parse_stamp(raw: Any) -> datetime | None:
    """``20260918T074055Z`` → datetime(UTC)；空 / 1970 / 非法 → None。"""
    if not isinstance(raw, str) or len(raw) < 15 or raw.startswith("1970"):
        return None
    try:
        return datetime.strptime(raw[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _newest_report_age_hours(device: DeviceContext) -> float | None:
    """最近一次有效上报距今多少小时（event.eventTime 与 lastActionTime 取最新）。"""
    now = datetime.now(timezone.utc)
    stamps = (
        _parse_stamp(device.value(_EVENT_SID, _EVENT_TIME_FIELD)),
        _parse_stamp(device.value(_LAST_ACTION_SID, _LAST_ACTION_FIELD)),
    )
    ages = [max(0.0, (now - s).total_seconds()) / 3600.0 for s in stamps if s is not None]
    return min(ages) if ages else None


def lock_available(device: DeviceContext) -> bool:
    """电池门锁的可用性：**云离线 ≠ 设备坏了**。

    本机型从不实际上报连接态，云上 online=False 只是「休眠省电」，缓存值仍然有效；
    所以默认保持可用（沿用 KW5J 的 v3.2 兜底），只在「电量 < _LOW_BATTERY 且
    _STALE_HOURS 内零上报」时才转 unavailable。电量 / 时间拿不到时保守判可用。
    """
    level = _as_int(device.value(_BATTERY_SID, _BATTERY_FIELD))
    if level is None or level < 0 or level >= _LOW_BATTERY:
        return True
    age = _newest_report_age_hours(device)
    return age is None or age <= _STALE_HOURS


def _enum_sensor(sid: str, field: str, labels: Mapping[int, str], key: str, name: str,
                 availability: Any = None) -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        code = _as_int(device.value(sid, field))
        return {"native_value": labels.get(code) if code is not None else None}

    return EntitySpec(platform="sensor", key=key, name=name, state=state, availability=availability)


class Product21RLAdapter:
    """21RL 德施曼门锁：只读状态（电量 / 模式 / 最近开锁）。"""

    prod_id = "21RL"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service(_MODE_SID):
            return ()

        def battery_state(device: DeviceContext) -> Mapping[str, Any]:
            level = _as_int(device.value(_BATTERY_SID, _BATTERY_FIELD))
            return {"native_value": None if level is None or level < 0 else float(level)}

        def event_time_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"native_value": _fmt_time(device.value(_EVENT_SID, _EVENT_TIME_FIELD))}

        return (
            EntitySpec(
                platform="sensor",
                key="battery",
                name="门锁电量",
                state=battery_state,
                metadata={"device_class": "battery", "unit": "%", "state_class": "measurement"},
                availability=lock_available,
            ),
            _enum_sensor(_MODE_SID, _MODE_FIELD, _MODE_LABELS, "lock_mode", "门锁模式",
                         availability=lock_available),
            _enum_sensor(_EVENT_SID, _EVENT_FIELD, _EVENT_LABELS, "last_event", "最近开锁",
                         availability=lock_available),
            EntitySpec(
                platform="sensor",
                key="last_event_time",
                name="最近开锁时间",
                state=event_time_state,
                availability=lock_available,
            ),
        )


ADAPTER = Product21RLAdapter()
