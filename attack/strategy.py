import random
import math
from abc import ABC, abstractmethod


class AttackStrategy(ABC):

    def __init__(self, endpoints):
        """
        endpoints: list of dicts loaded from endpoints.yaml
        """
        self.endpoints = endpoints

    @abstractmethod
    def next_endpoint(self) -> dict:
        """Select and return the next endpoint to attack."""
        pass

    def on_response(self, endpoint: dict, elapsed_ms: float):
        """
        Called after each request with the observed response time.
        Subclasses may use this to update internal state.
        """
        pass


class NormalTraffic(AttackStrategy):
    """Uniform random sampling across all endpoints — models balanced legitimate traffic."""

    def next_endpoint(self) -> dict:
        return random.choice(self.endpoints)


class NaiveAttack(AttackStrategy):
    """Sample endpoints proportional to vulnerability_score**p (p>1 emphasizes heavy endpoints)."""

    def __init__(self, endpoints, p=1.0):
        super().__init__(endpoints)
        self.p = p

    def next_endpoint(self) -> dict:
        total = sum(e.get("vulnerability_score", 0) ** self.p for e in self.endpoints)
        r = random.random() * total
        for e in self.endpoints:
            r -= e.get("vulnerability_score", 0) ** self.p
            if r <= 0:
                return e
        return self.endpoints[-1]


class StealthAttack(AttackStrategy):
    """Gaussian-kernel weighting with T/S cycling (mirrors simulator stealth)."""

    def __init__(self, endpoints, h=0.25):
        super().__init__(endpoints)
        self.h = h
        self.T = list(endpoints)
        self.S = []

    def next_endpoint(self) -> dict:
        if not self.T:
            self.T, self.S = list(self.S), []
        weights = [
            math.exp(-((e.get("vulnerability_score", 0) - 0.5) ** 2) / (2 * self.h ** 2))
            for e in self.T
        ]
        total = sum(weights)
        r = random.random() * total
        chosen = self.T[-1]
        for e, w in zip(self.T, weights):
            r -= w
            if r <= 0:
                chosen = e
                break
        self.T.remove(chosen)
        self.S.append(chosen)
        return chosen


class OptimizerAttack(AttackStrategy):
    """
    Burst/cooldown reactive policy.

    Operates in two alternating phases:
      Aggressive: hammer the highest-scoring endpoints (weighted by visit count
                  to spread load across them) until G seconds of response time
                  have accumulated in this burst.
      Cooldown:   send C_STEPS requests to low/medium endpoints to let the
                  server recover and avoid sustained detection, then reset for
                  the next aggressive burst.

    G=30s and C_STEPS=5 gives ~85% of requests on heavy endpoints across a
    6-minute run, which is enough to drive health well above 0.6.
    """

    def __init__(self, endpoints, G=30.0, C_STEPS=5):
        super().__init__(endpoints)
        self.G       = G
        self.C_STEPS = C_STEPS
        self.n_tau        = {}
        self.accumulator  = 0.0
        self.cooldown_left = 0

    def next_endpoint(self) -> dict:
        if self.cooldown_left > 0:
            # Cooldown: pick medium endpoints to avoid total idleness
            medium = [e for e in self.endpoints
                      if 0.3 <= e.get("vulnerability_score", 0) <= 0.6]
            chosen = random.choice(medium) if medium else random.choice(self.endpoints)
            self.cooldown_left -= 1
        else:
            # Aggressive: pick highest-scoring endpoint weighted by visit frequency
            chosen = max(self.endpoints, key=lambda e:
                         e.get("vulnerability_score", 0) / (1 + self.n_tau.get(e["url"], 0)))
        self.n_tau[chosen["url"]] = self.n_tau.get(chosen["url"], 0) + 1
        return chosen

    def on_response(self, endpoint: dict, elapsed_ms: float):
        if self.cooldown_left > 0:
            return
        if elapsed_ms >= 0:
            self.accumulator += elapsed_ms / 1000.0
        if self.accumulator >= self.G:
            self.accumulator  = 0.0
            self.cooldown_left = self.C_STEPS


class MarkovTraffic(AttackStrategy):
    """
    Session-based normal traffic using a Markov chain navigation model.

    Only real endpoints are used — canary and mitigation URLs are excluded
    entirely, modelling a legitimate user who navigates via application links
    and never discovers non-linked endpoints.

    Navigation graph (e-commerce session model):
      START  -> /ping, /category/{}/name, /product/{}/name  (entry points)
      browse -> /product/{}/name, /category/{}/products, /user/{}/name
      detail -> /product/{}/details, /user/{}/recent-orders, /cart/{}/items
      Any state can return to START (session end / new session).
      Heavy endpoints (/search/products/full, /user/orders/all, /export/*, /analytics/*)
      excluded — admin-only or too expensive for normal browsing.

    Transition weights are set to reflect realistic browsing:
    users spend most time on low/medium endpoints and only occasionally
    trigger expensive operations.
    """

    # Transition table: {from_url_pattern: [(to_url_pattern, weight), ...]}
    # Patterns match the normalised URL (with {product_id} etc. as-is from endpoints.yaml).
    _TRANSITIONS = {
        "__start__": [
            ("/ping",                          5),
            ("/category/{category_id}/name",   4),
            ("/product/{product_id}/name",     3),
        ],
        "/ping": [
            ("/category/{category_id}/name",   4),
            ("/product/{product_id}/name",     4),
            ("__start__",                      2),
        ],
        "/category/{category_id}/name": [
            ("/category/{category_id}/products", 5),
            ("/product/{product_id}/name",       3),
            ("__start__",                        2),
        ],
        "/category/{category_id}/products": [
            ("/product/{product_id}/name",    5),
            ("/product/{product_id}/details", 3),
            ("__start__",                     2),
        ],
        "/product/{product_id}/name": [
            ("/product/{product_id}/details", 6),
            ("/category/{category_id}/name",  2),
            ("__start__",                     2),
        ],
        "/product/{product_id}/details": [
            ("/cart/{user_id}/items",         5),
            ("/user/{user_id}/recent-orders", 2),
            ("/category/{category_id}/name",  2),
            ("__start__",                     1),
        ],
        "/cart/{user_id}/items": [
            ("/user/{user_id}/recent-orders", 4),
            ("/product/{product_id}/details", 2),
            ("__start__",                     4),
        ],
        "/user/{user_id}/name": [
            ("/user/{user_id}/recent-orders", 5),
            ("/user/{user_id}/orders/all",    1),
            ("__start__",                     4),
        ],
        "/user/{user_id}/recent-orders": [
            ("/user/{user_id}/orders/all",    1),
            ("/cart/{user_id}/items",         4),
            ("__start__",                     5),
        ],
        "/user/{user_id}/orders/all": [
            ("__start__", 10),
        ],
    }

    def __init__(self, endpoints):
        # Filter to real endpoints only
        real = [e for e in endpoints if e.get("kind", "real") == "real"]
        super().__init__(real)
        # Build url -> endpoint dict for fast lookup
        self._by_url = {e["url"]: e for e in real}
        # Each thread gets its own Markov state via thread-local storage
        import threading
        self._local = threading.local()

    def _sample(self, choices):
        """Weighted random choice from [(url, weight), ...]."""
        total = sum(w for _, w in choices)
        r = random.random() * total
        for url, w in choices:
            r -= w
            if r <= 0:
                return url
        return choices[-1][0]

    def next_endpoint(self) -> dict:
        # Each thread maintains its own independent Markov state
        if not hasattr(self._local, "state"):
            self._local.state = "__start__"
        transitions = self._TRANSITIONS.get(self._local.state, [("__start__", 1)])
        next_url = self._sample(transitions)
        if next_url == "__start__":
            self._local.state = "__start__"
            transitions = self._TRANSITIONS["__start__"]
            next_url = self._sample(transitions)
        self._local.state = next_url
        ep = self._by_url.get(next_url)
        if ep is None:
            ep = random.choice(self.endpoints)
        return ep
