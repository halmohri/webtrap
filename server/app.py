import json
import re
import time
import yaml
from pathlib import Path
from flask import Flask, request, jsonify, abort
from driver import Driver
import reqlog

app = Flask(__name__)
db = Driver()

CONFIGS_DIR      = Path(__file__).resolve().parent.parent / "configs"
ENDPOINTS_FILE   = CONFIGS_DIR / "endpoints.yaml"
CACHE_TTL_MINUTES = 30
MITIGATION_STATE = CONFIGS_DIR / "mitigations_state.json"

_endpoints_cache = None
_cache_loaded_at = 0.0


def _endpoints():
    global _endpoints_cache, _cache_loaded_at
    if _endpoints_cache is None or (time.time() - _cache_loaded_at) > CACHE_TTL_MINUTES * 60:
        with open(ENDPOINTS_FILE) as f:
            _endpoints_cache = yaml.safe_load(f)
        _cache_loaded_at = time.time()
    return _endpoints_cache


def _is_mitigation_active(url):
    try:
        with open(MITIGATION_STATE) as f:
            return json.load(f).get(url, False)
    except Exception:
        return False


def _normalize(path):
    """Replace numeric path segments with {id} for per-route aggregation."""
    return re.sub(r"/\d+", "/{id}", path)


# --- Timing middleware ---

@app.before_request
def _start_timer():
    request._start = time.time()

def _endpoint_kind(path):
    # determine if path is a mitigation decoy, canary, or real endpoint
    if path.startswith("/canary/"):
        norm = _normalize(path)
        data = _endpoints()
        mitigation_urls = {e["url"].split("?")[0] for e in data.get("endpoints", []) if e.get("kind") == "mitigation"}
        if any(path == u or norm == _normalize(u) for u in mitigation_urls):
            return reqlog.MITIGATION
        return reqlog.CANARY
    return reqlog.REAL


@app.after_request
def _record_time(response):
    elapsed_ms = (time.time() - request._start) * 1000
    kind = _endpoint_kind(request.path)
    if kind == reqlog.REAL:
        db.record_response_time(_normalize(request.path), elapsed_ms)
    reqlog.log_request(_normalize(request.path), elapsed_ms, kind)
    return response


# --- Low Impact ---

@app.route("/ping")
def ping():
    return jsonify(db.ping())

@app.route("/product/<int:product_id>/name")
def get_product_name(product_id):
    return jsonify(db.get_product_name(product_id))

@app.route("/category/<int:category_id>/name")
def get_category_name(category_id):
    return jsonify(db.get_category_name(category_id))

@app.route("/user/<int:user_id>/name")
def get_user_name(user_id):
    return jsonify(db.get_user_name(user_id))


# --- Medium Impact ---

@app.route("/product/<int:product_id>/details")
def get_product_details(product_id):
    return jsonify(db.get_product_details(product_id))

@app.route("/user/<int:user_id>/recent-orders")
def get_recent_orders(user_id):
    return jsonify(db.get_recent_orders(user_id))

@app.route("/cart/<int:user_id>/items")
def get_cart_items(user_id):
    return jsonify(db.get_cart_items(user_id))

@app.route("/category/<int:category_id>/products")
def get_category_products(category_id):
    return jsonify(db.get_category_products(category_id))


# --- High Impact ---

@app.route("/user/<int:user_id>/orders/all")
def get_all_orders(user_id):
    return jsonify(db.get_all_orders(user_id))

@app.route("/analytics/sales/range")
def sales_analytics_range():
    start = request.args.get("start", "2000-01-01")
    end = request.args.get("end", "2099-12-31")
    return jsonify(db.sales_analytics_range(start, end))

@app.route("/export/products/full")
def export_products_full():
    return jsonify(db.export_products_full())

@app.route("/search/products/full")
def search_products_full():
    query = request.args.get("q", "")
    return jsonify(db.search_products_full(query))


# --- Canary decoys (always active) ---

def _canary(mirrors):
    key = _normalize(mirrors)
    avg = db.get_avg_ms(key)
    time.sleep(avg / 1000)
    try:
        reqlog.record(key, avg, reqlog.CANARY)
    except Exception:
        pass
    return jsonify({"canary": True, "mirroring": key, "avg_ms": avg})

@app.route("/canary/ping")
def canary_ping():
    return _canary("/ping")

@app.route("/canary/product/<int:product_id>/name")
def canary_product_name(product_id):
    return _canary("/product/{id}/name")

@app.route("/canary/category/<int:category_id>/name")
def canary_category_name(category_id):
    return _canary("/category/{id}/name")

@app.route("/canary/user/<int:user_id>/name")
def canary_user_name(user_id):
    return _canary("/user/{id}/name")

@app.route("/canary/product/<int:product_id>/details")
def canary_product_details(product_id):
    return _canary("/product/{id}/details")

@app.route("/canary/user/<int:user_id>/recent-orders")
def canary_recent_orders(user_id):
    return _canary("/user/{id}/recent-orders")

@app.route("/canary/cart/<int:user_id>/items")
def canary_cart_items(user_id):
    return _canary("/cart/{id}/items")

@app.route("/canary/category/<int:category_id>/products")
def canary_category_products(category_id):
    return _canary("/category/{id}/products")

@app.route("/canary/user/<int:user_id>/orders/all")
def canary_all_orders(user_id):
    return _canary("/user/{id}/orders/all")

@app.route("/canary/analytics/sales/range")
def canary_sales_analytics():
    return _canary("/analytics/sales/range")

@app.route("/canary/export/products/full")
def canary_export_products():
    return _canary("/export/products/full")

@app.route("/canary/search/products/full")
def canary_search_products():
    return _canary("/search/products/full")


# --- Mitigation decoys (inactive by default, toggled via endpoints.yaml) ---

def _mitigation(url, mirrors):
    if not _is_mitigation_active(url):
        abort(404)
    return _canary(mirrors)

# /ping
@app.route("/canary/status")
def mitigation_status():
    return _mitigation("/canary/status", "/ping")

@app.route("/canary/health")
def mitigation_health():
    return _mitigation("/canary/health", "/ping")

@app.route("/canary/heartbeat")
def mitigation_heartbeat():
    return _mitigation("/canary/heartbeat", "/ping")

# /product/{id}/name
@app.route("/canary/product/1/name")
def mitigation_product_1_name():
    return _mitigation("/canary/product/1/name", "/product/{id}/name")

@app.route("/canary/product/2/name")
def mitigation_product_2_name():
    return _mitigation("/canary/product/2/name", "/product/{id}/name")

@app.route("/canary/product/3/name")
def mitigation_product_3_name():
    return _mitigation("/canary/product/3/name", "/product/{id}/name")

# /category/{id}/name
@app.route("/canary/category/1/name")
def mitigation_category_1_name():
    return _mitigation("/canary/category/1/name", "/category/{id}/name")

@app.route("/canary/category/2/name")
def mitigation_category_2_name():
    return _mitigation("/canary/category/2/name", "/category/{id}/name")

@app.route("/canary/category/3/name")
def mitigation_category_3_name():
    return _mitigation("/canary/category/3/name", "/category/{id}/name")

# /user/{id}/name
@app.route("/canary/user/1/name")
def mitigation_user_1_name():
    return _mitigation("/canary/user/1/name", "/user/{id}/name")

@app.route("/canary/user/2/name")
def mitigation_user_2_name():
    return _mitigation("/canary/user/2/name", "/user/{id}/name")

@app.route("/canary/user/3/name")
def mitigation_user_3_name():
    return _mitigation("/canary/user/3/name", "/user/{id}/name")

# /product/{id}/details
@app.route("/canary/product/1/details")
def mitigation_product_1_details():
    return _mitigation("/canary/product/1/details", "/product/{id}/details")

@app.route("/canary/product/2/details")
def mitigation_product_2_details():
    return _mitigation("/canary/product/2/details", "/product/{id}/details")

@app.route("/canary/product/3/details")
def mitigation_product_3_details():
    return _mitigation("/canary/product/3/details", "/product/{id}/details")

# /user/{id}/recent-orders
@app.route("/canary/user/1/recent-orders")
def mitigation_user_1_recent_orders():
    return _mitigation("/canary/user/1/recent-orders", "/user/{id}/recent-orders")

@app.route("/canary/user/2/recent-orders")
def mitigation_user_2_recent_orders():
    return _mitigation("/canary/user/2/recent-orders", "/user/{id}/recent-orders")

@app.route("/canary/user/3/recent-orders")
def mitigation_user_3_recent_orders():
    return _mitigation("/canary/user/3/recent-orders", "/user/{id}/recent-orders")

# /cart/{id}/items
@app.route("/canary/cart/1/items")
def mitigation_cart_1_items():
    return _mitigation("/canary/cart/1/items", "/cart/{id}/items")

@app.route("/canary/cart/2/items")
def mitigation_cart_2_items():
    return _mitigation("/canary/cart/2/items", "/cart/{id}/items")

@app.route("/canary/cart/3/items")
def mitigation_cart_3_items():
    return _mitigation("/canary/cart/3/items", "/cart/{id}/items")

# /category/{id}/products
@app.route("/canary/category/1/products")
def mitigation_category_1_products():
    return _mitigation("/canary/category/1/products", "/category/{id}/products")

@app.route("/canary/category/2/products")
def mitigation_category_2_products():
    return _mitigation("/canary/category/2/products", "/category/{id}/products")

@app.route("/canary/category/3/products")
def mitigation_category_3_products():
    return _mitigation("/canary/category/3/products", "/category/{id}/products")

# /user/{id}/orders/all
@app.route("/canary/user/1/orders/all")
def mitigation_user_1_orders_all():
    return _mitigation("/canary/user/1/orders/all", "/user/{id}/orders/all")

@app.route("/canary/user/2/orders/all")
def mitigation_user_2_orders_all():
    return _mitigation("/canary/user/2/orders/all", "/user/{id}/orders/all")

@app.route("/canary/user/3/orders/all")
def mitigation_user_3_orders_all():
    return _mitigation("/canary/user/3/orders/all", "/user/{id}/orders/all")

# /analytics/sales/range
@app.route("/canary/analytics/sales/range/2023")
def mitigation_sales_2023():
    return _mitigation("/canary/analytics/sales/range?start=2023-01-01&end=2023-12-31", "/analytics/sales/range")

@app.route("/canary/analytics/sales/range/2024")
def mitigation_sales_2024():
    return _mitigation("/canary/analytics/sales/range?start=2024-01-01&end=2024-12-31", "/analytics/sales/range")

@app.route("/canary/analytics/sales/range/all")
def mitigation_sales_all():
    return _mitigation("/canary/analytics/sales/range?start=2022-01-01&end=2025-12-31", "/analytics/sales/range")

# /export/products/full
@app.route("/canary/export/catalog/full")
def mitigation_export_catalog():
    return _mitigation("/canary/export/catalog/full", "/export/products/full")

@app.route("/canary/export/inventory/full")
def mitigation_export_inventory():
    return _mitigation("/canary/export/inventory/full", "/export/products/full")

@app.route("/canary/export/listings/full")
def mitigation_export_listings():
    return _mitigation("/canary/export/listings/full", "/export/products/full")

# /search/products/full
@app.route("/canary/search/products/full/a")
def mitigation_search_a():
    return _mitigation("/canary/search/products/full?q=a", "/search/products/full")

@app.route("/canary/search/products/full/e")
def mitigation_search_e():
    return _mitigation("/canary/search/products/full?q=e", "/search/products/full")

@app.route("/canary/search/products/full/pro")
def mitigation_search_pro():
    return _mitigation("/canary/search/products/full?q=pro", "/search/products/full")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8700, threaded=True)
