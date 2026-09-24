"""User-contributed protocol for Huawei product W001 (荣耀智慧屏系列).

Profile: https://smarthome-drcn.dbankcdn.com/device/guide/W001/W001.json
deviceModel ``LOK``, deviceTypeName 智慧屏 (Intelligent Vision),
manufacturer 荣耀 (HONOR).

公开 Profile 只声明 6 个服务 (messageboard / remotecontrol / autoconfig /
devicestate / generalcommand / logreport), 与 V0E9/V0FB/V004 等同代智慧屏
家族的薄 Profile 完全一致。所有特性权限均为 RG/RPG/RGP (无 W), 云端只读,
无法发送控制命令; Profile 不暴露电视实际操控 (电源/音量/输入源等)。

devicestate    screenState      bool RGP  0 熄屏 / 1 在线 / 2 离线
remotecontrol  switchState      bool RG   0 关闭 / 1 开启 (智慧屏操控开关)
remotecontrol  access_token/ip_addr/mask/gateway_mac/valid_time/
                 controller_mac  诊断与网络信息, 只读
messageboard   id/sender/message/reply  留言板, RPG, CRUD 无标准 HA 映射
generalcommand setCommand/getCommand    通用字符串通道, 语义不明确
logreport      Beta 日志上传, 诊断信息
autoconfig     hms_login_info  HMS 登录校验信息, 诊断信息

Exposed:
- sensor        屏幕状态: 基于 devicestate.screenState (熄屏/在线/离线).
- binary_sensor 遥控开关: 基于 remotecontrol.switchState (开启/关闭).

Not exposed (宁可不出):
- messageboard: 留言板为 CRUD 操作 (id/sender/message/reply),
  无标准 HA 实体映射.
- generalcommand: setCommand/getCommand 为通用字符串通道,
  无明确语义, 猜测风险高.
- logreport / autoconfig: 诊断与配置信息, 非设备运行状态.
- remotecontrol 网络字段 (ip_addr/mask/gateway_mac/controller_mac/
  access_token) 与 valid_time: 网络与 Token 诊断信息,
  非用户关心的设备状态.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext


# ---- 枚举映射 ------------------------------------------------------------

_SCREEN_STATE_LABELS: dict[int, str] = {
    0: "熄屏",
    1: "在线",
    2: "离线",
}


# ---- 工具函数 ------------------------------------------------------------

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


# ---- 适配器 --------------------------------------------------------------

class ProductW001Adapter:
    """W001 荣耀智慧屏系列 (HONOR Vision) 适配器。"""

    prod_id = "W001"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None:
            return ()

        entities: list[EntitySpec] = []

        # ---- sensor: 屏幕状态 --------------------------------------------
        if context.has_service("devicestate"):

            def screen_state(device: DeviceContext) -> Mapping[str, Any]:
                val = _as_int(device.value("devicestate", "screenState"))
                return {
                    "native_value": _SCREEN_STATE_LABELS.get(val, "未知"),
                }

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="screen_state",
                    name="屏幕状态",
                    state=screen_state,
                    metadata={},
                )
            )

        # ---- binary_sensor: 遥控开关 -------------------------------------
        if context.has_service("remotecontrol"):

            def remote_switch(device: DeviceContext) -> Mapping[str, Any]:
                val = _as_int(device.value("remotecontrol", "switchState"))
                return {"is_on": val == 1}

            entities.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="remote_switch",
                    name="遥控开关",
                    state=remote_switch,
                    metadata={},
                )
            )

        return tuple(entities)


ADAPTER = ProductW001Adapter()
