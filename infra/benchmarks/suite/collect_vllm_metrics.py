#!/usr/bin/env python3
import argparse
import csv
import datetime as dt
import math
import re
import signal
import sys
import time
import urllib.request

STOP = False

PROM_RE = re.compile(
    r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(.*)\})?\s+'
    r'([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?|NaN|[+-]?Inf)'
    r'(?:\s+\d+)?$'
)

def on_signal(signum, frame):
    global STOP
    STOP = True

def fetch(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": "vllm-hpc-metrics-collector/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")

def parse_value(s):
    if s == "NaN":
        return float("nan")
    if s in ("+Inf", "Inf"):
        return float("inf")
    if s == "-Inf":
        return float("-inf")
    return float(s)

def main():
    ap = argparse.ArgumentParser(description="Poll a Prometheus text endpoint into long-form CSV.")
    ap.add_argument("--url", required=True, help="Prometheus endpoint, e.g. http://host:50380/metrics")
    ap.add_argument("--output", required=True, help="Output CSV path")
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--prefix", default="vllm:", help="Only keep metrics beginning with this prefix; empty keeps all")
    args = ap.parse_args()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    out = PathLike = args.output
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["timestamp_epoch", "timestamp_iso", "metric", "labels", "value", "scrape_error"])
        f.flush()

        next_t = time.monotonic()
        while not STOP:
            epoch = time.time()
            iso = dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc).isoformat()
            try:
                text = fetch(args.url, args.timeout)
                wrote = False
                for line in text.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    m = PROM_RE.match(line)
                    if not m:
                        continue
                    name, labels, value_s = m.groups()
                    if args.prefix and not name.startswith(args.prefix):
                        continue
                    value = parse_value(value_s)
                    w.writerow([f"{epoch:.6f}", iso, name, labels or "", value, ""])
                    wrote = True
                if not wrote:
                    w.writerow([f"{epoch:.6f}", iso, "", "", "", "no matching metrics"])
            except Exception as e:
                w.writerow([f"{epoch:.6f}", iso, "", "", "", repr(e)])
            f.flush()

            next_t += args.interval
            sleep_s = next_t - time.monotonic()
            if sleep_s > 0:
                time.sleep(sleep_s)
            else:
                next_t = time.monotonic()

if __name__ == "__main__":
    main()
