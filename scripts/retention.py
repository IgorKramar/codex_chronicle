"""Explicit collector retention; operator stops collector and backs up first."""

import argparse
import datetime as dt
import os

from chronicle.events import now
from chronicle.store import Store

p = argparse.ArgumentParser()
p.add_argument("--days", type=int, required=True)
p.add_argument("--confirm", action="store_true")
a = p.parse_args()
if not a.confirm or a.days < 1:
    p.error("Positive --days and --confirm required after backup")
store = Store(os.environ["CHRONICLE_DATABASE"])
cutoff = (dt.datetime.now(dt.UTC) - dt.timedelta(days=a.days)).isoformat()
store.purge(before=cutoff)
store.set_meta(
    "retention:last_purge",
    {"before": cutoff, "at": now(), "evidence_available": "backup only before cutoff"},
)
print("Retention applied; pending events preserved.")
