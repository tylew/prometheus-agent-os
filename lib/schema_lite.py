#!/usr/bin/env python3
# ---
# name: schema_lite
# description: Stdlib JSON Schema subset for prometheus' own schemas — type, enum, const, pattern, required, properties, additionalProperties, items, minItems, minimum, $ref to #/$defs. Returns every error with its JSON path, never raises on bad data.
# usage: import schema_lite; schema_lite.validate(data, schema, root=schema) → [errors]
# ---
from __future__ import annotations

import re

_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def _is(value, t: str) -> bool:
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, _TYPES[t])


def _resolve(schema: dict, root: dict) -> dict:
    while "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            raise ValueError("only local refs are supported: %s" % ref)
        node = root
        for part in ref[2:].split("/"):
            node = node[part]
        schema = node
    return schema


def validate(data, schema: dict, root: dict | None = None, path: str = "$") -> list[str]:
    root = root or schema
    schema = _resolve(schema, root)
    errs: list[str] = []
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_is(data, x) for x in types):
            return ["%s: expected %s, got %s" % (path, "|".join(types), type(data).__name__)]
    if "const" in schema and data != schema["const"]:
        errs.append("%s: must be %r" % (path, schema["const"]))
    if "enum" in schema and data not in schema["enum"]:
        errs.append("%s: %r not one of %s" % (path, data, schema["enum"]))
    if isinstance(data, str) and "pattern" in schema and not re.search(schema["pattern"], data):
        errs.append("%s: %r does not match %s" % (path, data, schema["pattern"]))
    if isinstance(data, (int, float)) and not isinstance(data, bool) and "minimum" in schema \
            and data < schema["minimum"]:
        errs.append("%s: %r < %r" % (path, data, schema["minimum"]))
    if isinstance(data, dict):
        for key in schema.get("required", []):
            if key not in data:
                errs.append("%s: missing required %r" % (path, key))
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, val in data.items():
            if key in props:
                errs += validate(val, props[key], root, "%s.%s" % (path, key))
            elif extra is False:
                errs.append("%s: unknown field %r" % (path, key))
            elif isinstance(extra, dict):
                errs += validate(val, extra, root, "%s.%s" % (path, key))
    if isinstance(data, list):
        if len(data) < schema.get("minItems", 0):
            errs.append("%s: needs at least %d item(s)" % (path, schema["minItems"]))
        if "items" in schema:
            for i, val in enumerate(data):
                errs += validate(val, schema["items"], root, "%s[%d]" % (path, i))
    return errs
