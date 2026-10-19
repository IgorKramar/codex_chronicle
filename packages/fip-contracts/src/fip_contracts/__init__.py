"""Standalone schemas; no Chronicle transport or storage dependency."""

import json
from importlib.resources import files

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

__version__ = "1.0.0"


def schema(name=None):
    bundle = json.loads(files(__package__).joinpath("schemas/v1/fip.schema.json").read_text())
    return bundle if name is None else bundle["$defs"][name]


def validate(name, value):
    bundle = schema()
    registry = Registry().with_resource(bundle["$id"], Resource.from_contents(bundle))
    Draft202012Validator(
        bundle["$defs"][name], registry=registry, format_checker=FormatChecker()
    ).validate(value)
    return value
