"""User-contributed protocol for Huawei product 115J (遥控大师空调伴侣).

产品: 遥控大师空调伴侣
厂商: 深圳遥看科技有限公司
型号: YKK-KT16A / deviceTypeId 007 (万能遥控器)

═══════════════════════════════════════════════════════════════════
数据来源与验证状态
═══════════════════════════════════════════════════════════════════

字段名与取值范围取自该产品的物模型 (profile) 声明；``airKey`` 写帧的
形状（``id`` 恒为 0、关机只发 ``power``、除湿强制低风等）与厂商 H5
遥控页的下发逻辑一致。

状态读取（power/mode/wind/temp/up 投影）与上面这些写帧已在真实设备上
核对，空调开关、模式、温度、风速均可正常控制。

**未经真实设备逐项验证的部分**：左右扫风（``left``）与屏显
（``light``）—— 这两个字段不在物模型里，仅在设备实际上报后才启用，
其取值语义未逐项实测。如果你的 115J 不上报这两个字段，适配器不会为
它们建实体或档位。

═══════════════════════════════════════════════════════════════════
设备特性
═══════════════════════════════════════════════════════════════════

伴侣串在空调插座与空调插头之间，自身物模型里**没有**可控制的继电器服务：
它靠内置红外码库遥控空调，并用 ``powerCon`` 统计流经插座的功率/电量，
用这份功率「自动判断空调开关机」。

核心服务（取自真机物模型）:

    airKey      空调遥控: power 0/1, mode 0自动 1除湿 2送风 3制热 4制冷,
                wind 0自动 1低 2中 3高, temp 16-30, up 扫风 0/1
    ledOnoff    指示灯: ledOnoff 0/1 (物模型 report=0, 设备不主动上报)
    switchPower 自动判断开关机: on 0/1 (固件运行期上报, 不在物模型里)
    powerCon    功率统计: power(W) / watt(kWh) / workTime(min)

═══════════════════════════════════════════════════════════════════
实体清单
═══════════════════════════════════════════════════════════════════

    air                      climate  空调 (模式/温度/风速/扫风/开关)
    indicator_led            switch   空调伴侣指示灯
    screen_light             switch   空调屏幕显示 (仅开机时可切)
    auto_detect              switch   自动判断空调开关机
    current_power            sensor   当前功率 (W)
    energy_consumption       sensor   间隔用电量 (kWh)
    work_time                sensor   间隔工作时长 (min)

三条 powerCon 曲线都是**区间值**（「每 5 分钟一次」的间隔量），不是累计值，
因此 state_class 用 measurement。

═══════════════════════════════════════════════════════════════════
控制帧
═══════════════════════════════════════════════════════════════════

``airKey`` 写帧形状与厂商 H5 一致:

    {id: 0, mode, wind, temp, up[, left][, light][, power]}

``id`` 恒为 0（物模型 descCh: 0 = APP/语音/云端下发的离散控制参数）。
关机只发 ``{id: 0, power: 0}``，不改其它字段。

取值优先级：本次动作要改的字段 → 设备当前上报值；**拿不到就不放该字段**，
因为设备对缺省字段保持原值，补 0 反而会把风速/扫风打到自动档。

═══════════════════════════════════════════════════════════════════
可选能力（以实测上报为准）
═══════════════════════════════════════════════════════════════════

``left``（左右扫风）与 ``light``（屏显）**不在物模型里**，只有设备实际
上报过才建对应档位/实体，避免产出点了没反应的僵尸实体。
未上报 ``left`` 时扫风退化为「关/开」两档。

和客厅 ``107J``（遥看小苹果 YKK-1011）不通用：指示灯字段 115J 是
``ledOnoff``（107J 是 ``on``），开关值 0/1（107J 是 1/2），且 115J 多了
``powerCon``。两个适配器互不依赖，可同时安装。

═══════════════════════════════════════════════════════════════════
未映射的服务
═══════════════════════════════════════════════════════════════════

``deviceList`` / ``cmdList`` / ``loadRes`` / ``refKey`` / ``hotKey`` /
``sumKey`` / ``matchKey`` / ``timer`` / ``sumTimer`` / ``delay`` /
``delayAirkey`` / ``update`` / ``netInfo`` —— 配网、码库下载、急速制冷/制热、
睡眠曲线、倒计时与 OTA 都留给厂商 App。场景类开关需要在 ``cmdList`` /
``refKey`` / ``timer`` 之间链式下三帧，未逐项实测之前不映射。

═══════════════════════════════════════════════════════════════════
已知限制
═══════════════════════════════════════════════════════════════════

1. 设备不上报室温，``current_temperature`` 恒为 None。
2. ``ledOnoff`` 物模型 report=0，设备不主动上报，写入后靠本地回填，
   HA 重启后指示灯状态可能短暂未知，直到下次操作。
3. 扫风/屏显的具体档位取决于设备实际上报了哪些字段。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_AIR_SID = "airKey"
_LED_SID = "ledOnoff"
_AUTO_SID = "switchPower"
_POWER_CON_SID = "powerCon"

_AIR_ID = 0
_AIR_POWER_ON = 1
_AIR_POWER_OFF = 0

_TEMP_MIN = 16
_TEMP_MAX = 30

# 物模型 airKey.mode: 0自动 1除湿 2送风 3制热 4制冷
_DEV_TO_HVAC = {0: "auto", 1: "dry", 2: "fan_only", 3: "heat", 4: "cool"}
_HVAC_TO_DEV = {value: key for key, value in _DEV_TO_HVAC.items()}

# 物模型 airKey.wind: 0自动 1低 2中 3高
_DEV_TO_FAN = {0: "auto", 1: "low", 2: "medium", 3: "high"}
_FAN_TO_DEV = {value: key for key, value in _DEV_TO_FAN.items()}

# 只有 up 时有官方定义 0全关 / 1全开
_SWING_BASIC = ("off", "on")
# 设备额外上报 left 时才给四档
_SWING_FULL = ("off", "vertical", "horizontal", "both")
_SWING_CODES = {
    "off": (0, 0),
    "on": (1, 0),
    "vertical": (1, 0),
    "horizontal": (0, 1),
    "both": (1, 1),
}

# 除湿必须低风、送风不能自动风
_MODE_FORCED_FAN = {"dry": 1}


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


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
    number = _as_int(value)
    return None if number is None else number != 0


def _has_field(context: DeviceContext, sid: str, field: str) -> bool:
    """字段是否可用 = 当前上报值里有，或物模型里声明了。"""

    if field in context.service_state(sid):
        return True
    profile = context.profile
    if not isinstance(profile, Mapping):
        return False
    for service in profile.get("services", ()) or ():
        if not isinstance(service, Mapping) or service.get("serviceId") != sid:
            continue
        for characteristic in service.get("characteristics", ()) or ():
            if (
                isinstance(characteristic, Mapping)
                and characteristic.get("characteristicName") == field
            ):
                return True
    return False


def _supports_left(context: DeviceContext) -> bool:
    return _has_field(context, _AIR_SID, "left")


def _supports_light(context: DeviceContext) -> bool:
    return _has_field(context, _AIR_SID, "light")


def _swing_modes(context: DeviceContext) -> tuple[str, ...]:
    return _SWING_FULL if _supports_left(context) else _SWING_BASIC


def _air_frame(
    context: DeviceContext,
    state: Mapping[str, Any],
    **overrides: Any,
) -> dict[str, Any]:
    """按厂商 H5 口径拼一帧 airKey 控制参数。"""

    frame: dict[str, Any] = {"id": _AIR_ID}
    for field in ("mode", "wind", "temp", "up"):
        value = _as_int(overrides.get(field, state.get(field)))
        if value is not None:
            frame[field] = value
    if _supports_left(context):
        left = _as_int(overrides.get("left", state.get("left")))
        if left is not None:
            frame["left"] = left
    if _supports_light(context):
        light = _as_int(overrides.get("light", state.get("light")))
        if light is not None:
            frame["light"] = light
    power = _as_int(overrides.get("power"))
    if power is not None:
        frame["power"] = power
    return frame


def _wake_power(state: Mapping[str, Any]) -> int | None:
    """已关机时顺带带上 power=1，否则参数写下去也不生效。"""

    if _as_int(state.get("power")) == _AIR_POWER_ON:
        return None
    return _AIR_POWER_ON


async def _turn_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    state = context.service_state(_AIR_SID)
    await context.async_send_service(
        _AIR_SID,
        _air_frame(context, state, power=_AIR_POWER_ON),
    )


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(
        _AIR_SID,
        {"id": _AIR_ID, "power": _AIR_POWER_OFF},
    )


async def _set_hvac_mode(context: DeviceContext, data: Mapping[str, Any]) -> None:
    hvac_mode = str(data.get("hvac_mode"))
    if hvac_mode == "off":
        await _turn_off(context, data)
        return
    dev_mode = _HVAC_TO_DEV.get(hvac_mode)
    if dev_mode is None:
        raise ValueError(f"unsupported hvac_mode: {hvac_mode}")

    state = context.service_state(_AIR_SID)
    overrides: dict[str, Any] = {"mode": dev_mode}
    if hvac_mode in _MODE_FORCED_FAN:
        overrides["wind"] = _MODE_FORCED_FAN[hvac_mode]
    elif hvac_mode == "fan_only" and not _as_int(state.get("wind")):
        overrides["wind"] = _FAN_TO_DEV["low"]
    await context.async_send_service(
        _AIR_SID,
        _air_frame(context, state, power=_wake_power(state), **overrides),
    )


async def _set_temperature(context: DeviceContext, data: Mapping[str, Any]) -> None:
    temperature = _as_float(data.get("temperature"))
    if temperature is None:
        return
    target = max(_TEMP_MIN, min(_TEMP_MAX, int(round(temperature))))
    state = context.service_state(_AIR_SID)
    await context.async_send_service(
        _AIR_SID,
        _air_frame(context, state, power=_wake_power(state), temp=target),
    )


async def _set_fan_mode(context: DeviceContext, data: Mapping[str, Any]) -> None:
    fan_mode = str(data.get("fan_mode"))
    wind = _FAN_TO_DEV.get(fan_mode)
    if wind is None:
        raise ValueError(f"unsupported fan_mode: {fan_mode}")
    state = context.service_state(_AIR_SID)
    await context.async_send_service(
        _AIR_SID,
        _air_frame(context, state, power=_wake_power(state), wind=wind),
    )


async def _set_swing_mode(context: DeviceContext, data: Mapping[str, Any]) -> None:
    swing_mode = str(data.get("swing_mode"))
    if swing_mode not in _swing_modes(context):
        raise ValueError(f"unsupported swing_mode: {swing_mode}")
    up, left = _SWING_CODES[swing_mode]
    state = context.service_state(_AIR_SID)
    await context.async_send_service(
        _AIR_SID,
        _air_frame(context, state, power=_wake_power(state), up=up, left=left),
    )


def _panel_light_actions():
    async def _turn_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
        state = context.service_state(_AIR_SID)
        if _as_int(state.get("power")) != _AIR_POWER_ON:
            raise ValueError("空调关机时无法切换屏幕显示，请先开机")
        await context.async_send_service(
            _AIR_SID,
            _air_frame(context, state, light=1),
        )

    async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
        state = context.service_state(_AIR_SID)
        if _as_int(state.get("power")) != _AIR_POWER_ON:
            raise ValueError("空调关机时无法切换屏幕显示，请先开机")
        await context.async_send_service(
            _AIR_SID,
            _air_frame(context, state, light=0),
        )

    return _turn_on, _turn_off


def _led_actions():
    async def _turn_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
        await context.async_send_service(_LED_SID, {"ledOnoff": 1})

    async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
        await context.async_send_service(_LED_SID, {"ledOnoff": 0})

    return _turn_on, _turn_off


def _auto_actions():
    async def _turn_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
        await context.async_send_service(_AUTO_SID, {"on": 1})

    async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
        await context.async_send_service(_AUTO_SID, {"on": 0})

    return _turn_on, _turn_off


_SENSOR_SPECS: tuple[tuple[str, str, str, Mapping[str, Any]], ...] = (
    (
        "current_power",
        "当前功率",
        "power",
        {"unit": "W", "device_class": "power", "state_class": "measurement"},
    ),
    (
        "energy_consumption",
        "间隔用电量",
        "watt",
        # 该值是「本时间间隔内的度数」而非累计值，
        # HA 不允许 device_class=energy 配 state_class=measurement，故不设 device_class。
        {"unit": "kWh", "state_class": "measurement"},
    ),
    (
        "work_time",
        "间隔工作时长",
        "workTime",
        {"unit": "min", "device_class": "duration", "state_class": "measurement"},
    ),
)


class Product115JAdapter:
    """115J 遥控大师空调伴侣适配器。"""

    prod_id = "115J"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service(_AIR_SID):
            return ()

        swing_modes = _swing_modes(context)

        def climate_state(device: DeviceContext) -> Mapping[str, Any]:
            state = device.service_state(_AIR_SID)
            power = _as_int(state.get("power"))
            mode = _as_int(state.get("mode"))
            if power == _AIR_POWER_OFF:
                hvac_mode = "off"
            elif power is None:
                hvac_mode = None
            else:
                hvac_mode = _DEV_TO_HVAC.get(mode)
            swing_up = _as_int(state.get("up"))
            swing_left = _as_int(state.get("left"))
            if swing_modes == _SWING_BASIC:
                swing_mode = (
                    None if swing_up is None else ("on" if swing_up else "off")
                )
            elif swing_up is None and swing_left is None:
                swing_mode = None
            elif swing_up and swing_left:
                swing_mode = "both"
            elif swing_up:
                swing_mode = "vertical"
            elif swing_left:
                swing_mode = "horizontal"
            else:
                swing_mode = "off"
            return {
                "hvac_mode": hvac_mode,
                "target_temperature": _as_float(state.get("temp")),
                "fan_mode": _DEV_TO_FAN.get(_as_int(state.get("wind"))),
                "swing_mode": swing_mode,
            }

        entities = [
            EntitySpec(
                platform="climate",
                key="air",
                name=None,
                state=climate_state,
                metadata={
                    "hvac_modes": list(_DEV_TO_HVAC.values()) + ["off"],
                    "fan_modes": list(_DEV_TO_FAN.values()),
                    "swing_modes": list(swing_modes),
                    "min_temp": _TEMP_MIN,
                    "max_temp": _TEMP_MAX,
                },
                actions={
                    "turn_on": _turn_on,
                    "turn_off": _turn_off,
                    "set_hvac_mode": _set_hvac_mode,
                    "set_temperature": _set_temperature,
                    "set_fan_mode": _set_fan_mode,
                    "set_swing_mode": _set_swing_mode,
                },
            )
        ]

        if context.has_service(_LED_SID):
            led_on, led_off = _led_actions()
            entities.append(
                EntitySpec(
                    platform="switch",
                    key="indicator_led",
                    name="空调伴侣指示灯",
                    state=lambda device: {
                        "is_on": _as_bool(device.value(_LED_SID, "ledOnoff"))
                    },
                    actions={"turn_on": led_on, "turn_off": led_off},
                )
            )

        if _supports_light(context):
            light_on, light_off = _panel_light_actions()
            entities.append(
                EntitySpec(
                    platform="switch",
                    key="screen_light",
                    name="空调屏幕显示",
                    state=lambda device: {
                        "is_on": _as_bool(device.value(_AIR_SID, "light"))
                    },
                    actions={"turn_on": light_on, "turn_off": light_off},
                )
            )

        if context.has_service(_AUTO_SID):
            auto_on, auto_off = _auto_actions()
            entities.append(
                EntitySpec(
                    platform="switch",
                    key="auto_detect",
                    name="自动判断开关机",
                    state=lambda device: {
                        "is_on": _as_bool(device.value(_AUTO_SID, "on"))
                    },
                    actions={"turn_on": auto_on, "turn_off": auto_off},
                )
            )

        for key, name, field, metadata in _SENSOR_SPECS:
            if not _has_field(context, _POWER_CON_SID, field):
                continue
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key=key,
                    name=name,
                    state=(
                        lambda device, f=field: {
                            "native_value": _as_float(
                                device.value(_POWER_CON_SID, f)
                            )
                        }
                    ),
                    metadata=metadata,
                )
            )

        return tuple(entities)



ADAPTER = Product115JAdapter()
