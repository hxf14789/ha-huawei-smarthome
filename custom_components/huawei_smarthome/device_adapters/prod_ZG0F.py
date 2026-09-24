"""Independent ZG0F adapter with explicit product service mappings.

Field mappings and command validation are local to this product.
"""

import asyncio
import math

from .api import EntitySpec


def _field(ctx, sid, key):
    for service in (ctx.profile or {}).get("services", []):
        if service.get("serviceId") == sid:
            return next(
                (
                    f
                    for f in service.get("characteristics", [])
                    if f.get("characteristicName") == key
                ),
                None,
            )
    return None


def _number(value):
    try:
        if isinstance(value, bool):
            return None
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _boolean(value):
    if value in (0, "0", False):
        return False
    if value in (1, "1", True):
        return True
    return None


def _numeric(ctx, sid, key):
    value = _number(ctx.value(sid, key))
    schema = _field(ctx, sid, key)
    if value is None or not schema:
        return None
    low, high = (_number(schema.get("min")), _number(schema.get("max")))
    if low is not None and value < low or (high is not None and value > high):
        return None
    return value


def _writable(ctx, sid, key):
    schema = _field(ctx, sid, key)
    return bool(schema and "W" in schema.get("method", ""))


def _validate(ctx, sid, key, value):
    schema = _field(ctx, sid, key)
    if not _writable(ctx, sid, key):
        raise ValueError(f"Profile does not permit writing {sid}.{key}")
    kind = schema.get("characteristicType")
    if kind in ("int", "float", "double", "bool", "enum"):
        parsed = _number(value)
        if parsed is None:
            raise ValueError("A finite numeric command is required")
        if kind in ("int", "bool", "enum"):
            if not parsed.is_integer():
                raise ValueError("An integer command is required")
            value = int(parsed)
        else:
            value = parsed
        low, high = (_number(schema.get("min")), _number(schema.get("max")))
        if low is not None and value < low or (high is not None and value > high):
            raise ValueError("Command is outside the product Profile range")
        step = _number(schema.get("step"))
        if (
            step
            and low is not None
            and (
                not math.isclose(
                    (value - low) / step, round((value - low) / step), abs_tol=1e-06
                )
            )
        ):
            raise ValueError("Command does not match the product Profile step")
    if kind == "string" and (not isinstance(value, str)):
        raise ValueError("A string command is required")
    choices = schema.get("enumList", [])
    if choices and str(value) not in {str(e["enumVal"]) for e in choices}:
        raise ValueError("Command is not in the product Profile enum")
    return value


async def _send(ctx, sid, key, value):
    value = _validate(ctx, sid, key, value)
    await ctx.async_send_service(sid, {key: value})


def _sensor(
    ctx,
    sid,
    key,
    name,
    *,
    unit=None,
    device_class=None,
    binary=False,
    enum=False,
    scale=1,
):
    schema = _field(ctx, sid, key)
    if schema is None or "R" not in schema.get("method", ""):
        return None
    metadata = {}
    if unit:
        metadata["unit"] = unit
    if device_class:
        metadata["device_class"] = device_class

    def state(c):
        raw = c.value(sid, key)
        if binary:
            return {"is_on": _boolean(raw)}
        if enum:
            value = next(
                (
                    v.get("descCh") or str(raw)
                    for v in schema.get("enumList", [])
                    if str(v.get("enumVal")) == str(raw)
                ),
                None,
            )
        else:
            value = _numeric(c, sid, key)
            if value is not None:
                value = value / 10 if scale == 0.1 else value * scale
        return {"native_value": value}

    return EntitySpec(
        "binary_sensor" if binary else "sensor",
        f"{sid}_{key}",
        name,
        state,
        metadata=metadata,
    )


def _control_switch(ctx, sid, key, name, inverted=False):
    if not _writable(ctx, sid, key):
        return None

    async def on(c, d):
        await _send(c, sid, key, 0 if inverted else 1)

    async def off(c, d):
        await _send(c, sid, key, 1 if inverted else 0)

    return EntitySpec(
        "switch",
        f"{sid}_{key}_control",
        name,
        lambda c: {
            "is_on": not _boolean(c.value(sid, key))
            if inverted and _boolean(c.value(sid, key)) is not None
            else _boolean(c.value(sid, key))
        },
        actions={"turn_on": on, "turn_off": off},
    )


def _control_number(ctx, sid, key, name, unit=None):
    schema = _field(ctx, sid, key)
    if not _writable(ctx, sid, key) or "min" not in schema or "max" not in schema:
        return None

    async def set_value(c, d):
        await _send(c, sid, key, d["value"])

    return EntitySpec(
        "number",
        f"{sid}_{key}_control",
        name,
        lambda c: {"native_value": _numeric(c, sid, key)},
        {
            "min": float(schema["min"]),
            "max": float(schema["max"]),
            "step": float(schema.get("step") or 1),
            "unit": unit,
        },
        {"set_value": set_value},
    )


def _control_select(ctx, sid, key, name):
    if not _writable(ctx, sid, key):
        return None
    options = {
        str(v["enumVal"]): v.get("descCh", str(v["enumVal"]))
        for v in _field(ctx, sid, key).get("enumList", [])
    }
    if not options:
        return None

    async def select(c, d):
        value = next((k for k, v in options.items() if v == d["option"]), None)
        if value is None:
            raise ValueError("Unknown option")
        await _send(c, sid, key, int(value))

    return EntitySpec(
        "select",
        f"{sid}_{key}_control",
        name,
        lambda c: {"current_option": options.get(str(c.value(sid, key)))},
        {"options": tuple(options.values())},
        {"select_option": select},
    )


def _reading_entities(ctx, rows):
    result = []
    for row in rows:
        sid, key, name, unit, device_class, *kind = row
        scale = 1
        spec = _sensor(
            ctx,
            sid,
            key,
            name,
            unit=unit,
            device_class=device_class,
            binary=kind == ["binary"],
            enum=kind == ["enum"],
            scale=scale,
        )
        if spec is not None:
            result.append(spec)
    return result


def _numbers(value):
    if not isinstance(value, str) or len(value) > 4096:
        return []
    try:
        result = [float(x.strip()) for x in value.split(",")]
    except (TypeError, ValueError):
        return []
    return (
        result if all((math.isfinite(x) and abs(x) <= 100000 for x in result)) else []
    )


def _polygon(value, counted=False):
    n = _numbers(value)
    if counted:
        if (
            not n
            or n[0] != int(n[0])
            or (not 3 <= n[0] <= 64)
            or (len(n) < 1 + 2 * int(n[0]))
        ):
            return []
        n = n[1 : 1 + 2 * int(n[0])]
    if len(n) < 6 or len(n) % 2:
        return []
    points = [{"x": n[i], "y": n[i + 1]} for i in range(0, len(n), 2)]
    if len({(p["x"], p["y"]) for p in points}) < 3:
        return []
    return points


def _map_state(c):
    regions = []
    outer = []
    for i in range(1, 4):
        outer.extend(_polygon(c.value("basicFence", f"locationList{i}"), True))
    if outer:
        regions.append(
            {
                "name": c.value("basicFence", "fenceName") or "总区域",
                "kind": "boundary",
                "points": outer,
            }
        )
    for i in range(1, 9):
        sid = f"userFence{i}"
        if c.value(sid, "enableFence") not in (1, "1", True):
            continue
        pts = _polygon(c.value(sid, "locationList"))
        if pts:
            regions.append(
                {
                    "name": str(c.value(sid, "fenceName") or f"区域{i}"),
                    "kind": "region",
                    "points": pts,
                    "occupied": c.value(f"userFenceEvent{i}", "existent")
                    in (1, "1", True),
                }
            )
    walls = []
    for i in range(1, 26):
        v = _numbers(c.value("basicFence", f"virtualWallList{i}"))
        if len(v) >= 5 and v[0] in (1, 2, 3, 4, 5, 6):
            walls.append(
                {
                    "type": int(v[0]),
                    "points": [{"x": v[1], "y": v[2]}, {"x": v[3], "y": v[4]}],
                }
            )
    raw = c.value("basicFenceEvent", "positionList")
    if raw is None:
        raw = c.value("basicFenceEvent", "postionList")
    v = _numbers(raw)
    points = []
    if len(v) % 3 == 0:
        points = [
            {"x": v[i], "y": v[i + 1], "z": v[i + 2]}
            for i in range(0, min(len(v), 96), 3)
        ]
    tag = c.value("basicFenceEvent", "positionTag")
    if tag is None:
        tag = c.value("basicFenceEvent", "postionTag")
    occupied = c.value("basicFenceEvent", "existent")
    occupied = (
        True
        if occupied in (1, "1", True)
        else False
        if occupied in (0, "0", False)
        else None
    )
    install = _numbers(c.value("devLocation", "installCoord"))
    return {
        "native_value": "有人"
        if occupied is True
        else "无人"
        if occupied is False
        else "待上报",
        "extra_state_attributes": {
            "radar_map": True,
            "regions": regions,
            "walls": walls,
            "positions": points,
            "position_valid": tag not in (None, 0, "0", False) and bool(points),
            "occupied": occupied,
            "report_mode": c.value("basicFence", "singleReport"),
            "sensor_position": {"x": install[0], "y": install[1]}
            if len(install) >= 2
            else None,
            "coordinate_system": "vendor_xy",
            "freshness_seconds": 15,
        },
    }


def _radar_map_entities(ctx):
    return (
        EntitySpec(
            "sensor",
            "radar_area_map",
            "区域与人员位置",
            _map_state,
            {
                "radar_map": True,
                "attribute_update_timestamps": {
                    "position_received_at": {
                        "service": "basicFenceEvent",
                        "fields": ("positionList", "postionList"),
                    }
                },
            },
        ),
    )


def _flags(ctx):
    value = ctx.value("basicFence", "advancedPara")
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if str(result) == str(value) and 0 <= result <= 4294967295 else None


def _radar_option_entities(ctx):
    if (ctx.prod_id or "").upper() != "ZG0F" or _flags(ctx) is None:
        return ()

    def make(bit, name):

        def state(c):
            raw = _flags(c)
            return {"is_on": None if raw is None else bool(raw & 1 << bit)}

        async def set_flag(c, enabled):
            if not hasattr(c, "_radar_options_lock"):
                c._radar_options_lock = asyncio.Lock()
            async with c._radar_options_lock:
                raw = _flags(c)
                if raw is None:
                    raise ValueError("Advanced settings have not been reported")
                pending = getattr(c, "_radar_options_pending", None)
                if pending is not None:
                    old, mask, wanted = pending
                    if raw & mask != wanted:
                        raise ValueError(
                            "Waiting for previous advanced setting to be reported"
                        )
                    c._radar_options_pending = None
                if bit == 5 and (not raw & 1 << 25):
                    raise ValueError("Pet filtering is not supported")
                mask = 1 << bit
                value = raw | mask if enabled else raw & ~mask
                if value == raw:
                    return
                await c.async_send_service("basicFence", {"advancedPara": value})
                c._radar_options_pending = (raw, mask, value & mask)

        async def on(c, data):
            await set_flag(c, True)

        async def off(c, data):
            await set_flag(c, False)

        return EntitySpec(
            "switch",
            f"advanced_para_bit_{bit}",
            name,
            state,
            actions={"turn_on": on, "turn_off": off},
        )

    result = [make(0, "抗干扰增强")]
    if _flags(ctx) & 1 << 25:
        result.append(make(5, "防宠检测"))
    return tuple(result)


def _delay_values(ctx):
    raw = ctx.value("basicFence", "delayTimeList")
    if not isinstance(raw, str):
        return None
    values = raw.split(",")
    if len(values) != 16 or any((v not in ("0", "1", "2") for v in values)):
        return None
    return values


def _radar_tuning_entities(ctx):
    if (ctx.prod_id or "").upper() != "ZG0F":
        return ()
    result = []
    options = {"高": 2, "中": 3, "低": 4}
    if _writable(ctx, "basicFence", "sensitivity"):

        async def sensitivity(c, data):
            if data.get("option") not in options:
                raise ValueError("Unsupported sensitivity")
            await _send(c, "basicFence", "sensitivity", options[data["option"]])

        result.append(
            EntitySpec(
                "select",
                "radar_sensitivity",
                "检测灵敏度",
                lambda c: {
                    "current_option": next(
                        (
                            label
                            for label, value in options.items()
                            if str(c.value("basicFence", "sensitivity")) == str(value)
                        ),
                        None,
                    )
                },
                {"options": tuple(options)},
                {"select_option": sensitivity},
            )
        )
    if _writable(ctx, "basicFence", "filteringHeight"):

        async def height(c, data):
            value = float(data["value"])
            if not 0 <= value <= 70 or value % 5:
                raise ValueError("Height must be 0–70 cm in 5 cm increments")
            await _send(c, "basicFence", "filteringHeight", int(value))

        result.append(
            EntitySpec(
                "number",
                "radar_minimum_height",
                "最小感应高度",
                lambda c: {
                    "native_value": _numeric(c, "basicFence", "filteringHeight")
                },
                {"min": 0, "max": 70, "step": 5, "unit": "cm"},
                {"set_value": height},
            )
        )
    if _writable(ctx, "action", "action"):

        async def reset(c, data):
            await _send(c, "action", "action", 1)

        result.append(
            EntitySpec(
                "button",
                "radar_reset_unoccupied",
                "重置无人状态",
                lambda c: {},
                actions={"press": reset},
            )
        )
    values = _delay_values(ctx)
    if values is not None and _writable(ctx, "basicFence", "delayTimeList"):
        for i in range(1, 9):
            sid = f"userFence{i}"
            fid = ctx.value(sid, "fenceID")
            if not isinstance(fid, int) or not 0 < fid < len(values):
                continue
            if ctx.value(sid, "fenceType") != 0 or ctx.value(sid, "enableFence") != 1:
                continue
            name = ctx.value(sid, "fenceName") or f"区域{fid}"
            result.append(_delay_entity(sid, fid, name))
    return tuple(result)


def _delay_entity(sid, fid, name):
    options = {"快速响应": "0", "精准响应": "2"}

    def state(c):
        values = _delay_values(c)
        value = values[fid] if values else None
        return {
            "current_option": next((k for k, v in options.items() if v == value), None)
        }

    async def select(c, data):
        if data.get("option") not in options:
            raise ValueError("Unsupported region response mode")
        if not hasattr(c, "_radar_delay_lock"):
            c._radar_delay_lock = asyncio.Lock()
        async with c._radar_delay_lock:
            values = _delay_values(c)
            if (
                values is None
                or c.value(sid, "fenceID") != fid
                or c.value(sid, "enableFence") != 1
            ):
                raise ValueError("Region configuration changed; reload the integration")
            pending = getattr(c, "_radar_delay_pending", None)
            if pending and values[pending[0]] != pending[1]:
                raise ValueError(
                    "Waiting for the previous region setting to be reported"
                )
            value = options[data["option"]]
            if values[fid] == value:
                return
            values[fid] = value
            await _send(c, "basicFence", "delayTimeList", ",".join(values))
            c._radar_delay_pending = (fid, value)

    return EntitySpec(
        "select",
        f"radar_region_{fid}_response",
        f"{name}无人响应",
        state,
        {"options": tuple(options)},
        {"select_option": select},
    )


READINGS = [
    ("basicFenceEvent", "existent", "有人", None, "occupancy", "binary"),
    ("luminance", "current", "光照度原始值", None, None),
    ("luminance", "level", "光照等级", None, None, "enum"),
    ("basicFenceEvent", "standingExistent", "站立状态", None, "occupancy", "binary"),
    ("basicFenceEvent", "nightLightIndication", "起夜状态", None, None, "binary"),
    ("basicFenceEvent", "across", "穿越虚拟墙", None, None, "binary"),
    ("basicFenceEvent", "nonBedStatus", "非床区域活动", None, None, "enum"),
    ("faultDetection", "status", "设备故障", None, "problem", "binary"),
]
SWITCHES = [
    ("switch", "on", "传感器检测"),
    ("switch", "reportSwitch", "事件上报"),
    ("backlight", "on", "指示灯"),
    ("basicFence", "enableFence", "区域检测"),
    ("basicFence", "standingExistentEnable", "站立检测"),
    ("basicFence", "acrossEnable", "安防检测"),
    ("basicFence", "nightLightIndicationEnable", "起夜检测"),
]
SELECTS = [("basicFence", "singleReport", "人员定位上报")]
NUMBERS = [("luminance", "threshold", "光照变化阈值", None)]


class ProductAdapter:
    prod_id = "ZG0F"

    def entities(self, context):
        if (context.prod_id or "").casefold() != self.prod_id.casefold():
            return ()
        result = _reading_entities(context, READINGS)
        for sid, key, name in SWITCHES:
            result.append(_control_switch(context, sid, key, name))
        for sid, key, name in SELECTS:
            result.append(_control_select(context, sid, key, name))
        for sid, key, name, unit in NUMBERS:
            result.append(_control_number(context, sid, key, name, unit))
        result.extend(_radar_map_entities(context))
        result.extend(_radar_option_entities(context))
        result.extend(_radar_tuning_entities(context))
        return tuple((spec for spec in result if spec is not None))


ADAPTER = ProductAdapter()
