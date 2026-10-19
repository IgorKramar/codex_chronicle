"""Run only with explicit opt-in and locally configured dedicated integration."""

import os
import uuid

import pytest
from conftest import event

from chronicle.agent import Agent
from chronicle.notion import Publisher


@pytest.mark.skipif(
    os.environ.get("CHRONICLE_LIVE_NOTION") != "1", reason="Live Notion opt-in not configured"
)
def test_real_notion_create_update_read_cleanup(cfg):
    assert os.environ.get("NOTION_TOKEN") and os.environ.get("NOTION_PARENT")
    pid = str(uuid.uuid4())
    cfg["notion_parent"] = os.environ["NOTION_PARENT"]
    cfg["projects"][pid] = {
        "name": "Chronicle synthetic acceptance probe",
        "remote": "",
        "policy": "export",
    }
    agent = Agent(cfg)
    agent.store.append([event(cfg, project=pid)])
    publisher = Publisher(agent.store, cfg)
    try:
        assert publisher.publish()["projects"] == 1
        saved = agent.store.get_meta("notion:page:project:" + pid)
        page = publisher.call("GET", "/pages/" + saved["id"])
        assert page["id"] == saved["id"]
        assert len(list(publisher.pages("/blocks/" + saved["id"] + "/children"))) == 10
        publisher.publish()
        assert agent.store.get_meta("notion:page:project:" + pid)["id"] == saved["id"]
    finally:
        root = agent.store.get_meta("notion:root")
        if root:
            publisher.call("PATCH", "/pages/" + root, {"in_trash": True})
