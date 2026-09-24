"""User-contributed protocol for Huawei product X0A0 (华为 AI 音箱 FLMG-10).

设备类型: 华为 AI 音箱（FLMG-10；实测 2 台，左/右声道 stereo 配对）
制造商: 华为
Profile（profiles/X0A0.json）:
   smartspeaker.playControl enum RW  0=停止播放 1=启动播放 2=上一首 3=下一首
   audioplayer.playState  enum RW    0=暂停 1=播放中 2=停止
   speakerState.State     enum R     0=待机中 1=拾音中 2=等待响应 3=语音播报

本适配器暴露一个 media_player：播放 / 暂停 / 停止 / 上一首 / 下一首。
真机实测修正（官方 Profile 有两处笔误）:
- playControl 的 enumList 把「上一首」「下一首」都写成 2；实测 3 才是「下一首」。
- audioplayer.playState 虽标 RW，但写它一律被云端拒绝（errcode=-1）→ 暂停/停止只能走
  smartspeaker.playControl=0（资料写「停止播放」，实测效果=暂停，且能被 =1 恢复播放）；
  设备没有独立的「停止」态，故 pause 与 stop 同效。
- 音量字段在 X0A0 的 Profile 与真机上报里都不明确（`speaker` 只报 equalizer、
  `sleepHelp.volume` 是睡眠辅助音量）→ 不暴露音量。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_STATE_PLAYING = "playing"
_STATE_PAUSED = "paused"
_STATE_IDLE = "idle"


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


async def _play(device: DeviceContext, _data: Mapping[str, Any]) -> None:
    await device.async_send_service("smartspeaker", {"playControl": 1})


async def _pause(device: DeviceContext, _data: Mapping[str, Any]) -> None:
    # 真机实测：写 audioplayer.playState 一律被云端拒（errcode=-1），
    # 暂停只能走 smartspeaker.playControl=0（资料叫「停止播放」，实际=暂停，可被 =1 恢复）
    await device.async_send_service("smartspeaker", {"playControl": 0})


async def _previous_track(device: DeviceContext, _data: Mapping[str, Any]) -> None:
    await device.async_send_service("smartspeaker", {"playControl": 2})


async def _next_track(device: DeviceContext, _data: Mapping[str, Any]) -> None:
    await device.async_send_service("smartspeaker", {"playControl": 3})


class ProductX0A0Adapter:
    """X0A0 华为 AI 音箱：一个 media_player。"""

    prod_id = "X0A0"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("audioplayer"):
            return ()

        def player_state(device: DeviceContext) -> Mapping[str, Any]:
            code = _as_int(device.value("audioplayer", "playState"))
            if code == 1:
                state = _STATE_PLAYING
            elif code == 0:
                state = _STATE_PAUSED
            else:
                state = _STATE_IDLE
            return {"state": state}

        return (
            EntitySpec(
                platform="media_player",
                key="speaker",
                name=None,
                state=player_state,
                actions={"play": _play, "pause": _pause, "stop": _pause,   # 设备无独立停止态
                         "previous": _previous_track, "next": _next_track},
            ),
        )


ADAPTER = ProductX0A0Adapter()
