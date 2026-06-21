import sqlite3

DB_PATH = "../backend/shop.db"


class Driver:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path

    def _conn(self):
        return sqlite3.connect(self.db_path)

    # --- Low impact ---

    def ping(self):
        return {"pong": True}

    def get_product_name(self, product_id):
        with self._conn() as c:
            return c.execute("SELECT name FROM products WHERE id=?", (product_id,)).fetchone()

    def get_category_name(self, category_id):
        with self._conn() as c:
            return c.execute("SELECT name FROM categories WHERE id=?", (category_id,)).fetchone()

    def get_user_name(self, user_id):
        with self._conn() as c:
            return c.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()

    # --- Medium impact ---

    def get_product_details(self, product_id):
        with self._conn() as c:
            return c.execute(
                "SELECT p.id, p.name, p.price, p.stock, c.name as category "
                "FROM products p JOIN categories c ON p.category_id=c.id WHERE p.id=?",
                (product_id,)
            ).fetchone()

    def get_recent_orders(self, user_id):
        with self._conn() as c:
            return c.execute(
                "SELECT id, status, created_at, total FROM orders "
                "WHERE user_id=? ORDER BY created_at DESC LIMIT 10",
                (user_id,)
            ).fetchall()

    def get_cart_items(self, user_id):
        with self._conn() as c:
            return c.execute(
                "SELECT p.name, ca.quantity, p.price FROM carts ca "
                "JOIN products p ON ca.product_id=p.id WHERE ca.user_id=?",
                (user_id,)
            ).fetchall()

    def get_category_products(self, category_id):
        with self._conn() as c:
            return c.execute(
                "SELECT id, name, price FROM products WHERE category_id=? LIMIT 20",
                (category_id,)
            ).fetchall()

    # --- High impact ---

    def get_all_orders(self, user_id):
        with self._conn() as c:
            return c.execute(
                "SELECT o.id, o.created_at, o.total, oi.product_id, oi.quantity, oi.unit_price "
                "FROM orders o JOIN order_items oi ON o.id=oi.order_id WHERE o.user_id=?",
                (user_id,)
            ).fetchall()

    def sales_analytics_range(self, start, end):
        with self._conn() as c:
            return c.execute(
                "SELECT DATE(created_at) as day, SUM(total) as revenue, COUNT(*) as n_orders "
                "FROM orders WHERE created_at BETWEEN ? AND ? GROUP BY day ORDER BY day",
                (start, end)
            ).fetchall()

    def export_products_full(self):
        with self._conn() as c:
            return c.execute(
                "SELECT p.id, p.name, p.price, p.stock, c.name as category "
                "FROM products p JOIN categories c ON p.category_id=c.id"
            ).fetchall()

    def search_products_full(self, query):
        with self._conn() as c:
            return c.execute(
                "SELECT id, name, price FROM products WHERE name LIKE ?",
                (f"%{query}%",)
            ).fetchall()

    # --- Response time tracking ---

    def record_response_time(self, endpoint, elapsed_ms):
        with self._conn() as c:
            c.execute(
                "INSERT INTO response_times (endpoint, avg_ms, n_samples) VALUES (?, ?, 1) "
                "ON CONFLICT(endpoint) DO UPDATE SET "
                "avg_ms = (avg_ms * n_samples + excluded.avg_ms) / (n_samples + 1), "
                "n_samples = n_samples + 1",
                (endpoint, elapsed_ms)
            )

    def get_avg_ms(self, endpoint):
        with self._conn() as c:
            row = c.execute(
                "SELECT avg_ms FROM response_times WHERE endpoint=?", (endpoint,)
            ).fetchone()
            return row[0] if row else 0.0
