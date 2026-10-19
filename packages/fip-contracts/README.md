# fip-contracts 1.0.0

Standalone FIP v1 JSON Schema bundle and synthetic examples. Requires Python 3.11+ and jsonschema; no Chronicle, database, HTTP or MCP dependency.

```python
from fip_contracts import schema, validate

validate("AgentEvent", event_dict)
bundle = schema()  # $defs and local URN identity
```

Schema dialect is Draft 2020-12; confidence labels are subjective, never probabilities. See the Chronicle distribution's contracts/fip/v1/README.md for field semantics and compatibility rules. Named schemas use URN references resolved by `validate`, without network access.
