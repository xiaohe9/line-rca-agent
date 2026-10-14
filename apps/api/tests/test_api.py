"""API surface tests: the SSE stream is the contract the UI depends on."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from line_rca_api.main import app

client = TestClient(app)


def test_health_describes_the_live_composition() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["orchestrator"] == {"planner": "plan-execute", "executor": "react"}
    assert "query_defects" in body["tools"]
    assert body["traceSchemaVersion"] == "1"


def test_public_config_never_leaks_credentials() -> None:
    body = client.get("/config").json()
    assert set(body) == {"env", "demoMode", "traceSchemaVersion"}


def test_tools_catalogue_matches_the_registry() -> None:
    tools = client.get("/api/tools").json()["tools"]
    names = [tool["name"] for tool in tools]

    assert names == ["query_defects", "query_telemetry"]
    for tool in tools:
        assert tool["inputSchema"]["type"] == "object"
        assert tool["description"]


def test_collected_run_produces_a_full_trace_and_an_answer() -> None:
    response = client.post("/api/analyze/collect", json={"goal": "为什么 B-2041 批次良率下降？"})

    assert response.status_code == 200
    body = response.json()
    types = [event["type"] for event in body["events"]]

    assert types[0] == "run.started"
    assert types[-1] == "run.finished"
    assert "plan.created" in types
    assert "tool.called" in types
    assert body["failed"] is None
    assert body["answer"] is not None
    assert "划伤" in body["answer"]


def test_streaming_run_emits_sse_frames_in_order() -> None:
    with client.stream(
        "POST", "/api/analyze", json={"goal": "为什么 B-2041 良率下降？"}
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        raw = "".join(response.iter_text())

    frames = [frame for frame in raw.split("\n\n") if frame.strip()]
    names = [frame.split("\n", 1)[0].removeprefix("event: ") for frame in frames]

    assert names[0] == "run.started"
    assert names[-1] == "run.finished"
    assert all(name for name in names)

    payloads = [json.loads(frame.split("data: ", 1)[1]) for frame in frames]
    assert [payload["seq"] for payload in payloads] == list(range(1, len(payloads) + 1))
    assert {payload["schema_version"] for payload in payloads} == {"1"}


def test_empty_goal_is_rejected_before_any_llm_call() -> None:
    response = client.post("/api/analyze/collect", json={"goal": ""})
    assert response.status_code == 422
