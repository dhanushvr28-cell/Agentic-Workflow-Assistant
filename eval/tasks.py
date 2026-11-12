"""Evaluation tasks. Expected values are computed from the database, so they always match the seeded data."""
import re
import sqlite3

DB, POLICY, CALC, TICKET = {"query_database", "get_order_status"}, {"search_policies"}, {"calculate"}, {"create_ticket"}
NEGATIVE = r"\b(no|not|cannot|can't|can not|no longer|outside|past|expired|ineligible|isn't|unable)\b"
POSITIVE = r"\b(yes|can|eligible|within|inside|still)\b"


def numbers(text: str) -> list[float]:
    out = []
    for token in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
        try:
            out.append(float(token.replace(",", "")))
        except ValueError:
            pass
    return out


def has_number(answer: str, value: float) -> bool:
    return any(abs(n - value) <= max(0.5, abs(value) * 0.0005) for n in numbers(answer))


def has_text(answer: str, *alternatives: str) -> bool:
    return any(a.lower() in answer.lower() for a in alternatives)


def matches(answer: str, pattern: str) -> bool:
    return re.search(pattern, answer, re.I) is not None


def build_tasks(db_path: str, today: str) -> list[dict]:
    con = sqlite3.connect(db_path)
    one = lambda sql, *p: con.execute(sql, p).fetchone()

    shipped = one("SELECT COUNT(*) FROM orders WHERE status='shipped'")[0]
    delivered_total = one("SELECT SUM(total_amount) FROM orders WHERE status='delivered'")[0]
    top_cat = one("SELECT p.category FROM orders o JOIN products p ON p.id=o.product_id WHERE o.status='delivered' "
                  "GROUP BY 1 ORDER BY SUM(o.total_amount) DESC LIMIT 1")[0]
    mumbai = one("SELECT COUNT(*) FROM customers WHERE city='Mumbai'")[0]
    top_cust = one("SELECT c.id, c.name, SUM(o.total_amount) FROM orders o JOIN customers c ON c.id=o.customer_id "
                   "WHERE o.status='delivered' GROUP BY c.id ORDER BY 3 DESC LIMIT 1")
    top_prod = one("SELECT p.name FROM orders o JOIN products p ON p.id=o.product_id GROUP BY p.id "
                   "ORDER BY SUM(o.quantity) DESC LIMIT 1")[0]
    lookup = one("SELECT o.id, o.status, p.name FROM orders o JOIN products p ON p.id=o.product_id "
                 "WHERE o.status='delivered' ORDER BY o.id LIMIT 1")
    recent = one("SELECT id, total_amount FROM orders WHERE status='delivered' AND "
                 "julianday(?) - julianday(delivered_date) BETWEEN 3 AND 20 ORDER BY total_amount DESC LIMIT 1", today)
    old = one("SELECT id FROM orders WHERE status='delivered' AND julianday(?) - julianday(delivered_date) > 60 "
              "ORDER BY id LIMIT 1", today)[0]
    silver = one("SELECT customer_id, SUM(total_amount) FROM orders WHERE status='delivered' GROUP BY 1 "
                 "HAVING SUM(total_amount) BETWEEN 9000 AND 18000 ORDER BY 1 LIMIT 1")
    late = one("SELECT id, customer_id, CAST(julianday(?) - julianday(order_date) AS INTEGER) FROM orders "
               "WHERE status='shipped' AND julianday(?) - julianday(order_date) > 30 ORDER BY id LIMIT 1", today, today)
    processing = one("SELECT id FROM orders WHERE status='processing' ORDER BY id LIMIT 1")[0]
    electronics = one("SELECT SUM(o.total_amount) FROM orders o JOIN products p ON p.id=o.product_id "
                      "WHERE o.status='delivered' AND p.category='Electronics'")[0]
    cancelled_pct = 100 * one("SELECT COUNT(*) FROM orders WHERE status='cancelled'")[0] / \
        one("SELECT COUNT(*) FROM orders")[0]
    con.close()

    def ticket_created(answer: str) -> bool:
        c = sqlite3.connect(db_path)
        row = c.execute("SELECT priority FROM tickets WHERE customer_id = ? ORDER BY id DESC LIMIT 1",
                        (late[1],)).fetchone()
        c.close()
        return row is not None and row[0] == "high"

    return [
        # --- database lookups ---
        dict(id="db_count", q="How many orders are currently in 'shipped' status?", tools=[DB],
             check=lambda a: has_number(a, shipped)),
        dict(id="db_sum", q="What is the total amount of all delivered orders?", tools=[DB],
             check=lambda a: has_number(a, delivered_total)),
        dict(id="db_group", q="Which product category has the highest total sales from delivered orders?",
             tools=[DB], check=lambda a: has_text(a, top_cat)),
        dict(id="db_filter", q="How many customers are from Mumbai?", tools=[DB],
             check=lambda a: has_number(a, mumbai)),
        dict(id="db_join", q="Which customer has spent the most on delivered orders, and how much?", tools=[DB],
             check=lambda a: has_text(a, top_cust[1]) and has_number(a, top_cust[2])),
        dict(id="db_topn", q="Which product has been ordered the most by total quantity across all orders?",
             tools=[DB], check=lambda a: has_text(a, top_prod)),
        dict(id="order_lookup", q=f"What is the status of order {lookup[0]} and which product was ordered?",
             tools=[DB], check=lambda a: has_text(a, lookup[1]) and has_text(a, lookup[2])),
        dict(id="order_missing", q="What is the status of order 99999?", tools=[DB],
             check=lambda a: has_text(a, "no order", "not found", "not exist", "n't exist", "not find", "n't find",
                                      "no such", "no record", "not locate", "n't locate")),
        # --- policy questions ---
        dict(id="policy_express", q="How long does express shipping take and what does it cost?", tools=[POLICY],
             check=lambda a: has_number(a, 2) and has_number(a, 249)),
        dict(id="policy_warranty", q="How long is the warranty on furniture?", tools=[POLICY],
             check=lambda a: has_number(a, 24) or has_text(a, "two years", "2 years")),
        dict(id="policy_restock", q="What restocking fee applies to opened products that are returned?",
             tools=[POLICY], check=lambda a: has_number(a, 15)),
        dict(id="policy_cancel", q="Can a customer cancel an order that has already been shipped?", tools=[POLICY],
             check=lambda a: matches(a, NEGATIVE)),
        dict(id="policy_shipping_fee",
             q="What is the standard shipping charge for an order of 1,500 rupees, and for one of 2,500 rupees?",
             tools=[POLICY], check=lambda a: has_number(a, 99) and has_text(a, "free", "no charge", "0 rupees", "₹0")),
        # --- multi-step: data + policy (+ arithmetic) ---
        dict(id="multi_refund",
             q=f"The customer opened the product from order {recent[0]} and it works, but they want to return it. "
               "Is it still inside the return window, and how much refund would they get?",
             tools=[DB, POLICY], check=lambda a: has_number(a, round(recent[1] * 0.85, 2))),
        dict(id="multi_return_expired", q=f"Is order {old} still eligible for a return?", tools=[DB, POLICY],
             check=lambda a: matches(a, NEGATIVE)),
        dict(id="multi_loyalty_gold",
             q=f"Which loyalty tier is customer {top_cust[0]} in, and what discount do they get?",
             tools=[DB, POLICY], check=lambda a: has_text(a, "gold") and has_number(a, 10)),
        dict(id="multi_loyalty_silver",
             q=f"Which loyalty tier is customer {silver[0]} in, and what discount do they get?",
             tools=[DB, POLICY], check=lambda a: has_text(a, "silver") and has_number(a, 5)),
        dict(id="multi_delayed",
             q=f"Is order {late[0]} delayed under our shipping policy, and how many days ago was it placed?",
             tools=[DB, POLICY], check=lambda a: has_number(a, late[2]) and has_text(a, "delayed", "yes")),
        dict(id="multi_address", q=f"Can the shipping address of order {processing} still be changed?",
             tools=[DB, POLICY], check=lambda a: matches(a, POSITIVE) and not has_text(a, "cannot", "can't", "can not")),
        dict(id="multi_calc", q="What is 12% of the total revenue from delivered Electronics orders?",
             tools=[DB, CALC], check=lambda a: has_number(a, round(electronics * 0.12, 2))),
        dict(id="multi_percent", q="What percentage of all orders were cancelled?", tools=[DB],
             check=lambda a: any(abs(n - cancelled_pct) <= 0.06 for n in numbers(a))),
        # --- action ---
        dict(id="action_ticket",
             q=f"Order {late[0]} still has not arrived. Check whether it is delayed under our policy and, if it is, "
               f"create a support ticket for customer {late[1]} with the priority the policy requires.",
             tools=[DB, POLICY, TICKET], check=ticket_created),
    ]
