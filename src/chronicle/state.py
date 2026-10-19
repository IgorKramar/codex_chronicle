import datetime as dt
from collections import Counter, defaultdict
from typing import Any

from .events import now


def session_key(e):
    return ":".join(e[k] for k in ("computer_id", "session_id", "agent_id"))


def build_state(events, stale_seconds=1800, clock=None):
    clock = clock or dt.datetime.now(dt.UTC)
    sessions: dict[str, Any] = {}
    reports, decisions, issues, tests, files = [], [], [], [], set()
    for e in events:
        key = session_key(e)
        p = e["payload"]
        s = sessions.setdefault(
            key,
            {
                "key": key,
                "session_id": e["session_id"],
                "computer_id": e["computer_id"],
                "agent_id": e["agent_id"],
                "project_id": e["project_id"],
                "status": "Unknown",
                "started_at": e["occurred_at"],
                "last_activity": e["occurred_at"],
                "ended_at": None,
                "model": "Unknown",
                "task": "Не зафиксирована",
                "event_ids": [],
            },
        )
        s["event_ids"].append(e["event_id"])
        s["started_at"] = min(s["started_at"], e["occurred_at"])
        # Late delivery must not overwrite a newer lifecycle state.
        if (
            e["kind"] not in {"Checkpoint", "MemoryReport", "GitSnapshot"}
            and e["occurred_at"] >= s["last_activity"]
            and not (
                e["occurred_at"] == s["last_activity"]
                and (s["ended_at"] is not None or s["status"] == "Interrupted")
                and e["kind"] not in {"SessionEnd", "SubagentStop", "Interrupt"}
            )
        ):
            s["last_activity"] = e["occurred_at"]
            if e["kind"] in {
                "SessionStart",
                "SubagentStart",
                "UserPromptSubmit",
                "PreToolUse",
                "PostToolUse",
                "Stop",
            }:
                s["status"] = "Running"
                s["ended_at"] = None
            elif e["kind"] == "Interrupt":
                s["status"] = "Interrupted"
            elif e["kind"] == "SubagentStop":
                s["status"] = "Unknown"
                s["ended_at"] = e["occurred_at"]
            elif e["kind"] == "SessionEnd":
                s["status"] = "Unknown"
                s["ended_at"] = e["occurred_at"]
        if "model" in p:
            s["model"] = p["model"]
        if "task" in p:
            s["task"] = p["task"]
        files.update(p.get("files", []))
        if e["kind"] == "PostToolUse" and "exit_code" in p:
            # Tool completion is observed. It is not necessarily a test.
            tests.append(
                {
                    "event_id": e["event_id"],
                    "tool": p.get("tool_name"),
                    "exit_code": p["exit_code"],
                    "test_status": p.get("test_status", "Unknown"),
                    "test_runner": p.get("test_runner"),
                    "evidence": e["evidence"],
                    "execution_status": p.get("execution_status", "unknown"),
                }
            )
        if e["kind"] == "MemoryReport":
            report = dict(
                p["report"],
                event_id=e["event_id"],
                session_key=key,
                occurred_at=e["occurred_at"],
                evidence="agent_reported",
            )
            reports.append(report)
            for d in report.get("Decisions", []):
                if isinstance(d, dict):
                    decisions.append(dict(d, source_event=e["event_id"], evidence="agent_reported"))
            for issue in report.get("Problems", []):
                if isinstance(issue, dict):
                    issues.append(
                        dict(issue, source_event=e["event_id"], evidence="agent_reported")
                    )
    for s in sessions.values():
        age = (clock - dt.datetime.fromisoformat(s["last_activity"])).total_seconds()
        if s["status"] == "Running" and age > stale_seconds:
            s["status"] = "Stale"
    # Keep revisions. IDs are scoped by project and explicitly supersede older revisions.
    current_decisions: dict[str, Any] = {}
    current_issues: dict[str, Any] = {}
    for collection, target in [(decisions, current_decisions), (issues, current_issues)]:
        for item in collection:
            identity = item.get("id")
            if identity:
                target.setdefault(identity, []).append(item)
    issue_states = {}
    for iid, revisions in current_issues.items():
        closed_sources = {
            ref for r in revisions if r["status"] == "Resolved" for ref in r.get("resolves", [])
        }
        unresolved = [
            r["source_event"]
            for r in revisions
            if r["status"] == "Open" and r["source_event"] not in closed_sources
        ]
        issue_states[iid] = {
            "status": "Open" if unresolved else "Resolved",
            "unresolved_sources": unresolved,
        }
    latest = reports[-1] if reports else {}
    latest_by_session = {r["session_key"]: r for r in reports}
    conflicts = {}
    for did, revisions in current_decisions.items():
        accepted = [r for r in revisions if r["status"] == "Accepted"]
        retired = {r.get("supersedes") for r in revisions if r.get("supersedes")}
        active = [r for r in accepted if r["source_event"] not in retired]
        if len({json_text(r["choice"]) for r in active}) > 1:
            conflicts[did] = [r["source_event"] for r in active]
    return {
        "schema_version": 1,
        "project_id": events[0]["project_id"] if events else None,
        "project": events[0]["project"] if events else {},
        "updated_at": now(),
        "sessions": list(sessions.values()),
        "reports": reports,
        "decisions": current_decisions,
        "issues": current_issues,
        "issue_states": issue_states,
        "tool_results": tests,
        "changed_files": sorted(files),
        "event_count": len(events),
        "latest_report": latest,
        "latest_reports_by_session": latest_by_session,
        "decision_conflicts": conflicts,
        "evidence_ids": [e["event_id"] for e in events],
        "last_activity": max(
            (e["occurred_at"] for e in events if e["kind"] != "Checkpoint"), default=None
        ),
    }


def latest_test_results(tests):
    return {
        (t["project_id"], t["test_id"]): t for t in sorted(tests, key=lambda t: t["revision"])
    }.values()


def render_state(state, fip_context=None, fip_tests=()):
    r = state["latest_report"]
    context = fip_context or {}
    tests = [
        {
            "name": t["test_runner"],
            "status": t["test_status"],
            "provenance": t["evidence"],
            "source": t["event_id"],
            "channel": "legacy",
            "execution_status": t["execution_status"],
            "exit_code": t["exit_code"],
            "source_event_ids": [t["event_id"]],
        }
        for t in state["tool_results"]
        if t["test_runner"]
    ]
    tests += [dict(t, source=t["record_id"], channel="FIP") for t in latest_test_results(fip_tests)]
    counts = Counter((t["provenance"], t["status"]) for t in tests)
    test_summary = (
        "; ".join(
            f"{provenance}: {status} — {count}"
            for (provenance, status), count in sorted(counts.items())
        )
        or "Тестовые результаты не зарегистрированы ни в legacy, ни в FIP."
    )
    test_details = [
        f"- {t['name']} — {t['status']} [{t['provenance']}; {t['channel']}]; "
        f"execution={t['execution_status']}, exit_code={t['exit_code']}; "
        f"источник: {t['source']}; evidence: {json_text(t.get('source_event_ids', []))}"
        for t in tests
    ]
    updated_at = max(
        state["updated_at"],
        context.get("timestamp", state["updated_at"]),
        key=dt.datetime.fromisoformat,
    )
    lines = [
        "# Current State — " + state["project"].get("name", context.get("name", "Unknown")),
        "Обновлено: " + updated_at,
        "\n## Кратко",
        "Тесты: " + test_summary,
        "Статус теста относится к одному запуску; agent_reported — отчёт, observed — наблюдение.",
        "Событий legacy: " + str(state["event_count"]),
        "Статусы сессий: " + json_text(dict(Counter(s["status"] for s in state["sessions"]))),
    ]
    sections = [
        ("Что представляет собой проект", state["project"]),
        ("Текущая цель разработки", r.get("Task", context.get("current_goal", "Не зафиксирована"))),
        (
            "Что реализовано — по отчётам агентов",
            [v.get("Changes", []) for v in state["latest_reports_by_session"].values()],
        ),
        (
            "Тесты и подробности по источникам",
            "\n".join(test_details) or test_summary,
        ),
        (
            "Что находится в работе",
            [
                {"session": s["key"], "task": s["task"], "status": s["status"]}
                for s in state["sessions"]
            ],
        ),
        ("Обнаруженные проблемы", state["issues"]),
        ("Решения и причины — история, не только принятые", state["decisions"]),
        (
            "Что осталось сделать",
            [v.get("Next Steps", []) for v in state["latest_reports_by_session"].values()],
        ),
        ("Когда обновлено", updated_at),
        (
            "Подтверждающие источники",
            {
                "report_events": [
                    v["event_id"] for v in state["latest_reports_by_session"].values()
                ],
                "tool_results": state["tool_results"],
                "confidence": r.get("Confidence", "Не установлена"),
            },
        ),
    ]
    for label, content in sections:
        lines += ["\n## " + label, json_text(content)]
    if context:
        lines += ["\n## Подробности FIP и источники", context["llm_summary"]]
    lines += [
        "\nКонфликты решений: " + json_text(state["decision_conflicts"]),
        "Отчёты и обоснования: agent_reported; первичные наблюдения: observed. "
        "Успех тестов не выводится из одного факта запуска команды.",
    ]
    return "\n".join(lines)


def json_text(v):
    import json

    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def period_summary(events, date, days=1):
    start = dt.date.fromisoformat(date)
    end = start + dt.timedelta(days=days)
    previous = start - dt.timedelta(days=days)
    current, prior = [], []
    for e in events:
        day = dt.datetime.fromisoformat(e["occurred_at"]).astimezone(dt.UTC).date()
        if start <= day < end:
            current.append(e)
        elif previous <= day < start:
            prior.append(e)
    grouped = defaultdict(list)
    for e in current:
        grouped[e["project_id"]].append(e)
    return {
        "start": date,
        "days": days,
        "timezone": "UTC",
        "event_count": len(current),
        "previous_event_count": len(prior),
        "event_delta": len(current) - len(prior),
        "meaning": "Количество событий не является метрикой завершённых задач",
        "agents": sorted({session_key(e) for e in current}),
        "projects": {k: build_state(v) for k, v in grouped.items()},
    }


def render_period_summary(summary):
    lines = [
        f"Отчёт с {summary['start']} на {summary['days']} дн., UTC",
        f"Агентов/сессий: {len(summary['agents'])}; событий: {summary['event_count']}; "
        f"предыдущий период: {summary['previous_event_count']}",
        summary["meaning"],
    ]
    for pid, state in summary["projects"].items():
        lines += [
            "\nПроект: " + state["project"].get("name", pid),
            "Сессии: "
            + json_text(
                [
                    {k: s[k] for k in ("session_id", "computer_id", "agent_id", "status")}
                    for s in state["sessions"]
                ]
            ),
            "Подтверждённые test runs: "
            + json_text([r for r in state["tool_results"] if r["test_status"] == "Passed"]),
            "Ошибки tool calls: "
            + json_text([r for r in state["tool_results"] if r["exit_code"] != 0]),
        ]
        for report in state["latest_reports_by_session"].values():
            lines += [
                "Задача (agent_reported): " + report["Task"],
                "Изменения: " + json_text(report["Changes"]),
                "Проблемы: " + json_text(report["Problems"]),
                "Где остановились / следующий шаг: " + json_text(report["Next Steps"]),
                "Источник: " + report["event_id"],
            ]
        if not state["reports"]:
            lines += ["Содержательный отчёт агента отсутствует; завершение задач не установлено."]
    return "\n".join(lines)
