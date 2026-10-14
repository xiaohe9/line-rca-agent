"""API surface tests.

These are integration tests: they run against a real Postgres, because the schema, the seed
data and the SQL are all part of what the endpoints promise. The tool layer has its own
database-free tests in `test_tools.py`.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

EXPECTED_TOOLS = [
    "create_work_order",
    "find_similar_cases",
    "list_work_orders",
    "query_defects",
    "query_telemetry",
]


def test_live_does_not_touch_the_database(client: TestClient) -> None:
    response = client.get("/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_confirms_database_access(client: TestClient) -> None:
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_health_describes_the_live_composition(client: TestClient) -> None:
    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["orchestrator"] == {"planner": "plan-execute", "executor": "react"}
    assert body["tools"] == EXPECTED_TOOLS
    assert body["traceSchemaVersion"] == "1"


def test_public_config_never_leaks_credentials(client: TestClient) -> None:
    body = client.get("/config").json()
    assert set(body) == {"env", "demoMode", "traceSchemaVersion"}


def test_tools_catalogue_matches_the_registry(client: TestClient) -> None:
    tools = client.get("/api/tools").json()["tools"]

    assert [tool["name"] for tool in tools] == EXPECTED_TOOLS
    for tool in tools:
        assert tool["inputSchema"]["type"] == "object"
        assert tool["description"]


def test_batches_endpoint_reports_the_seeded_defect_rates(client: TestClient) -> None:
    batches = {item["batchId"]: item for item in client.get("/api/batches").json()["batches"]}

    # The anomalous batch is the story the seeded data is built to tell.
    assert batches["B-2041"]["defectRate"] > 0.35
    assert batches["B-2040"]["defectRate"] < 0.10
    assert batches["B-2041"]["source"] == "simulated"


def test_batch_defects_endpoint_concentrates_on_one_station(client: TestClient) -> None:
    body = client.get("/api/batches/B-2041/defects").json()

    assert body["found"] is True
    top = body["breakdown"][0]
    assert top["station"] == "镀膜"
    assert top["defectType"] == "划伤"


def test_unknown_batch_reports_absence_rather_than_inventing(client: TestClient) -> None:
    body = client.get("/api/batches/B-9999/defects").json()
    assert body["found"] is False
    assert body["defects"] == []


def test_collected_run_produces_a_full_trace_and_an_answer(client: TestClient) -> None:
    response = client.post("/api/analyze/collect", json={"goal": "为什么 B-2041 批次良率下降？"})

    assert response.status_code == 200
    body = response.json()
    types = [event["type"] for event in body["events"]]

    assert body["runId"].startswith("run-")
    assert types[0] == "run.started"
    assert types[-1] == "run.finished"
    assert types.count("tool.called") == 4
    assert body["failed"] is None
    assert "镀膜" in body["answer"]


def test_streaming_run_emits_sse_frames_in_order(client: TestClient) -> None:
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

    payloads = [json.loads(frame.split("data: ", 1)[1]) for frame in frames]
    assert [payload["seq"] for payload in payloads] == list(range(1, len(payloads) + 1))
    assert len({payload["run_id"] for payload in payloads}) == 1


def test_a_run_opens_a_work_order(client: TestClient) -> None:
    run_id = client.post("/api/analyze/collect", json={"goal": "良率异常"}).json()["runId"]

    orders = client.get("/api/workorders", params={"status": "open"}).json()["workOrders"]
    assert orders, "the demo run should have opened a work order"

    created = orders[0]
    assert created["station"] == "镀膜"
    assert created["batchId"] == "B-2041"
    assert created["priority"] == "high"
    assert created["id"].startswith("WO-")
    assert created["id"] != "WO-20260901-001"
    assert run_id.startswith("run-")


def test_seeded_historical_work_order_is_present(client: TestClient) -> None:
    orders = client.get("/api/workorders", params={"limit": 100}).json()["workOrders"]
    historical = [order for order in orders if order["id"] == "WO-20260901-001"]

    assert len(historical) == 1
    assert historical[0]["status"] == "closed"
    assert "导向轮" in historical[0]["rootCause"]


def test_empty_goal_is_rejected_before_any_llm_call(client: TestClient) -> None:
    assert client.post("/api/analyze/collect", json={"goal": ""}).status_code == 422
