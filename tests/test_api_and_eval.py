from fastapi.testclient import TestClient

from agent.api import create_app
from agent.config import Settings
from agent.store import Store
from eval.run_eval import run_tasks, summarise, to_markdown
from eval.tasks import build_tasks, has_number, numbers
from tests.conftest import TODAY


def client_for(agent, tmp_path):
    return TestClient(create_app(Settings(_env_file=None), agent=agent, store=Store(str(tmp_path / "s.db"))))


def test_chat_keeps_session_memory_and_trace(make_agent, tmp_path):
    agent, llm = make_agent([[("get_order_status", {"order_id": 52})], "Order 52 is delivered.", "On 2026-10-27."])
    client = client_for(agent, tmp_path)
    first = client.post("/chat", json={"message": "Status of order 52?"}).json()
    assert first["answer"] == "Order 52 is delivered." and first["tools_used"] == ["get_order_status"]
    second = client.post("/chat", json={"message": "When?", "session_id": first["session_id"]}).json()
    assert second["session_id"] == first["session_id"]
    assert llm.requests[-1]["messages"][1]["content"] == "Status of order 52?"  # memory from turn one
    turns = client.get(f"/sessions/{first['session_id']}").json()["turns"]
    assert len(turns) == 2 and turns[0]["steps"][0]["tool"] == "get_order_status"


def test_chat_validation_and_llm_failure(make_agent, tmp_path):
    agent, _ = make_agent([RuntimeError("quota")])
    client = client_for(agent, tmp_path)
    assert client.post("/chat", json={"message": "x"}).status_code == 422
    assert client.post("/chat", json={"message": "   "}).status_code == 422
    assert client.post("/chat", json={"message": "hello", "session_id": 77}).status_code == 404
    assert client.get("/sessions/77").status_code == 404
    assert client.post("/chat", json={"message": "hello there"}).status_code == 502
    assert client.get("/health").json()["status"] == "ok"


def test_number_matching():
    assert numbers("Refund: ₹10,198.30 (85% of 11,998)") == [10198.30, 85, 11998]
    assert has_number("about 10,198 rupees", 10198.3) and not has_number("10,298", 10198.3)


def test_eval_tasks_have_consistent_ground_truth(db_path, toolbox, make_agent):
    tasks = build_tasks(db_path, TODAY)
    assert len(tasks) == 22 and len({t["id"] for t in tasks}) == 22
    by_id = {t["id"]: t for t in tasks}
    assert by_id["db_count"]["check"]("There are 22 shipped orders.") and not by_id["db_count"]["check"]("21")
    assert by_id["db_join"]["check"]("Customer 7 spent 44,683.00") is False  # the name is required too
    assert by_id["multi_return_expired"]["check"]("No, the 30-day window has passed.")
    assert by_id["policy_cancel"]["check"]("A shipped order cannot be cancelled.")
    assert not by_id["multi_address"]["check"]("No, it cannot be changed.")
    assert by_id["multi_address"]["check"]("Yes, it can still be changed while processing.")
    assert not by_id["action_ticket"]["check"]("done")  # no ticket yet

    # a scripted agent that solves two tasks, to exercise the runner and the summary
    agent, _ = make_agent([
        [("query_database", {"sql": "SELECT COUNT(*) FROM orders WHERE status='shipped'"})], "22 orders are shipped.",
        "Probably 5 customers.",
    ])
    rows = run_tasks(agent, [by_id["db_count"], by_id["db_filter"]])
    assert [(r["success"], r["tools_ok"]) for r in rows] == [(True, True), (False, False)]
    summary = summarise(rows)
    assert summary["success_rate"] == 0.5 and summary["avg_tool_calls"] == 0.5
    assert "| Task success rate | 50.0% |" in to_markdown(summary, rows, "m")


def test_ticket_task_checks_database_state(db_path, toolbox):
    tasks = {t["id"]: t for t in build_tasks(db_path, TODAY)}
    import re
    customer = int(re.search(r"customer (\d+)", tasks["action_ticket"]["q"]).group(1))
    toolbox.execute("create_ticket", {"customer_id": customer, "subject": "Delayed order", "priority": "medium"})
    assert not tasks["action_ticket"]["check"]("created")
    toolbox.execute("create_ticket", {"customer_id": customer, "subject": "Delayed order", "priority": "high"})
    assert tasks["action_ticket"]["check"]("created")
