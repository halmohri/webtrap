"""
defense.py — Adaptive Decoy Defense lifecycle loop.

Runs as a standalone process alongside app.py.
All configuration is read from configs/defense.yaml.

Usage:
  python3 defense.py
  python3 defense.py --health-only
"""

import argparse
import csv
import datetime
import json
import sys
import time
import urllib.request
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sprt import SPRT
from system import System

TESTBED          = Path(__file__).resolve().parent.parent
LOGS_DIR         = TESTBED / "logs"
CONFIGS_DIR      = TESTBED / "configs"
REQUESTS_CSV     = LOGS_DIR / "requests.csv"
DETECTIONS_PATH  = LOGS_DIR / "detections.jsonl"
MITIGATION_STATE = CONFIGS_DIR / "mitigations_state.json"
YAML_PATH        = CONFIGS_DIR / "endpoints.yaml"
CONFIG_PATH      = CONFIGS_DIR / "defense.yaml"

_RUN_STAMP   = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
HEALTH_PATH  = None  # set in main() after name is known
RUN_PATH     = None  # set in main() after name is known


def _make_paths(name=None):
    suffix = f"_{name}" if name else ""
    global HEALTH_PATH, RUN_PATH
    HEALTH_PATH = LOGS_DIR / f"health_{_RUN_STAMP}{suffix}.csv"
    RUN_PATH    = LOGS_DIR / f"defense_run_{_RUN_STAMP}{suffix}.csv"


def log_run(elapsed_s, c, delta, E, detected, rejected, mitigations_active, tick_proc_ms):
    """Append a per-tick row to the defense run CSV for offline analysis."""
    try:
        write_header = not RUN_PATH.exists()
        with RUN_PATH.open("a", newline="") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(["timestamp", "elapsed_s", "c", "delta", "E",
                            "detected", "rejected", "mitigations_active", "tick_proc_ms"])
            w.writerow([
                datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                round(elapsed_s, 2),
                round(c, 4),
                round(delta, 4),
                round(E, 4),
                int(detected),
                int(rejected),
                int(mitigations_active),
                round(tick_proc_ms, 4),
            ])
    except Exception:
        pass


def log_health(sys_monitor,logfile=True):
    s = sys_monitor.snapshot()
    health = max(s["cpu"], s["mem"], s["net"])
    if logfile: 
        try:
            write_header = not HEALTH_PATH.exists()
            with HEALTH_PATH.open("a", newline="") as f:
                w = csv.writer(f)
                if write_header:
                    w.writerow(["timestamp", "cpu", "mem", "net", "health"])
                w.writerow([datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), round(s["cpu"], 4), round(s["mem"], 4), round(s["net"], 4), round(health, 4)])
        except Exception:
            pass
    return s, health


def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def init_sprt(cfg):
    """Instantiate the single global SPRT from config sprt block."""
    log_a = cfg["log_a"]
    log_b = cfg["log_b"]
    s = cfg["sprt"]
    sprt = SPRT(s["mu0"], s["sigma0"], s["mu1"], s["sigma1"], log_a, log_b)
    print("=" * 60)
    print("SPRT INITIALIZED")
    print(f"  mu0    = {s['mu0']:.4f}   sigma0 = {s['sigma0']:.4f}")
    print(f"  mu1    = {s['mu1']:.4f}   sigma1 = {s['sigma1']:.4f}")
    print(f"  log_A  = {log_a:+.4f}   log_B  = {log_b:+.4f}")
    print(f"  E      = 0.0000")
    print("=" * 60)
    return sprt


def step_sprt(sprt, health_value):
    """Step the global SPRT with current health value. Return (delta, detected, rejected)."""
    _, delta, decision = sprt.step(health_value)
    return delta, decision


def _load_state():
    try:
        with open(MITIGATION_STATE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state):
    with open(MITIGATION_STATE, "w") as f:
        json.dump(state, f)


def activate_mitigations():
    """Flip ALL mitigation decoys to active. Return count activated."""
    with open(YAML_PATH) as f:
        data = yaml.safe_load(f)
    state = _load_state()
    count = 0
    for m in data.get("endpoints", []):
        if m.get("kind") != "mitigation":
            continue
        if not state.get(m["url"]):
            state[m["url"]] = True
            count += 1
    _save_state(state)
    return count


def verify_mitigations(host):
    """Hit one active mitigation URL and print the result."""
    state = _load_state()
    active = [url for url, v in state.items() if v]
    if not active:
        print("[defense] verify: no active mitigations to check")
        return
    url = active[0]
    full = host.rstrip("/") + url
    try:
        code = urllib.request.urlopen(full, timeout=3).getcode()
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception as e:
        print(f"[defense] verify: {full} -> ERROR {e}")
        return
    print(f"[defense] verify: {full} -> {code} ({'OK' if code == 200 else 'FAIL'}), {len(active)} mitigations active")


def retire_mitigations():
    """Set all mitigation decoys to inactive."""
    _save_state({})


def count_canary_hits(path, offset):
    """Count new canary hits in requests.csv since last offset. Returns (count, new_offset)."""
    count = 0
    try:
        with open(path, newline="") as f:
            rows = list(csv.reader(f))
        new_offset = len(rows)
        for row in rows[offset:]:
            if len(row) >= 4 and row[3] == "1":  # kind == CANARY
                count += 1
        return count, new_offset
    except Exception:
        return 0, offset


def log_detection(tag):
    try:
        with open(DETECTIONS_PATH, "a") as f:
            f.write(json.dumps({"t": round(time.time(), 3), "event": tag}) + "\n")
    except Exception:
        pass


def main(no_mitigate=False, always_mitigate=False, no_canary=False, name=None):
    _make_paths(name)
    cfg = load_config()
    tick   = cfg.get("tick",   5.0)
    log_a  = cfg.get("log_a",  30.0)
    log_b  = cfg.get("log_b", -30.0)
    eta    = 0.0 if no_canary else cfg.get("eta", 5.0)
    host   = cfg.get("host",   "http://localhost:8700")

    max_duration = float(cfg.get("max_duration_minutes", 60)) * 60

    retire_mitigations()  # clear any stale state from previous run
    sprt = init_sprt(cfg)
    sys_monitor = System()
    mitigations_active = False
    offset = 0
    started_at = time.time()

    if always_mitigate:
        activate_mitigations()
        mitigations_active = True
        verify_mitigations(host)

    print(f"[defense] started | tick={tick}s log_A={log_a} log_B={log_b} eta={eta} no_mitigate={no_mitigate} always_mitigate={always_mitigate} no_canary={no_canary} max={max_duration//60}m")

    while time.time() - started_at < max_duration:
        time.sleep(tick)
        tick_start = time.time()

        try:
            snap, health = log_health(sys_monitor)
            canary_hits, offset = count_canary_hits(REQUESTS_CSV, offset)
            if canary_hits and eta > 0:
                sprt.E += canary_hits * eta
                print(f"[def] canary hits={canary_hits} E boosted by {canary_hits * eta:+.2f} -> E={sprt.E:+.4f}")
            delta, decision = step_sprt(sprt, health)
            detected = decision == "DETECTED"
            rejected = decision == "REJECTED"
            print(f"[def] c={health:.4f}  delta={delta:+.4f} E={sprt.E:+.4f} dec={decision} mit={int(mitigations_active)}")
            if detected:
                log_detection("DETECTED")
                if not no_mitigate and not always_mitigate and not mitigations_active:
                    activate_mitigations()
                    mitigations_active = True
                    verify_mitigations(host)
            elif rejected:
                log_detection("REJECTED")
                if not no_mitigate and not always_mitigate and mitigations_active:
                    retire_mitigations()
                    mitigations_active = False
            tick_proc_ms = (time.time() - tick_start) * 1000
            log_run(time.time() - started_at, health, delta, sprt.E,
                    detected, rejected, mitigations_active, tick_proc_ms)
        except Exception as e:
            print(f"[defense] tick error: {e}")

    print("[defense] max duration reached, shutting down.")
    if not no_mitigate and not always_mitigate:
        retire_mitigations()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--health-only", action="store_true", help="Only collect health data, no detection")
    parser.add_argument("--no-mitigate", action="store_true", help="Run detection only, skip mitigation activation")
    parser.add_argument("--always-mitigate", action="store_true", help="Activate all mitigations at startup and never retire")
    parser.add_argument("--no-canary", action="store_true", help="Disable canary hit boost (eta=0), detection via health only")
    parser.add_argument("--name", default=None, help="Optional label appended to log filenames (e.g. naive_mit_canary)")
    args = parser.parse_args()

    if args.health_only:
        _make_paths(args.name)
        cfg = load_config()
        tick = cfg.get("tick", 5.0)
        max_duration = float(cfg.get("max_duration_minutes", 60)) * 60
        sys_monitor = System()
        started_at = time.time()
        print(f"[defense] health-only mode | tick={tick}s max={max_duration//60}m name={args.name}")
        while time.time() - started_at < max_duration:
            time.sleep(tick)
            log_health(sys_monitor)
    else:
        main(no_mitigate=args.no_mitigate, always_mitigate=args.always_mitigate, no_canary=args.no_canary, name=args.name)
