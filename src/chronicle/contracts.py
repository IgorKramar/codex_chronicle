"""FIP schema validation; depends only on JSON Schema, never on HTTP/MCP/Notion."""

import json
from importlib.resources import files

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

BUNDLE = json.loads(
    files("chronicle").joinpath("assets/fip/v1/fip.schema.json").read_text(encoding="utf-8")
)
REGISTRY = Registry().with_resource(BUNDLE["$id"], Resource.from_contents(BUNDLE))
CATEGORIES = BUNDLE["$defs"]["KnowledgeRecord"]["properties"]["category"]["enum"]
OPERATIONS = [
    name.removesuffix("Arguments") for name in BUNDLE["$defs"] if name.endswith("Arguments")
]


def validate(name, value):
    Draft202012Validator(
        BUNDLE["$defs"][name], registry=REGISTRY, format_checker=FormatChecker()
    ).validate(value)
    return value


def embedded(name):
    """Self-contained schema for OpenAPI/MCP; no network $ref resolution."""
    schema = json.loads(json.dumps(BUNDLE["$defs"][name]))

    def rewrite(value):
        if isinstance(value, dict):
            return {
                k: v.replace("urn:fip:v1#/$defs/", "#/$defs/") if k == "$ref" else rewrite(v)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [rewrite(v) for v in value]
        return value

    schema = rewrite(schema)
    # Only reachable definitions: including every response in every tool is wasteful.
    needed, pending = {}, [schema]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            if "$ref" in item:
                key = item["$ref"].split("/")[-1]
                if key not in needed:
                    needed[key] = rewrite(BUNDLE["$defs"][key])
                    pending.append(needed[key])
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    if needed:
        schema["$defs"] = needed
    return schema
