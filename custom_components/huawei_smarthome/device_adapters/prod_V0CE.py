"""User-contributed protocol for Huawei product V0CE (智慧屏 V75 Pro, FREU-570A).

证据：
- 真机上报服务（2026-09-16 集成状态文件）：`screen` / `speaker` / `inputSource` /
  `devicestate` / `pictureMode` / `systemMode` / `audioPlayer` / `videoPlayer` 等约 30 个
  —— Profile 只声明 6 个（messageboard/remotecontrol/autoconfig/devicestate/
  generalcommand/logreport），所以实体一律按**真机上报的服务**建，缺了就丢。
- 写命令实证抄自同系列 `prod_v0a2.py`（华为智慧屏 V 系列，服务结构一致，
  每条都经真机 `errcode=0` + `deviceDataChanged` 回推确认）：
  `speaker.volume` / `speaker.mute` / `inputSource.name` / `screen.brightness` / `screen.on`

⚠️ 已知固件限制（V0A2 实测、厂家 App 同样表现）：`screen.on = true`（开机）云端会受理、
   面板真会亮，但电视**不上报** `on: true` → 唤醒后 HA 会停在上一次的 `off`，直到电视
   推别的状态。关机（`on=false`）则正常上报。
⚠️ 被拒的命令（errcode=-1，故不暴露）：`systemMode` / `screenSaver` / `switch`。

暴露：一个 media_player（开关 / 音量 / 静音 / 输入源）+ 一个 number（屏幕亮度）。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_VOLUME_MAX = 100
_BRIGHTNESS_MAX = 100

_SCREEN_SID = "screen"
_SCREEN_BRIGHTNESS_FIELD = "brightness"
_SCREEN_ON_FIELD = "on"
_SPEAKER_SID = "speaker"
_SPEAKER_VOLUME_FIELD = "volume"
_SPEAKER_MUTE_FIELD = "mute"
_INPUT_SOURCE_SID = "inputSource"
_INPUT_SOURCE_FIELD = "name"


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
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


# 关于 `screen.on`（开关）：**电视在线时是有效的**（2026-09-16 真机实测：能熄屏、也能再按亮屏），
# 只有**离线时**才被云端拒（`HuaweiCommandRejectedError: sid=screen errcode=1001`）。
# ⚠️ 2026-09-17：曾改成「一次性熄屏 button」，结果熄屏后没法再按亮 → 恢复成 media_player 的
#    on/off 开关（双向）。别再退回单向 button。
async def _turn_on(device: DeviceContext, _data: Mapping[str, Any]) -> None:
    await device.async_send_service(_SCREEN_SID, {_SCREEN_ON_FIELD: True})


async def _turn_off(device: DeviceContext, _data: Mapping[str, Any]) -> None:
    await device.async_send_service(_SCREEN_SID, {_SCREEN_ON_FIELD: False})



async def _set_volume(device: DeviceContext, data: Mapping[str, Any]) -> None:
    """HA 交来 0~1 浮点；设备要 0~100。"""
    raw = data.get("volume")
    level = _number(raw)
    if level is None:
        return
    if isinstance(raw, float) and 0.0 <= raw <= 1.0:
        level = round(raw * _VOLUME_MAX)
    level = min(max(level, 0), _VOLUME_MAX)
    await device.async_send_service(_SPEAKER_SID, {_SPEAKER_VOLUME_FIELD: int(level)})


async def _select_source(device: DeviceContext, data: Mapping[str, Any]) -> None:
    source = data.get("source")
    if not isinstance(source, str) or not source.strip():
        return
    await device.async_send_service(_INPUT_SOURCE_SID, {_INPUT_SOURCE_FIELD: source.strip()})


async def _set_brightness(device: DeviceContext, data: Mapping[str, Any]) -> None:
    value = _number(data.get("value"))
    if value is None:
        return
    value = min(max(value, 0), _BRIGHTNESS_MAX)
    await device.async_send_service(_SCREEN_SID, {_SCREEN_BRIGHTNESS_FIELD: int(value)})


class ProductV0CEAdapter:
    """智慧屏 V75 Pro：media_player（电视）+ number（亮度）。"""

    prod_id = "V0CE"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service(_SPEAKER_SID):
            return ()

        def tv_state(device: DeviceContext) -> Mapping[str, Any]:
            raw_volume = _number(device.value(_SPEAKER_SID, _SPEAKER_VOLUME_FIELD))
            volume = (
                min(max(raw_volume, 0), _VOLUME_MAX) / _VOLUME_MAX
                if raw_volume is not None
                else None
            )
            on = _flag(device.value(_SCREEN_SID, _SCREEN_ON_FIELD))
            return {
                "state": "on" if on else ("off" if on is False else None),
                "volume_level": volume,
                "is_volume_muted": _flag(device.value(_SPEAKER_SID, _SPEAKER_MUTE_FIELD)),
                "source": device.value(_INPUT_SOURCE_SID, _INPUT_SOURCE_FIELD),
            }

        specs: list[EntitySpec] = [
            EntitySpec(
                platform="media_player",
                key="tv",
                name=None,
                state=tv_state,
                # 真机实测：设备层显示“离线”时命令照样生效（云端会唤醒设备）
                # → 不能因为集成层面的 offline 就把实体标成不可用、连带把命令也拦掉。
                availability=lambda _device: True,
                actions={
                    "turn_on": _turn_on,
                    "turn_off": _turn_off,
                    "volume": _set_volume,
                    "select_source": _select_source,
                },
            )
        ]

        if context.has_service(_SCREEN_SID):
            def brightness_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "native_value": _number(device.value(_SCREEN_SID, _SCREEN_BRIGHTNESS_FIELD))
                }

            specs.append(
                EntitySpec(
                    platform="number",
                    key="screen_brightness",
                    name="屏幕亮度",
                    state=brightness_state,
                    metadata={"min": 0, "max": _BRIGHTNESS_MAX, "step": 1},
                    availability=lambda _device: True,      # 同 media_player：别因离线把命令一起拦掉
                    actions={"set_value": _set_brightness},
                )
            )
        return tuple(specs)


ADAPTER = ProductV0CEAdapter()
