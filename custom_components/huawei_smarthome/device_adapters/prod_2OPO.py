"""Independent 2OPO adapter with explicit product service mappings.

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


def _reading_entities(ctx, rows):
    result = []
    for row in rows:
        sid, key, name, unit, device_class, *kind = row
        scale = 0.1 if sid in ("temperature", "humidity") else 1
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
    ("battery", "level", "电量", "%", "battery"),
    ("battery", "alarm", "低电量", None, "battery", "binary"),
    ("temperature", "current", "温度", "°C", "temperature"),
    ("humidity", "current", "湿度", "%", "humidity"),
    ("temperature", "level", "温度舒适度", None, None, "enum"),
    ("humidity", "level", "湿度舒适度", None, None, "enum"),
    ("commonFaultDetection", "status", "设备故障", None, "problem", "binary"),
]


class ProductAdapter:
    prod_id = "2OPO"

    def entities(self, context):
        if (context.prod_id or "").casefold() != self.prod_id.casefold():
            return ()
        result = _reading_entities(context, READINGS)
        return tuple((spec for spec in result if spec is not None))


ADAPTER = ProductAdapter()
