"""Conservative compatibility: v1 shapes are frozen; new definitions are additive."""

import argparse
import json
from pathlib import Path


def shape(value):
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            if key in {"description", "title", "examples", "$comment"}:
                continue
            if key in {
                "properties",
                "patternProperties",
                "$defs",
                "definitions",
                "dependentSchemas",
            }:
                # Property/definition names are data, even when named title or description.
                result[key] = {name: shape(schema) for name, schema in child.items()}
            elif key in {"const", "enum", "default"}:
                result[key] = child
            else:
                result[key] = shape(child)
        return result
    if isinstance(value, list):
        return [shape(v) for v in value]
    return value


def check(previous, current):
    changes = []
    for name, schema in previous["$defs"].items():
        if name not in current["$defs"]:
            changes.append("removed definition: " + name)
        elif shape(schema) != shape(current["$defs"][name]):
            changes.append("changed v1 shape: " + name)
    if previous["$id"] != current["$id"] or previous["$schema"] != current["$schema"]:
        changes.append("changed contract identity or schema dialect")
    return changes


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument(
        "--baseline", type=Path, default=Path("contracts/fip/v1/compatibility-baseline.json")
    )
    p.add_argument("--current", type=Path, default=Path("contracts/fip/v1/fip.schema.json"))
    a = p.parse_args()
    issues = check(
        json.loads(a.baseline.read_text(encoding="utf-8")),
        json.loads(a.current.read_text(encoding="utf-8")),
    )
    if issues:
        raise SystemExit("\n".join(issues))
    print("FIP v1 compatibility passed: existing public shapes unchanged")
