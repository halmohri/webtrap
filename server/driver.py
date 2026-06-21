import random
import math

# ---------------------------------------------------------------------------
# Simulated load parameters per impact tier
# ---------------------------------------------------------------------------
#   low:    tiny CPU work, negligible memory, fast return
#   medium: moderate CPU loop + small allocation, noticeable but bounded
#   high:   expensive CPU loop + large allocation, visible system pressure
#
# MEDIUM_AMPLIFICATION: multiplier for medium-impact endpoints (default 1.0).
# HIGH_AMPLIFICATION: multiplier for high-impact endpoints.
# Increase both on a t3.small to stretch response times into seconds/minutes.
# ---------------------------------------------------------------------------

LOW_AMPLIFICATION    = 1.0
MEDIUM_AMPLIFICATION = .2
HIGH_AMPLIFICATION   = 1.0
CPU_BURN_SCALE       = 1.0  # global scale: 1.0=default, 0.5=half load, 2.0=double
_CPU_BURN_BASE       = 10_000


def _noise(base, rel=0.15):
    """Return base value with ±rel relative Gaussian noise."""
    return max(0, base * (1 + random.gauss(0, rel)))


def _burn_cpu(iterations):
    """Pure-Python LCG loop — fully GIL-bound, one core per thread saturates."""
    x = 1
    for _ in range(max(1, int(iterations * _CPU_BURN_BASE * CPU_BURN_SCALE))):
        x = (x * 1103515245 + 12345) & 0x7FFFFFFF
    return x


def _burn_mem(mb):
    """Allocate, write, and read ~mb megabytes of data."""
    chunk = bytearray(mb * 1024 * 1024)
    for i in range(0, len(chunk), 4096):
        chunk[i] = i & 0xFF
    total = sum(chunk[i] for i in range(0, len(chunk), 4096))
    return total


class Driver:

    # --- Low impact: negligible work, small static response ---

    def ping(self):
        _burn_cpu(int(_noise(5 * LOW_AMPLIFICATION)))
        return {"pong": True}

    def get_product_name(self, product_id):
        _burn_cpu(int(_noise(8 * LOW_AMPLIFICATION)))
        return {"id": product_id, "name": f"Product {product_id}"}

    def get_category_name(self, category_id):
        _burn_cpu(int(_noise(6 * LOW_AMPLIFICATION)))
        return {"id": category_id, "name": f"Category {category_id}"}

    def get_user_name(self, user_id):
        _burn_cpu(int(_noise(7 * LOW_AMPLIFICATION)))
        return {"id": user_id, "username": f"user_{user_id}"}

    # --- Medium impact: moderate CPU + small allocation ---

    def get_product_details(self, product_id):
        _burn_cpu(int(_noise(20_000 * MEDIUM_AMPLIFICATION)))
        _burn_mem(int(_noise(4)))
        return {
            "id": product_id, "name": f"Product {product_id}",
            "price": round(_noise(49.99), 2), "stock": int(_noise(100)),
            "category": "Electronics"
        }

    def get_recent_orders(self, user_id):
        _burn_cpu(int(_noise(30_000 * MEDIUM_AMPLIFICATION)))
        _burn_mem(int(_noise(6)))
        return [{"order_id": i, "total": round(_noise(120.0), 2)} for i in range(10)]

    def get_cart_items(self, user_id):
        _burn_cpu(int(_noise(25_000 * MEDIUM_AMPLIFICATION)))
        _burn_mem(int(_noise(4)))
        return [{"product": f"Item {i}", "qty": random.randint(1, 3), "price": round(_noise(30.0), 2)}
                for i in range(random.randint(2, 8))]

    def get_category_products(self, category_id):
        _burn_cpu(int(_noise(35_000 * MEDIUM_AMPLIFICATION)))
        _burn_mem(int(_noise(8)))
        return [{"id": i, "name": f"Product {i}", "price": round(_noise(60.0), 2)}
                for i in range(20)]

    # --- High impact: expensive CPU loop + large memory allocation ---

    def get_all_orders(self, user_id):
        _burn_cpu(int(_noise(14_000 * HIGH_AMPLIFICATION)))
        _burn_mem(int(_noise(80)))
        return [{"order_id": i, "total": round(_noise(200.0), 2), "items": random.randint(1, 10)}
                for i in range(int(_noise(200)))]

    def sales_analytics_range(self, start, end):
        _burn_cpu(int(_noise(20_000 * HIGH_AMPLIFICATION)))
        _burn_mem(int(_noise(120)))
        return [{"day": f"2024-{m:02d}-01", "revenue": round(_noise(5000.0), 2), "n_orders": int(_noise(50))}
                for m in range(1, 13)]

    def export_products_full(self):
        _burn_cpu(int(_noise(16_000 * HIGH_AMPLIFICATION)))
        _burn_mem(int(_noise(150)))
        return [{"id": i, "name": f"Product {i}", "price": round(_noise(75.0), 2),
                 "stock": int(_noise(100)), "category": f"Category {i % 8}"}
                for i in range(int(_noise(500)))]

    def search_products_full(self, query):
        _burn_cpu(int(_noise(18_000 * HIGH_AMPLIFICATION)))
        _burn_mem(int(_noise(100)))
        return [{"id": i, "name": f"Product matching '{query}' #{i}", "price": round(_noise(55.0), 2)}
                for i in range(int(_noise(300)))]

    # --- Response time tracking (in-memory, no DB) ---

    _rt: dict = {}

    def record_response_time(self, endpoint, elapsed_ms):
        if endpoint not in self._rt:
            self._rt[endpoint] = {"avg_ms": elapsed_ms, "n": 1}
        else:
            e = self._rt[endpoint]
            e["avg_ms"] = (e["avg_ms"] * e["n"] + elapsed_ms) / (e["n"] + 1)
            e["n"] += 1

    def get_avg_ms(self, endpoint):
        return self._rt.get(endpoint, {}).get("avg_ms", 0.0)
