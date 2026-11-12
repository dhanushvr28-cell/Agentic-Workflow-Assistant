"""The tools the agent can call. Every tool returns a JSON-serialisable dict; failures raise ToolError."""
import ast
import json
import operator
import os
import re
import sqlite3
from datetime import date

import numpy as np

from .seed import SCHEMA_DESCRIPTION

KB_DIR = os.path.join(os.path.dirname(__file__), "kb")
MAX_ROWS = 50


class ToolError(Exception):
    """An error the model can read and recover from (bad arguments, invalid SQL, unknown id)."""


# ---------- knowledge base search ----------
class SentenceTransformerEmbedder:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.asarray(self.model.encode(texts, normalize_embeddings=True))


class KnowledgeBase:
    """Policy documents split by section and searched by embedding similarity."""

    def __init__(self, embedder, kb_dir: str = KB_DIR):
        self.embedder = embedder
        self.sections: list[dict] = []
        for name in sorted(os.listdir(kb_dir)):
            if not name.endswith(".md"):
                continue
            with open(os.path.join(kb_dir, name), encoding="utf-8") as f:
                text = f.read()
            title = text.splitlines()[0].lstrip("# ").strip()
            for block in re.split(r"\n## ", text)[1:]:
                heading, _, body = block.partition("\n")
                self.sections.append({"document": title, "section": heading.strip(), "text": body.strip()})
        self.vectors = np.asarray(self.embedder.embed(
            [f"{s['document']} - {s['section']}. {s['text']}" for s in self.sections]))

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        scores = self.vectors @ np.asarray(self.embedder.embed([query]))[0]
        best = np.argsort(-scores)[:top_k]
        return [dict(self.sections[i], score=round(float(scores[i]), 3)) for i in best]


# ---------- safe arithmetic ----------
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Mod: operator.mod, ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}


def safe_eval(expression: str) -> float:
    def ev(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ToolError("Exponent too large.")
            return _OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        raise ToolError("Only numbers and + - * / % ** ( ) are allowed.")
    try:
        return ev(ast.parse(expression.replace(",", ""), mode="eval").body)
    except ToolError:
        raise
    except ZeroDivisionError:
        raise ToolError("Division by zero.")
    except Exception:
        raise ToolError(f"Could not parse expression: {expression!r}")


# ---------- toolbox ----------
class Toolbox:
    def __init__(self, db_path: str, kb: KnowledgeBase, reference_date: str):
        self.db_path, self.kb, self.today = db_path, kb, date.fromisoformat(reference_date)

    def _read(self, sql: str, params: tuple = ()) -> list[dict]:
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)  # read-only at the connection level
        con.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in con.execute(sql, params).fetchmany(MAX_ROWS)]
        finally:
            con.close()

    def query_database(self, sql: str) -> dict:
        statement = sql.strip().rstrip(";").strip()
        if ";" in statement or not re.match(r"(?is)^(select|with)\b", statement):
            raise ToolError("Only a single SELECT statement is allowed.")
        try:
            rows = self._read(statement)
        except sqlite3.Error as exc:
            raise ToolError(f"SQL error: {exc}. Schema:\n{SCHEMA_DESCRIPTION}")
        return {"row_count": len(rows), "rows": rows, "truncated": len(rows) == MAX_ROWS}

    def get_order_status(self, order_id: int) -> dict:
        rows = self._read(
            "SELECT o.*, p.name AS product, p.category, c.name AS customer FROM orders o "
            "JOIN products p ON p.id = o.product_id JOIN customers c ON c.id = o.customer_id WHERE o.id = ?",
            (int(order_id),))
        if not rows:
            raise ToolError(f"No order with id {order_id}.")
        order = rows[0]
        order["days_since_order"] = (self.today - date.fromisoformat(order["order_date"])).days
        if order["delivered_date"]:
            order["days_since_delivery"] = (self.today - date.fromisoformat(order["delivered_date"])).days
        return order

    def search_policies(self, query: str) -> dict:
        if not query.strip():
            raise ToolError("query must not be empty.")
        return {"results": self.kb.search(query)}

    def calculate(self, expression: str) -> dict:
        return {"expression": expression, "result": round(safe_eval(expression), 4)}

    def create_ticket(self, customer_id: int, subject: str, priority: str, order_id: int | None = None) -> dict:
        if priority not in ("low", "medium", "high"):
            raise ToolError("priority must be one of: low, medium, high.")
        if not subject.strip():
            raise ToolError("subject must not be empty.")
        if not self._read("SELECT 1 FROM customers WHERE id = ?", (int(customer_id),)):
            raise ToolError(f"No customer with id {customer_id}.")
        con = sqlite3.connect(self.db_path)
        try:
            cur = con.execute(
                "INSERT INTO tickets (customer_id, order_id, subject, priority, created_at) VALUES (?,?,?,?,?)",
                (int(customer_id), order_id, subject.strip(), priority, self.today.isoformat()))
            con.commit()
            return {"ticket_id": cur.lastrowid, "status": "open", "priority": priority}
        finally:
            con.close()

    def execute(self, name: str, arguments: str | dict) -> dict:
        """Validate and run one tool call. Raises ToolError with a message the model can act on."""
        spec = next((t["function"] for t in TOOL_SCHEMAS if t["function"]["name"] == name), None)
        if spec is None:
            raise ToolError(f"Unknown tool '{name}'. Available: {[t['function']['name'] for t in TOOL_SCHEMAS]}")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except json.JSONDecodeError:
                raise ToolError("Arguments were not valid JSON.")
        if not isinstance(arguments, dict):
            raise ToolError("Arguments must be a JSON object.")
        props, required = spec["parameters"]["properties"], spec["parameters"].get("required", [])
        missing = [k for k in required if k not in arguments]
        unknown = [k for k in arguments if k not in props]
        if missing or unknown:
            raise ToolError(f"Bad arguments for {name}: missing {missing}, unknown {unknown}.")
        try:
            return getattr(self, name)(**arguments)
        except (TypeError, ValueError) as exc:
            raise ToolError(f"Bad argument value for {name}: {exc}")


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required}}}


TOOL_SCHEMAS = [
    _tool("query_database",
          "Run one read-only SQL SELECT on the shop database (SQLite). Use for counts, totals, lists and "
          "lookups across customers, products, orders and tickets. Schema:\n" + SCHEMA_DESCRIPTION,
          {"sql": {"type": "string", "description": "A single SELECT statement."}}, ["sql"]),
    _tool("get_order_status",
          "Get one order with product, customer, status, dates and days since order/delivery.",
          {"order_id": {"type": "integer"}}, ["order_id"]),
    _tool("search_policies",
          "Search company policy documents (returns, refunds, shipping, warranty, cancellation, loyalty). "
          "Use for any question about rules, time limits, fees or eligibility.",
          {"query": {"type": "string"}}, ["query"]),
    _tool("calculate", "Evaluate an arithmetic expression exactly. Use for any percentage, sum or difference.",
          {"expression": {"type": "string", "description": "e.g. 0.85 * 6998"}}, ["expression"]),
    _tool("create_ticket", "Create a support ticket for a customer. Only use when the user asks for one.",
          {"customer_id": {"type": "integer"}, "subject": {"type": "string"},
           "priority": {"type": "string", "enum": ["low", "medium", "high"]},
           "order_id": {"type": "integer"}}, ["customer_id", "subject", "priority"]),
]
