"""Create the demo e-commerce database with reproducible synthetic data.

Usage:  python -m agent.seed
"""
import os
import random
import sqlite3
from datetime import date, timedelta

SCHEMA = """
CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, email TEXT, city TEXT, joined_date TEXT);
CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, category TEXT, price REAL);
CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id),
    product_id INTEGER REFERENCES products(id), quantity INTEGER, total_amount REAL,
    status TEXT, order_date TEXT, delivered_date TEXT);
CREATE TABLE tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER REFERENCES customers(id),
    order_id INTEGER, subject TEXT, priority TEXT, status TEXT DEFAULT 'open', created_at TEXT);
"""
SCHEMA_DESCRIPTION = """customers(id, name, email, city, joined_date)
products(id, name, category ['Electronics','Accessories','Furniture'], price)
orders(id, customer_id, product_id, quantity, total_amount, status ['processing','shipped','delivered','cancelled','returned'], order_date, delivered_date)
tickets(id, customer_id, order_id, subject, priority ['low','medium','high'], status, created_at)
Dates are ISO strings (YYYY-MM-DD). total_amount = price * quantity, in rupees."""

FIRST = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Sana", "Vikram", "Ananya", "Arjun", "Isha", "Nikhil", "Priya"]
LAST = ["Sharma", "Iyer", "Khan", "Patel", "Reddy", "Das", "Nair", "Singh"]
CITIES = ["Chennai", "Coimbatore", "Bengaluru", "Mumbai", "Delhi", "Hyderabad", "Pune", "Kochi"]
PRODUCTS = [
    ("Wireless Headphones", "Electronics", 3499), ("Smart Watch", "Electronics", 5999),
    ("Bluetooth Speaker", "Electronics", 2499), ("Mechanical Keyboard", "Electronics", 4299),
    ("Webcam HD", "Electronics", 1899), ("Phone Case", "Accessories", 399), ("USB-C Cable", "Accessories", 299),
    ("Laptop Sleeve", "Accessories", 899), ("Screen Protector", "Accessories", 249),
    ("Office Chair", "Furniture", 8999), ("Study Desk", "Furniture", 6499), ("Bookshelf", "Furniture", 3999),
]


def seed(db_path: str, reference_date: str = "2026-11-01", n_customers: int = 40, n_orders: int = 220,
         seed_value: int = 42) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)
    rng = random.Random(seed_value)
    today = date.fromisoformat(reference_date)
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    for i in range(1, n_customers + 1):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        con.execute("INSERT INTO customers VALUES (?,?,?,?,?)",
                    (i, f"{first} {last}", f"{first.lower()}.{last.lower()}{i}@example.com", rng.choice(CITIES),
                     (today - timedelta(days=rng.randint(200, 900))).isoformat()))
    con.executemany("INSERT INTO products VALUES (?,?,?,?)",
                    [(i, name, cat, price) for i, (name, cat, price) in enumerate(PRODUCTS, start=1)])
    for i in range(1, n_orders + 1):
        product_id = rng.randint(1, len(PRODUCTS))
        quantity = rng.choice([1, 1, 1, 2, 2, 3])
        order_day = today - timedelta(days=rng.randint(1, 180))
        age = (today - order_day).days
        if age <= 3:
            status = "processing"
        elif age <= 8:
            status = rng.choice(["shipped", "shipped", "processing"])
        else:
            status = rng.choices(["delivered", "cancelled", "returned", "shipped"], weights=[78, 8, 8, 6])[0]
        delivered = None
        if status in ("delivered", "returned"):
            delivered = (order_day + timedelta(days=rng.randint(2, 8))).isoformat()
        con.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?)",
                    (i, rng.randint(1, n_customers), product_id, quantity, PRODUCTS[product_id - 1][2] * quantity,
                     status, order_day.isoformat(), delivered))
    con.commit()
    con.close()


if __name__ == "__main__":
    from .config import get_settings

    s = get_settings()
    seed(s.db_path, s.reference_date)
    print(f"Seeded {s.db_path}")
