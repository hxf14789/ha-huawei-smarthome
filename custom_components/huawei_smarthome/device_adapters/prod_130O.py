"""User-contributed protocol for Huawei product 130O (A.O.史密斯燃气热水器 JSQ).

设备类型: 热水器
本适配器暴露:
   1. water_heater 热水器(switch.on / temperature.target / mode.mode)
   2. binary_sensor 燃烧状态(burningStatus.on)
   3. binary_sensor 循环状态(loopStatus.on)
   4. binary_sensor 燃气安全状态(gasSafeStatus.status)
   5. binary_sensor 整机安全状态(machineSafeStatus.status)
   6. select 零冷水模式(noColdWaterMode.mode 1=夏季,2=冬季)
   7. switch 零冷水开关(noColdWater.on)
   8. switch 增压模式(boost.on)
   9. sensor 进水温度(temperature.inlet)

   13. binary_sensor 故障(faultCode.status)
   14. sensor 故障码(faultCode.code 0~15)

   ##以下服务未出现在profile中,但在设备上有显示,可能是profile不完整
   15. sensor 当前水流量 升/分钟(useInformation.waterFlow)
   16. sensor 生产热水总量 吨(useInformation.hotWater)
   17. sensor 累计工作时长 小时(useInformation.burningTime)
   18. sensor 累计燃气消耗 立方米(useInformation.naturalGas)


以下服务暂不适配:
   1. reserveTimer 预约零冷水(reserveTimer.timer/reserveTimer.week/reserveTimer.enable)
    过于复杂，暂不适配
   2. update OTA升级(update.action/update.version/update.introduction/update.progress/update.bootTime)
    没有测试
   3. netInfo 网络信息(netInfo.intensity/netInfo.RSSI/netInfo.SSID/netInfo.IP)
    实测没有信息

"""

from __future__ import annotations

from collections.abc import Mapping, Callable
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_COLD_WATER_MODE_OPTIONS = (
    "夏季", "冬季",
)
_COLD_WATER_MODE_VALUES = {
    "夏季": 1, "冬季": 2,
}

_MODE_OPTIONS = (
    "无模式", "厨房模式", "夏季淋浴", "冬季泡澡",
)
_MODE_VALUES = {
    "无模式": 0, "厨房模式": 1, "夏季淋浴": 2, "冬季泡澡": 3,
}

_ERROR_VALUES = {
    0: "0:运行正常，无错误", 
    1: "1:意外熄火", 
    2: "2:烟道堵塞",
    3: "3:出水温度过高",
    4: "4:残火故障",
    5: "5:CO报警",
    6: "6:进水温度异常",
    7: "7:出水温度传感器故障",
    8: "8:进水温度传感器故障",
    9: "9:风机转速异常",
    10: "10:比例阀电流故障",
    11: "11:点火失败",
    12: "12:循环水泵空转",
    13: "13:循环水泵堵转",
    14: "14:低温提示",
    15: "15:燃烧时间达到45分钟",
}

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
        if value.casefold() in {"1", "true", "on"}:
            return True
        if value.casefold() in {"0", "false", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None

def _switchEntitySpec(name: str, key: str, service: str, characteristic: str, metadata: Mapping[str, Any] = None) -> EntitySpec:
    return EntitySpec(
        platform="switch",
        key=key,
        name=name,
        state=lambda device: {
            "is_on": _bool(device.value(service, characteristic)) is True
        },
        actions={
            "turn_on": lambda d, _data: d.async_send_service(service, {characteristic: 1}),
            "turn_off": lambda d, _data: d.async_send_service(service, {characteristic: 0}),
        },
        metadata=metadata,
    )

def _binarySensorEntitySpec(name: str, key: str, service: str, characteristic: str, metadata: Mapping[str, Any] = None) -> EntitySpec:
    return EntitySpec(
        platform="binary_sensor",
        key=key,
        name=name,
        state=lambda device: {
            "is_on": _bool(device.value(service, characteristic)) is True
        },
        metadata=metadata,
    )

def _numberSensorEntitySpec(name: str, key: str, service: str, characteristic: str, metadata: Mapping[str, Any] = None, availability: Callable[["DeviceContext"], bool] = None, scale: float = 1.0) -> EntitySpec:
    return EntitySpec(
        platform="sensor",
        key=key,
        name=name,
        state=lambda device: {
            "native_value": _number(device.value(service, characteristic)) * scale if device.value(service, characteristic) is not None else None
        },
        metadata=metadata,
        availability=availability,
    )

def _sensorEntitySpec(name: str, key: str, service: str, characteristic: str, metadata: Mapping[str, Any] = None, value_map: Mapping[int | float | None, Any] = None, availability: Callable[["DeviceContext"], bool] = None) -> EntitySpec:
    return EntitySpec(
        platform="sensor",
        key=key,
        name=name,
        state=lambda device: {
            "native_value": value_map.get(_number(device.value(service, characteristic))) if value_map else device.value(service, characteristic)
        },
        metadata=metadata,
        availability=availability,
    )


def _water_heater_spec(context: DeviceContext) -> EntitySpec:
    """Expose the main water-heater controls as one HA water_heater entity."""

    actions = {
        "turn_on": lambda device, _data: device.async_send_service(
            "switch", {"on": 1}
        ),
        "turn_off": lambda device, _data: device.async_send_service(
            "switch", {"on": 0}
        ),
    }
    if context.has_service("temperature"):
        actions["set_temperature"] = lambda device, data: device.async_send_service(
            "temperature", {"target": _number(data.get("temperature"))}
        )
    if context.has_service("mode"):

        async def set_operation_mode(
            device: DeviceContext,
            data: Mapping[str, Any],
        ) -> None:
            option = str(data.get("operation_mode"))
            if option not in _MODE_VALUES:
                raise ValueError(f"unknown mode: {option}")
            value = _MODE_VALUES[option]
            await device.async_send_service(
                "mode",
                {"on": 0 if value == 0 else 1, "mode": value},
            )

        actions["set_operation_mode"] = set_operation_mode

    def state(device: DeviceContext) -> Mapping[str, Any]:
        mode = _number(device.value("mode", "mode"))
        operation = next(
            (
                label
                for label, value in _MODE_VALUES.items()
                if mode == value
            ),
            None,
        )
        if _bool(device.value("mode", "on")) is False:
            operation = "无模式"
        return {
            "target_temperature": _number(
                device.value("temperature", "target")
            ),
            "current_operation": operation,
        }

    return EntitySpec(
        platform="water_heater",
        key="water_heater",
        name="热水器",
        state=state,
        metadata={
            "min_temp": 35,
            "max_temp": 70,
            "target_temp_step": 1,
            "operation_modes": _MODE_OPTIONS,
        },
        actions=actions,
    )

class Product130OAdapter:
    """Keep all 130O entity and command choices in this file."""

    prod_id = "130O"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("switch"):
            return ()

        entities: list[EntitySpec] = [_water_heater_spec(context)]

        if context.has_service("burningStatus"):
            entities.append(
                _binarySensorEntitySpec(
                    "燃烧状态", "burning_status", "burningStatus", "on",
                    metadata={"device_class": "running"}
                )
            )

        if context.has_service("loopStatus"):
            entities.append(
                _binarySensorEntitySpec(
                    "循环状态", "loop_status", "loopStatus", "on",
                    metadata={"device_class": "running"}
                )
            )

        if context.has_service("gasSafeStatus"):
            entities.append(
                _binarySensorEntitySpec(
                    "燃气安全状态", "gas_safe_status", "gasSafeStatus", "status",
                    metadata={"device_class": "problem"}
                )
            )

        if context.has_service("machineSafeStatus"):
            entities.append(
                _binarySensorEntitySpec(
                    "整机安全状态", "machine_safe_status", "machineSafeStatus", "status",
                    metadata={"device_class": "problem"}
                )
            )

        if context.has_service("noColdWaterMode"):
            async def set_cold_water_mode(
                device: DeviceContext, data: Mapping[str, Any]
            ) -> None:
                option = str(data.get("option"))
                if option not in _COLD_WATER_MODE_VALUES:
                    raise ValueError(f"unknown cold water mode: {option}")
                await device.async_send_service(
                    "noColdWaterMode", {"mode": _COLD_WATER_MODE_VALUES[option]}
                )

            entities.append(
                EntitySpec(
                    platform="select",
                    key="cold_water_mode",
                    name="零冷水模式",
                    state=lambda device: {
                        "current_option": next(
                            (
                                label
                                for label, raw in _COLD_WATER_MODE_VALUES.items()
                                if _number(device.value("noColdWaterMode", "mode")) == raw
                            ),
                            None,
                        )
                    },
                    metadata={"options": _COLD_WATER_MODE_OPTIONS},
                    actions={"select_option": set_cold_water_mode},
                )
            )

        if context.has_service("noColdWater"):
            entities.append(
                _switchEntitySpec(
                    "零冷水开关", "cold_water_switch", "noColdWater", "on"
                )
            )

        if context.has_service("boost"):
            entities.append(
                _switchEntitySpec(
                    "增压模式", "boost_switch", "boost", "on"
                )
            )

        if context.has_service("temperature"):
            entities.append(
                _numberSensorEntitySpec(
                    "进水温度", "inlet_temperature", "temperature", "inlet",
                    metadata={"unit": "°C", "device_class": "temperature", "state_class": "measurement"}
                )
            )

        if context.has_service("useInformation"):
            entities.append(
                _numberSensorEntitySpec(
                    "当前水流量", "current_water_flow", "useInformation", "waterFlow",
                    metadata={"unit": "L/min", "device_class": "volume_flow_rate", "state_class": "measurement"},
                    availability=lambda device: device.value("useInformation", "waterFlow") is not None
                )
            )
            entities.append(
                _numberSensorEntitySpec(
                    "生产热水总量", "total_hot_water", "useInformation", "hotWater",
                    metadata={"unit": "m³", "device_class": "water", "state_class": "total_increasing"},
                    availability=lambda device: device.value("useInformation", "hotWater") is not None,
                    scale=0.1
                )
            )
            entities.append(
                _numberSensorEntitySpec(
                    "累计工作时长", "total_burning_time", "useInformation", "burningTime",
                    metadata={"unit": "h", "device_class": "duration", "state_class": "total_increasing"},
                    availability=lambda device: device.value("useInformation", "burningTime") is not None
                )
            )
            entities.append(
                _numberSensorEntitySpec(
                    "累计燃气消耗", "total_natural_gas", "useInformation", "naturalGas",
                    metadata={"unit": "m³", "device_class": "gas", "state_class": "total_increasing"},
                    availability=lambda device: device.value("useInformation", "naturalGas") is not None,
                    scale=0.1
                )
            )

        if context.has_service("faultCode"):
            entities.append(
                _binarySensorEntitySpec(
                    "故障状态", "fault_code_status", "faultCode", "status",
                    metadata={"entity_category": "diagnostic", "device_class": "problem"}
                )
            )
            entities.append(
                _sensorEntitySpec(
                    "故障码", "fault_code", "faultCode", "code",
                    value_map=_ERROR_VALUES,
                    metadata={"entity_category": "diagnostic"}
                )
            )

        return tuple(entities)


ADAPTER = Product130OAdapter()
