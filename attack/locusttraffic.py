"""
locusttraffic.py — Locust-based normal traffic generator for WebTrap false positive evaluation.


Usage:
  pip install locust
  locust -f attack/locusttraffic.py --headless -u 3 -r 1 --run-time 6m \
         --host http://localhost:8700

"""

import random
from locust import HttpUser, task, between


# Fixed IDs used in URL parameters — representative values, not exhaustive
PRODUCT_IDS  = [1, 2, 3, 4, 5]
CATEGORY_IDS = [1, 2, 3]
USER_IDS     = [1, 2, 3, 4]


def _pid():
    return random.choice(PRODUCT_IDS)

def _cid():
    return random.choice(CATEGORY_IDS)

def _uid():
    return random.choice(USER_IDS)


class NormalUser(HttpUser):
    """
    Simulates a legitimate e-commerce user navigating the application.
    Only real endpoints are requested — no canary or mitigation URLs.
    wait_time models think time between requests (1–3 seconds).
    """
    wait_time = between(2, 5)

    # ── Low-impact endpoints (high frequency) ─────────────────────────────────

    @task(8)
    def ping(self):
        self.client.get("/ping", name="/ping")

    @task(7)
    def category_name(self):
        self.client.get(f"/category/{_cid()}/name", name="/category/{id}/name")

    @task(5)
    def product_name(self):
        self.client.get(f"/product/{_pid()}/name", name="/product/{id}/name")

    @task(4)
    def user_name(self):
        self.client.get(f"/user/{_uid()}/name", name="/user/{id}/name")

    # ── Medium-impact endpoints (moderate frequency) ───────────────────────────

    @task(4)
    def category_products(self):
        self.client.get(f"/category/{_cid()}/products", name="/category/{id}/products")

    @task(4)
    def product_details(self):
        self.client.get(f"/product/{_pid()}/details", name="/product/{id}/details")

    @task(3)
    def cart_items(self):
        self.client.get(f"/cart/{_uid()}/items", name="/cart/{id}/items")

    @task(2)
    def recent_orders(self):
        self.client.get(f"/user/{_uid()}/recent-orders", name="/user/{id}/recent-orders")

    # ── Heavy endpoint (very low frequency) ───────────────────────────────────

    @task(1)
    def all_orders(self):
        self.client.get(f"/user/{_uid()}/orders/all", name="/user/{id}/orders/all")

    # /search/products/full, /export/*, /analytics/* excluded —
    # admin-only or not reachable via normal application navigation.
