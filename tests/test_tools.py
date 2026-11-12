import sqlite3

import pytest

from agent.tools import ToolError, safe_eval


def test_query_database_reads_and_is_read_only(toolbox, db_path):
    out = toolbox.execute("query_database", {"sql": "SELECT COUNT(*) AS n FROM orders;"})
    assert out["rows"] == [{"n": 220}]
    assert toolbox.execute("query_database", '{"sql": "WITH x AS (SELECT 1 AS a) SELECT a FROM x"}')["row_count"] == 1
    for bad in ("DELETE FROM orders", "SELECT 1; DROP TABLE orders", "UPDATE orders SET status='x'", "PRAGMA x"):
        with pytest.raises(ToolError):
            toolbox.execute("query_database", {"sql": bad})
    # even a write smuggled inside a WITH statement is stopped by the read-only connection
    with pytest.raises(ToolError):
        toolbox.execute("query_database", {"sql": "WITH x AS (SELECT 1) DELETE FROM orders"})
    assert sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 220


def test_sql_errors_include_the_schema_and_rows_are_capped(toolbox):
    with pytest.raises(ToolError, match="customers\\(id, name"):
        toolbox.execute("query_database", {"sql": "SELECT nope FROM orders"})
    out = toolbox.execute("query_database", {"sql": "SELECT * FROM orders"})
    assert out["row_count"] == 50 and out["truncated"] is True


def test_get_order_status(toolbox):
    order = toolbox.execute("get_order_status", {"order_id": 52})
    assert order["product"] == "Office Chair" and order["status"] == "delivered" and order["days_since_delivery"] == 5
    with pytest.raises(ToolError, match="No order"):
        toolbox.execute("get_order_status", {"order_id": 99999})


def test_search_policies_finds_relevant_section(toolbox):
    results = toolbox.execute("search_policies", {"query": "return window after delivery date"})["results"]
    assert len(results) == 3 and results[0]["section"] == "Return window" and "30 days" in results[0]["text"]
    top = toolbox.execute("search_policies", {"query": "warranty for furniture"})["results"][0]
    assert top["document"] == "Warranty Policy"


def test_calculate_is_safe():
    assert safe_eval("0.85 * 11,998") == pytest.approx(10198.3)
    assert safe_eval("-(2 + 3) ** 2 % 7") == 3
    for bad in ("__import__('os').system('x')", "a + 1", "1/0", "9**999", "len('x')", "True + 1"):
        with pytest.raises(ToolError):
            safe_eval(bad)


def test_create_ticket_and_argument_validation(toolbox, db_path):
    out = toolbox.execute("create_ticket", {"customer_id": 3, "subject": "Late order", "priority": "high",
                                            "order_id": 12})
    row = sqlite3.connect(db_path).execute("SELECT customer_id, order_id, priority, status FROM tickets "
                                           "WHERE id = ?", (out["ticket_id"],)).fetchone()
    assert row == (3, 12, "high", "open")
    cases = [("create_ticket", {"customer_id": 3, "subject": "x", "priority": "urgent"}),
             ("create_ticket", {"customer_id": 999, "subject": "x", "priority": "low"}),
             ("create_ticket", {"customer_id": 3}),
             ("get_order_status", {"order_id": "abc"}),
             ("get_order_status", {"order_id": 1, "extra": 2}),
             ("launch_rocket", {}),
             ("calculate", "not json"),
             ("calculate", "[1, 2]")]
    for name, args in cases:
        with pytest.raises(ToolError):
            toolbox.execute(name, args)
