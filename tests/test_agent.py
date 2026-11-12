import json

from agent.llm import ToolCallingUnsupported


def test_multi_step_task_chains_tools(make_agent):
    agent, llm = make_agent([
        [("get_order_status", {"order_id": 100})],
        [("search_policies", {"query": "refund for opened product"})],
        [("calculate", {"expression": "0.85 * 11998"})],
        "Yes, it is within 30 days. The refund is 10,198.30 rupees.",
    ])
    result = agent.run("Refund for opened order 100?")
    assert result.tools_used == ["get_order_status", "search_policies", "calculate"]
    assert result.llm_calls == 4 and result.stopped == "answered" and "10,198.30" in result.answer
    assert result.steps[2]["result"]["result"] == 10198.3
    # every tool result is sent back to the model, linked to the call that produced it
    last = llm.requests[-1]["messages"]
    assert [m["role"] for m in last] == ["system", "user", "assistant", "tool", "assistant", "tool", "assistant", "tool"]
    assert last[3]["tool_call_id"] == last[2]["tool_calls"][0]["id"]
    assert "2026-11-01" in last[0]["content"]


def test_tool_error_is_returned_to_model_for_recovery(make_agent):
    agent, llm = make_agent([
        [("query_database", {"sql": "SELECT COUNT(*) FROM order"})],
        [("query_database", {"sql": "SELECT COUNT(*) AS n FROM orders"})],
        "There are 220 orders.",
    ])
    result = agent.run("How many orders?")
    assert [bool(s["error"]) for s in result.steps] == [True, False]
    assert "SQL error" in json.loads(llm.requests[1]["messages"][-1]["content"])["error"]
    assert result.answer == "There are 220 orders."


def test_parallel_tool_calls_and_malformed_arguments(make_agent):
    agent, _ = make_agent([
        [("get_order_status", {"order_id": 52}), ("calculate", "{not json")],
        "Order 52 is delivered.",
    ])
    result = agent.run("Status of order 52?")
    assert len(result.steps) == 2 and result.steps[0]["error"] is None and "JSON" in result.steps[1]["error"]


def test_step_limit_forces_a_final_answer(make_agent):
    agent, llm = make_agent([[("calculate", {"expression": "1+1"})]] * 3 + ["Best effort: 2."], max_steps=3)
    result = agent.run("Loop forever")
    assert result.stopped == "max_steps" and result.answer == "Best effort: 2." and result.llm_calls == 4
    assert llm.requests[-1]["tools"] is None  # the last call cannot use tools


def test_json_protocol_fallback_when_native_tool_calls_fail(make_agent):
    agent, llm = make_agent([
        ToolCallingUnsupported("tool_use_failed"),
        'I will look it up. {"tool": "get_order_status", "arguments": {"order_id": 52}}',
        '```json\n{"final": "Order 52 was delivered."}\n```',
    ])
    result = agent.run("Status of order 52?")
    assert result.protocol == "json" and result.tools_used == ["get_order_status"]
    assert result.answer == "Order 52 was delivered."
    assert llm.requests[1]["tools"] is None and "get_order_status(order_id)" in llm.requests[1]["messages"][0]["content"]


def test_history_is_included(make_agent):
    agent, llm = make_agent(["It was delivered on 2026-10-27."])
    agent.run("And when?", history=[{"role": "user", "content": "Status of order 52?"},
                                    {"role": "assistant", "content": "Delivered."}])
    assert [m["role"] for m in llm.requests[0]["messages"]] == ["system", "user", "assistant", "user"]


def test_json_protocol_accepts_plain_text_answer(make_agent):
    agent, _ = make_agent([ToolCallingUnsupported("x"), "Standard shipping takes 5 to 7 business days."])
    result = agent.run("How long is standard shipping?")
    assert result.protocol == "json" and result.answer.startswith("Standard shipping")
