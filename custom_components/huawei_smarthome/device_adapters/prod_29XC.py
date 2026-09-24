"""Independent 29XC adapter with explicit product service mappings.

Field mappings and command validation are local to this product.
"""

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


READINGS = [
    ("Temp", "display", "温度", "°C", "temperature"),
    ("HUM", "display", "湿度", "%", "humidity"),
    ("commonFilterElement1", "alarm", "滤网更换提醒", None, "problem", "binary"),
    ("commonFilterElement1", "leftTime", "滤网剩余时间", "h", None),
    ("commonFaultDetection", "code", "故障代码", None, None, "enum"),
    ("commonFaultDetection", "status", "设备故障", None, "problem", "binary"),
]
SWITCHES = [("childLockSwitch", "on", "童锁"), ("Purify", "Purify", "光催化")]
SELECTS = [("SetSpeed", "set", "风速")]
NUMBERS = [("Countdown", "Countdown", "定时关机", "h")]


def _dehumidifier(ctx):
    needed = [("switch", "on"), ("SetDUM", "SetDUM"), ("SetMode", "set")]
    if not all((_writable(ctx, *f) for f in needed)):
        return ()
    modes = {
        str(x["enumVal"]): x["descCh"]
        for x in _field(ctx, "SetMode", "set")["enumList"]
    }

    def state(c):
        return {
            "is_on": _boolean(c.value("switch", "on")),
            "current_humidity": _numeric(c, "HUM", "display"),
            "target_humidity": _numeric(c, "SetDUM", "SetDUM"),
            "mode": modes.get(str(c.value("SetMode", "set"))),
        }

    async def on(c, data):
        await _send(c, "switch", "on", 1)

    async def off(c, data):
        await _send(c, "switch", "on", 0)

    async def humidity(c, data):
        await _send(c, "SetDUM", "SetDUM", data["humidity"])

    async def mode(c, data):
        value = next((v for v, label in modes.items() if label == data["mode"]), None)
        if value is None:
            raise ValueError("Unknown dehumidifier mode")
        await _send(c, "SetMode", "set", int(value))

    return (
        EntitySpec(
            "humidifier",
            "dehumidifier",
            "除湿控制",
            state,
            {
                "device_class": "dehumidifier",
                "min_humidity": 30,
                "max_humidity": 80,
                "modes": tuple(modes.values()),
            },
            {
                "turn_on": on,
                "turn_off": off,
                "set_humidity": humidity,
                "set_mode": mode,
            },
        ),
    )


class ProductAdapter:
    prod_id = "29XC"

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
        result.extend(_dehumidifier(context))
        return tuple((spec for spec in result if spec is not None))


ADAPTER = ProductAdapter()
