"""User-contributed protocol for Huawei product V0EN (华为Vision智慧屏 4).

设备型号 QINL-380B, 设备类型 09C 智慧屏 (Intelligent Vision)。
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/V0EN/V0EN.json

公开 Profile 只声明 6 个服务 (messageboard / remotecontrol / autoconfig /
devicestate / generalcommand / logreport), 且 20 个 characteristic 中
含写权限(W)的数量为 0, 单看 Profile 会误判为"纯只读设备"。

实机 (2026-09-19 读取 HA 状态文件) 实际上报 45 个服务, 与 V0EM/V0DL 同代架构,
且云端 operations = EXECUTE/READ/WRITE, 说明可写。因此本适配器按实机上报的
服务构建, 与 prod_V0EM.py 同源但按 V0EN 实测差异调整。

实机观测 (固件 QINL-LGRP1-CHN 4.3.0.252(SP11)):

    devicestate    screenState=1, screenSwitch=1
    screen         on=True, brightness=100, mode="STANDARD"
    switch         on=1
    speaker        volume=17, mute=False, equalizer="STANDARD"
    inputSource    name="HDMI1", defaultSource="HDMI1", fullScreenSwitch=False
    pictureMode    mode="1"
    voiceMode      mode="2"
    systemMode     mode="STANDARD_MODE"
    screenSaver    switch=0
    remotecontrol  ip_addr="******", switchState="1"
    netInfo        SSID="******"
    videoPlayer    state="FINISHED", metadata={vodName:...}
    audioPlayer    state="PAUSED", metadata={artist,track,title...}

与 V0EM (QINL-370B) 的实测差异:

    - V0EN 的 devicestate 同时上报 screenSwitch (V0EM 无此字段),
      故额外暴露 screen_switch 二进制传感器。
    - V0EN 另有 luminance / inputInterface / netInfo / cameraControl /
      homeView 等服务, 本适配器只取其中语义明确的 netInfo.SSID。
    - V0EN 存在字段名带尾随空格的脏数据 ("luminance ", "cmd ",
      "videoCall "), 读取一律用 strip 归一化后的字段名匹配。

写入策略 (方案 A: 仅电源可写, 其余只读):

    - 唯一可写实体是电源开关, 走 screen.on (V0EM 实机验证有效的开机通道)。
      写入按候选通道依次尝试, 首个成功即止。
    - 其余全部为只读传感器/二进制传感器。特别是音量: V0EM/V0DL 实测
      speaker.volume 存在云端假 ACK (设备不执行), 在 V0EN 实机确认前
      不做可写控件, 只读展示。
    - 不实现 Wake-on-LAN: V0EN 实测为 Wi-Fi 连接, WOL 基本无效, 且会引入
      写死的 MAC 与广播依赖, 故不采用。

未暴露的服务及原因 (宁可不出):

    - videoCall / cameraControl: 摄像头与通话, 涉及隐私, 不做实体。
    - homeCenter / d2dSubscribe / relateVisitor: 私有场景与协议载荷。
    - deviceInfo (udid/deviceCommId/loginStatus) / remotecontrol.access_token /
      deviceInteract.access_token / ctlCapability.authcode: 凭据与标识, 敏感。
    - capabilitySet / upgrade / update / diagnose / complain / appCenter /
      photoTable / cpLinkStatusReport / surroundSound / bluetooth /
      accessories / devCustomInfo / messageBoard / logreport / autoconfig /
      generalCommand / homeView: 诊断、维护、透传或空载荷, 非用户状态。
    - 音量另有 volume.volume 字段 (实测 "0"), 与 speaker.volume 语义冲突,
      存在假 ACK 风险, 只取 speaker.volume。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

try:  # 保留引用以兼容旧环境; 适配器内已不再依赖它翻译报错。
    from ..mqtt.commands import HuaweiCommandRejectedError  # noqa: F401
except Exception:  # pragma: no cover
    HuaweiCommandRejectedError = None


# ---------------------------------------------------------------- 服务 / 字段

# 电源状态以 devicestate.screenState 为准 (1=亮屏, 0=熄屏, 2=离线);
# screenSwitch 是 V0EN 独有的同步字段, 作为兜底。
_SCREEN_STATE_SID = "devicestate"
_SCREEN_STATE_FIELD = "screenState"
_SCREEN_SWITCH_FIELD = "screenSwitch"

# 开机实测走 screen.on (V0EM 同架构验证有效)。
_SCREEN_SID = "screen"
_SCREEN_ON_FIELD = "on"
_SCREEN_BRIGHTNESS_FIELD = "brightness"
_SCREEN_MODE_FIELD = "mode"

# switch.on 是 V0EM 实测有效的关机通道, 在 V0EN 作为候选之一。
_LEGACY_SWITCH_SID = "switch"
_LEGACY_SWITCH_FIELD = "on"

_SPEAKER_SID = "speaker"
_SPEAKER_VOLUME_FIELD = "volume"
_SPEAKER_MUTE_FIELD = "mute"
_SPEAKER_EQUALIZER_FIELD = "equalizer"

_PICTURE_MODE_SID = "pictureMode"
_PICTURE_MODE_FIELD = "mode"

_VOICE_MODE_SID = "voiceMode"
_VOICE_MODE_FIELD = "mode"

_INPUT_SOURCE_SID = "inputSource"
_INPUT_SOURCE_FIELD = "defaultSource"
_INPUT_SOURCE_NAME_FIELD = "name"

_SYSTEM_MODE_SID = "systemMode"
_SYSTEM_MODE_FIELD = "mode"

_SCREEN_SAVER_SID = "screenSaver"
_SCREEN_SAVER_FIELD = "switch"
_SCREEN_SAVER_ON = 1

_REMOTE_CONTROL_SID = "remotecontrol"
_REMOTE_CONTROL_IP_FIELD = "ip_addr"
_REMOTE_CONTROL_SWITCH_FIELD = "switchState"
_REMOTE_CONTROL_ON = 1

_NET_INFO_SID = "netInfo"
_NET_INFO_SSID_FIELD = "SSID"

_VIDEO_PLAYER_SID = "videoPlayer"
_AUDIO_PLAYER_SID = "audioPlayer"

_SCREEN_STATE_LABELS = {0: "熄屏", 1: "在线", 2: "离线"}

_PLAYER_STATE_MAP = {
    "PLAYING": "playing",
    "PAUSED": "paused",
    "BUFFERING": "buffering",
    "PREPARING": "buffering",
    "STOPPED": "idle",
    "STOP": "idle",
    "FINISHED": "idle",
    "COMPLETED": "idle",
    "IDLE": "idle",
}

_ACTIVE_PLAYER_STATES = frozenset({"PLAYING", "PAUSED", "BUFFERING", "PREPARING"})

# 播放器上报超过这个时长就算陈旧: 电视断电后最后一次的剧名会一直留在云端。
_STALE_AFTER_SECONDS = 30 * 60


# ------------------------------------------------------------------- 取值工具


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.casefold()
        if normalized in {"1", "true", "on"}:
            return True
        if normalized in {"0", "false", "off"}:
            return False
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _text(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        return text or None
    return None


def _json(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        import json

        parsed = json.loads(value)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, Mapping) else {}


def _seconds(value: Any) -> float | None:
    number = _number(value)
    return None if number is None else float(number)


# ------------------------------------------------------------------- 新鲜度


def _reported_at(device: DeviceContext, sid: str) -> datetime | None:
    getter = getattr(device, "reported_timestamp", None)
    stamp = getter(sid) if callable(getter) else None
    if not isinstance(stamp, str):
        timestamps = getattr(device, "_timestamps", None)
        if isinstance(timestamps, Mapping):
            stamp = timestamps.get(sid)
    if not isinstance(stamp, str) or not stamp:
        return None
    try:
        return datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _is_fresh(device: DeviceContext, sid: str) -> bool:
    stamp = _reported_at(device, sid)
    if stamp is None:
        return True
    return (datetime.now(timezone.utc) - stamp).total_seconds() <= _STALE_AFTER_SECONDS


# ------------------------------------------------------------------- 播放器


def _active_player(device: DeviceContext) -> tuple[str, Mapping[str, Any]]:
    video = (
        device.service_state(_VIDEO_PLAYER_SID)
        if device.has_service(_VIDEO_PLAYER_SID)
        else {}
    )
    audio = (
        device.service_state(_AUDIO_PLAYER_SID)
        if device.has_service(_AUDIO_PLAYER_SID)
        else {}
    )
    for sid, state in ((_VIDEO_PLAYER_SID, video), (_AUDIO_PLAYER_SID, audio)):
        if str(state.get("state") or "").upper() in _ACTIVE_PLAYER_STATES and _is_fresh(
            device, sid
        ):
            return sid, state
    return (_VIDEO_PLAYER_SID, video) if video else (_AUDIO_PLAYER_SID, audio)


def _screen_is_on(device: DeviceContext) -> bool | None:
    """屏幕是否点亮: screenState 1=亮屏, 0=熄屏, 2=离线; 兜底 screenSwitch。"""

    state = _number(device.value(_SCREEN_STATE_SID, _SCREEN_STATE_FIELD))
    if state is not None:
        return state == 1
    switch = _number(device.value(_SCREEN_STATE_SID, _SCREEN_SWITCH_FIELD))
    if switch is not None:
        return switch == 1
    return None


def _player_state(device: DeviceContext) -> str | None:
    # 熄屏优先: 播放器残留状态在息屏后一律不算数。
    if _screen_is_on(device) is False:
        return "off"
    sid, state = _active_player(device)
    raw = str(state.get("state") or "").upper()
    mapped = _PLAYER_STATE_MAP.get(raw)
    if mapped == "playing":
        return mapped
    if mapped in {"paused", "buffering"}:
        return mapped if _is_fresh(device, sid) else "on"
    if _screen_is_on(device) is True:
        return "on"
    return mapped


# ------------------------------------------------------------------- 实体构造


def _sensor(
    key: str,
    name: str,
    read,
    metadata: Mapping[str, Any] | None = None,
) -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        return {"native_value": read(device)}

    return EntitySpec(
        platform="sensor",
        key=key,
        name=name,
        state=state,
        metadata=dict(metadata or {}),
    )


def _binary(
    key: str,
    name: str,
    read,
    device_class: str | None = None,
) -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        return {"is_on": read(device)}

    return EntitySpec(
        platform="binary_sensor",
        key=key,
        name=name,
        state=state,
        metadata={"device_class": device_class} if device_class else {},
    )


def _media_player() -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        sid, player = _active_player(device)
        is_video = sid == _VIDEO_PLAYER_SID
        playing = _player_state(device) in {"playing", "paused", "buffering"}
        metadata = _json(player.get("metadata")) if playing else {}

        volume = _number(device.value(_SPEAKER_SID, _SPEAKER_VOLUME_FIELD))
        progress = _number(player.get("progress")) if playing else None
        duration = (
            _seconds(
                metadata.get("totalTime") if is_video else metadata.get("duration")
            )
            if playing
            else None
        )

        return {
            "state": _player_state(device),
            "volume_level": (
                None if volume is None else max(0.0, min(1.0, volume / 100.0))
            ),
            "is_volume_muted": _bool(device.value(_SPEAKER_SID, _SPEAKER_MUTE_FIELD)),
            "media_title": _text(metadata.get("vodName") or metadata.get("title")),
            "media_artist": _text(metadata.get("artist")) if not is_video else None,
            "media_album_name": _text(metadata.get("album")) if not is_video else None,
            "media_series_title": _text(metadata.get("vodName")) if is_video else None,
            "media_episode": _number(metadata.get("volumeIndex")) if is_video else None,
            # progress 单位是毫秒, duration/totalTime 是秒。
            "media_position": None if progress is None else progress / 1000.0,
            "media_duration": duration,
            "media_image_url": _text(metadata.get("titlePicture")) if is_video else None,
            "source": _text(device.value(_INPUT_SOURCE_SID, _INPUT_SOURCE_FIELD)),
            "source_list": None,
        }

    async def turn_on(device: DeviceContext, data: Mapping[str, Any]) -> None:
        del data
        await _power_on(device)

    async def turn_off(device: DeviceContext, data: Mapping[str, Any]) -> None:
        del data
        await _power_off(device)

    return EntitySpec(
        platform="media_player",
        key="player",
        name="播放",
        state=state,
        metadata={},
        # 音量故意不做可写控件: V0EM/V0DL 实测 speaker.volume 存在云端假 ACK。
        actions={"turn_on": turn_on, "turn_off": turn_off},
    )


async def _send_first_available(
    device: DeviceContext,
    attempts: tuple[tuple[str, Mapping[str, Any]], ...],
) -> None:
    """依次尝试候选写入通道, 首个成功即止; 全部失败则抛出最后一个错误。

    V0EN 的 devicestate / switch 等服务的可写性尚未在实机上逐条验证, 因此按
    成本从低到高排列候选通道, 并跳过设备未上报的服务。
    """

    last_err: Exception | None = None
    for sid, payload in attempts:
        if not device.has_service(sid):
            continue
        try:
            await device.async_send_service(sid, payload)
            return
        except Exception as err:  # noqa: BLE001
            last_err = err
    if last_err is not None:
        raise last_err


async def _power_on(device: DeviceContext) -> None:
    """亮屏/开机: screen.on 为主通道 (V0EM 实机验证有效)。"""

    await _send_first_available(
        device,
        (
            (_SCREEN_SID, {_SCREEN_ON_FIELD: True}),
            (_SCREEN_SID, {_SCREEN_ON_FIELD: 1}),
            (_LEGACY_SWITCH_SID, {_LEGACY_SWITCH_FIELD: 1}),
            (_SCREEN_STATE_SID, {_SCREEN_STATE_FIELD: 1}),
            (_SCREEN_STATE_SID, {_SCREEN_SWITCH_FIELD: 1}),
        ),
    )


async def _power_off(device: DeviceContext) -> None:
    """息屏/关机: screen.on=false 为主通道, 其余作兜底。"""

    await _send_first_available(
        device,
        (
            (_SCREEN_SID, {_SCREEN_ON_FIELD: False}),
            (_SCREEN_SID, {_SCREEN_ON_FIELD: 0}),
            (_LEGACY_SWITCH_SID, {_LEGACY_SWITCH_FIELD: 0}),
            (_SCREEN_STATE_SID, {_SCREEN_STATE_FIELD: 0}),
        ),
    )


def _power_switch() -> EntitySpec:
    """电源开关: 跟随 devicestate.screenState (1=亮屏, 0=熄屏/离线)。"""

    def is_on(device: DeviceContext) -> bool | None:
        return _screen_is_on(device)

    async def turn_on(device: DeviceContext, data: Mapping[str, Any]) -> None:
        del data
        await _power_on(device)

    async def turn_off(device: DeviceContext, data: Mapping[str, Any]) -> None:
        del data
        await _power_off(device)

    return EntitySpec(
        platform="switch",
        key="power_switch",
        name="电源",
        state=lambda device: {"is_on": is_on(device)},
        metadata={"icon": "mdi:television"},
        actions={"turn_on": turn_on, "turn_off": turn_off},
    )


def _flag(device: DeviceContext, sid: str, field: str) -> bool | None:
    """读取 0/1 或 true/false 类标志字段, 数值缺失时返回 None。"""

    value = _number(device.value(sid, field))
    if value is not None:
        return value == 1
    return _bool(device.value(sid, field))


class ProductV0ENAdapter:
    """华为 Vision 智慧屏 4 (QINL-380B) 的实体定义。"""

    prod_id = "V0EN"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None:
            return ()

        entities: list[EntitySpec] = []

        if context.has_service(_VIDEO_PLAYER_SID) or context.has_service(
            _AUDIO_PLAYER_SID
        ):
            entities.append(_media_player())

        # 电源开关是唯一可写实体, 以 devicestate 存在为前提。
        if context.has_service(_SCREEN_STATE_SID):
            entities.append(_power_switch())
            entities.append(
                _sensor(
                    "screen_state",
                    "屏幕状态",
                    lambda device: _SCREEN_STATE_LABELS.get(
                        _number(device.value(_SCREEN_STATE_SID, _SCREEN_STATE_FIELD))
                    ),
                    {"icon": "mdi:television-shimmer"},
                )
            )
            entities.append(
                _binary(
                    "screen_switch",
                    "屏幕点亮",
                    lambda device: _flag(
                        device, _SCREEN_STATE_SID, _SCREEN_SWITCH_FIELD
                    ),
                    "running",
                )
            )

        if context.has_service(_SPEAKER_SID):
            entities.append(
                _sensor(
                    "volume",
                    "音量",
                    lambda device: _number(
                        device.value(_SPEAKER_SID, _SPEAKER_VOLUME_FIELD)
                    ),
                    {"unit": "%", "state_class": "measurement"},
                )
            )
            entities.append(
                _binary(
                    "mute",
                    "静音",
                    lambda device: _bool(
                        device.value(_SPEAKER_SID, _SPEAKER_MUTE_FIELD)
                    ),
                    "sound",
                )
            )
            entities.append(
                _sensor(
                    "sound_mode",
                    "音效模式",
                    lambda device: _text(
                        device.value(_SPEAKER_SID, _SPEAKER_EQUALIZER_FIELD)
                    ),
                    {"icon": "mdi:equalizer"},
                )
            )

        if context.has_service(_SCREEN_SID):
            entities.append(
                _sensor(
                    "screen_brightness",
                    "屏幕亮度",
                    lambda device: _number(
                        device.value(_SCREEN_SID, _SCREEN_BRIGHTNESS_FIELD)
                    ),
                    {"unit": "%", "state_class": "measurement"},
                )
            )
            entities.append(
                _sensor(
                    "screen_mode",
                    "屏幕模式",
                    lambda device: _text(device.value(_SCREEN_SID, _SCREEN_MODE_FIELD)),
                    {"icon": "mdi:monitor"},
                )
            )

        if context.has_service(_PICTURE_MODE_SID):
            entities.append(
                _sensor(
                    "picture_mode",
                    "图像模式",
                    lambda device: _text(
                        device.value(_PICTURE_MODE_SID, _PICTURE_MODE_FIELD)
                    ),
                    {"icon": "mdi:image-filter-hdr"},
                )
            )

        if context.has_service(_VOICE_MODE_SID):
            entities.append(
                _sensor(
                    "voice_mode",
                    "语音模式",
                    lambda device: _text(
                        device.value(_VOICE_MODE_SID, _VOICE_MODE_FIELD)
                    ),
                    {"icon": "mdi:microphone-message"},
                )
            )

        if context.has_service(_INPUT_SOURCE_SID):
            entities.append(
                _sensor(
                    "input_source",
                    "信号源",
                    lambda device: _text(
                        device.value(_INPUT_SOURCE_SID, _INPUT_SOURCE_FIELD)
                    )
                    or _text(device.value(_INPUT_SOURCE_SID, _INPUT_SOURCE_NAME_FIELD)),
                    {"icon": "mdi:video-input-hdmi"},
                )
            )

        if context.has_service(_SYSTEM_MODE_SID):
            entities.append(
                _sensor(
                    "system_mode",
                    "系统模式",
                    lambda device: _text(
                        device.value(_SYSTEM_MODE_SID, _SYSTEM_MODE_FIELD)
                    ),
                    {"icon": "mdi:television-classic"},
                )
            )

        if context.has_service(_SCREEN_SAVER_SID):
            entities.append(
                _binary(
                    "screen_saver",
                    "屏保",
                    lambda device: (
                        None
                        if _number(
                            device.value(_SCREEN_SAVER_SID, _SCREEN_SAVER_FIELD)
                        )
                        is None
                        else _number(
                            device.value(_SCREEN_SAVER_SID, _SCREEN_SAVER_FIELD)
                        )
                        == _SCREEN_SAVER_ON
                    ),
                )
            )

        if context.has_service(_REMOTE_CONTROL_SID):
            entities.append(
                _sensor(
                    "ip",
                    "IP 地址",
                    lambda device: _text(
                        device.value(_REMOTE_CONTROL_SID, _REMOTE_CONTROL_IP_FIELD)
                    ),
                    {"icon": "mdi:ip-network"},
                )
            )
            entities.append(
                _binary(
                    "remote_control",
                    "遥控开关",
                    lambda device: _flag(
                        device,
                        _REMOTE_CONTROL_SID,
                        _REMOTE_CONTROL_SWITCH_FIELD,
                    ),
                )
            )

        if context.has_service(_NET_INFO_SID):
            entities.append(
                _sensor(
                    "wifi_ssid",
                    "Wi-Fi 名称",
                    lambda device: _text(
                        device.value(_NET_INFO_SID, _NET_INFO_SSID_FIELD)
                    ),
                    {"icon": "mdi:wifi"},
                )
            )

        return tuple(entities)


ADAPTER = ProductV0ENAdapter()
