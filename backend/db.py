"""
db.py — SQLite schema setup and optional data bootstrapping.

Usage:
  python db.py                        # create schema only (no data)
  python db.py --seed 1000            # create schema + seed with 1000 users worth of data
  python db.py --recreate             # drop and recreate schema (no data)
  python db.py --recreate --seed 500  # drop, recreate, and seed
"""

import argparse
import random
import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = "shop.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    price       REAL NOT NULL,
    stock       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS users (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    email    TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    status     TEXT NOT NULL DEFAULT 'completed',
    created_at TEXT NOT NULL,
    total      REAL NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS order_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id   INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity   INTEGER NOT NULL,
    unit_price REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS carts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS response_times (
    endpoint    TEXT PRIMARY KEY,
    avg_ms      REAL NOT NULL DEFAULT 0.0,
    n_samples   INTEGER NOT NULL DEFAULT 0
);
"""

CATEGORY_NAMES = [
    "Electronics", "Clothing", "Books", "Home & Garden",
    "Sports", "Toys", "Food & Grocery", "Automotive"
]

PRODUCT_ADJECTIVES = ["Premium", "Budget", "Classic", "Modern", "Deluxe", "Basic", "Pro", "Lite"]
PRODUCT_NOUNS = ["Widget", "Gadget", "Device", "Item", "Unit", "Pack", "Set", "Kit"]

ORDER_STATUSES = ["completed", "completed", "completed", "shipped", "pending", "cancelled"]


def connect(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def drop_db(path):
    if os.path.exists(path):
        os.remove(path)
        print(f"Dropped {path}")


def create_schema(conn):
    conn.executescript(SCHEMA)
    conn.commit()
    print("Schema created.")


def random_date(start_days_ago=730):
    delta = timedelta(days=random.randint(0, start_days_ago),
                      hours=random.randint(0, 23),
                      minutes=random.randint(0, 59))
    return (datetime.now() - delta).strftime("%Y-%m-%d %H:%M:%S")


def seed(conn, n_users):
    cur = conn.cursor()

    # Categories
    cur.executemany("INSERT OR IGNORE INTO categories (name) VALUES (?)",
                    [(c,) for c in CATEGORY_NAMES])
    conn.commit()
    category_ids = [r[0] for r in cur.execute("SELECT id FROM categories").fetchall()]

    # Products: ~10 per category
    products = []
    for cat_id in category_ids:
        for _ in range(10):
            name = f"{random.choice(PRODUCT_ADJECTIVES)} {random.choice(PRODUCT_NOUNS)}"
            price = round(random.uniform(5.0, 500.0), 2)
            stock = random.randint(0, 200)
            products.append((name, cat_id, price, stock))
    cur.executemany("INSERT INTO products (name, category_id, price, stock) VALUES (?,?,?,?)", products)
    conn.commit()
    product_ids = [r[0] for r in cur.execute("SELECT id FROM products").fetchall()]
    product_prices = {r[0]: r[1] for r in cur.execute("SELECT id, price FROM products").fetchall()}

    # Users
    users = []
    for i in range(1, n_users + 1):
        username = f"user_{i}"
        email = f"user_{i}@example.com"
        created_at = random_date(1460)
        users.append((username, email, created_at))
    cur.executemany("INSERT INTO users (username, email, created_at) VALUES (?,?,?)", users)
    conn.commit()
    user_ids = [r[0] for r in cur.execute("SELECT id FROM users").fetchall()]

    # Orders + order items: avg 5 orders per user, 1-5 items each
    orders = []
    order_items = []
    for user_id in user_ids:
        n_orders = random.randint(1, 10)
        for _ in range(n_orders):
            created_at = random_date(730)
            status = random.choice(ORDER_STATUSES)
            orders.append((user_id, status, created_at))

    cur.executemany("INSERT INTO orders (user_id, status, created_at, total) VALUES (?,?,?,0.0)", orders)
    conn.commit()
    order_ids = [r[0] for r in cur.execute("SELECT id FROM orders").fetchall()]

    for order_id in order_ids:
        n_items = random.randint(1, 5)
        chosen = random.sample(product_ids, min(n_items, len(product_ids)))
        total = 0.0
        for pid in chosen:
            qty = random.randint(1, 4)
            unit_price = product_prices[pid]
            order_items.append((order_id, pid, qty, unit_price))
            total += qty * unit_price
        cur.execute("UPDATE orders SET total=? WHERE id=?", (round(total, 2), order_id))

    cur.executemany("INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (?,?,?,?)", order_items)
    conn.commit()

    # Carts: ~30% of users have items in their cart
    carts = []
    for user_id in random.sample(user_ids, k=max(1, len(user_ids) // 3)):
        n_items = random.randint(1, 4)
        for pid in random.sample(product_ids, min(n_items, len(product_ids))):
            carts.append((user_id, pid, random.randint(1, 3)))
    cur.executemany("INSERT INTO carts (user_id, product_id, quantity) VALUES (?,?,?)", carts)
    conn.commit()

    print(f"Seeded: {len(category_ids)} categories, {len(products)} products, "
          f"{n_users} users, {len(order_ids)} orders, {len(order_items)} order items, "
          f"{len(carts)} cart entries.")


def main():
    parser = argparse.ArgumentParser(description="Set up the shop SQLite database.")
    parser.add_argument("--db", default=DB_PATH, help="Path to the SQLite file (default: shop.db)")
    parser.add_argument("--recreate", action="store_true", help="Drop and recreate the database")
    parser.add_argument("--seed", type=int, metavar="N", help="Seed with N users worth of randomized data")
    args = parser.parse_args()

    if args.recreate:
        drop_db(args.db)

    conn = connect(args.db)
    create_schema(conn)

    if args.seed:
        seed(conn, args.seed)

    conn.close()


if __name__ == "__main__":
    main()
