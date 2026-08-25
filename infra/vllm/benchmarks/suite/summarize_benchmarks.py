#!/usr/bin/env python3
import argparse
import csv
import json
from pathlib import Path
from statistics import mean

GAUGES = {
    "vllm:num_requests_running": "peak_running_requests",
    "vllm:num_requests_waiting": "peak_waiting_requests",
    "vllm:gpu_cache_usage_perc": "peak_gpu_kv_cache_usage",
}
COUNTERS = {
    "vllm:num_preemptions_total": "preemptions_delta",
    "vllm:prompt_tokens_total": "server_prompt_tokens_delta",
    "vllm:generation_tokens_total": "server_generation_tokens_delta",
}

CLIENT_KEYS = [
    "duration", "completed", "total_input_tokens", "total_output_tokens",
    "request_throughput", "request_goodput:", "output_throughput",
    "total_token_throughput",
    "mean_ttft_ms", "median_ttft_ms", "p50_ttft_ms", "p90_ttft_ms",
    "p95_ttft_ms", "p99_ttft_ms",
    "mean_tpot_ms", "median_tpot_ms", "p50_tpot_ms", "p90_tpot_ms",
    "p95_tpot_ms", "p99_tpot_ms",
    "mean_itl_ms", "median_itl_ms", "p50_itl_ms", "p90_itl_ms",
    "p95_itl_ms", "p99_itl_ms",
    "mean_e2el_ms", "median_e2el_ms", "p50_e2el_ms", "p90_e2el_ms",
    "p95_e2el_ms", "p99_e2el_ms",
]

def aggregate_prom(path):
    vals = {}
    errors = 0
    if not path.exists():
        return {}, 0
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("scrape_error"):
                errors += 1
            name = row.get("metric", "")
            if name not in GAUGES and name not in COUNTERS:
                continue
            try:
                v = float(row["value"])
            except Exception:
                continue
            vals.setdefault(name, []).append(v)

    out = {}
    for metric, col in GAUGES.items():
        xs = vals.get(metric, [])
        if xs:
            out[col] = max(xs)
            out[col.replace("peak_", "mean_")] = mean(xs)
    for metric, col in COUNTERS.items():
        xs = vals.get(metric, [])
        if xs:
            out[col] = max(xs) - min(xs)
    return out, errors

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="Benchmark result root directory")
    ap.add_argument("--csv", default=None)
    ap.add_argument("--markdown", default=None)
    args = ap.parse_args()

    root = Path(args.root)
    rows = []
    for client_json in sorted(root.rglob("client.json")):
        case_dir = client_json.parent
        try:
            data = json.loads(client_json.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"WARN: cannot parse {client_json}: {e}")
            continue

        row = {
            "case": data.get("case", case_dir.name),
            "input_len": data.get("input_len", ""),
            "output_len": data.get("output_len", ""),
            "num_prompts": data.get("num_prompts", ""),
            "request_rate": data.get("request_rate", ""),
            "max_concurrency": data.get("max_concurrency", ""),
            "backend": data.get("backend", ""),
            "model_id": data.get("model_id", ""),
        }
        for k in CLIENT_KEYS:
            row[k.replace(":", "")] = data.get(k, "")
        prom, scrape_errors = aggregate_prom(case_dir / "metrics_timeseries.csv")
        row.update(prom)
        row["metrics_scrape_errors"] = scrape_errors
        rows.append(row)

    if not rows:
        raise SystemExit(f"No client.json files found under {root}")

    preferred = [
        "case", "input_len", "output_len", "num_prompts",
        "request_rate", "max_concurrency", "completed", "duration",
        "request_throughput", "output_throughput", "total_token_throughput",
        "mean_ttft_ms", "p50_ttft_ms", "p90_ttft_ms", "p95_ttft_ms", "p99_ttft_ms",
        "mean_tpot_ms", "p50_tpot_ms", "p90_tpot_ms", "p95_tpot_ms", "p99_tpot_ms",
        "mean_itl_ms", "p50_itl_ms", "p90_itl_ms", "p95_itl_ms", "p99_itl_ms",
        "mean_e2el_ms", "p50_e2el_ms", "p90_e2el_ms", "p95_e2el_ms", "p99_e2el_ms",
        "peak_running_requests", "peak_waiting_requests",
        "peak_gpu_kv_cache_usage", "mean_gpu_kv_cache_usage",
        "preemptions_delta", "server_prompt_tokens_delta",
        "server_generation_tokens_delta", "metrics_scrape_errors",
    ]
    all_keys = []
    for r in rows:
        for k in r:
            if k not in all_keys:
                all_keys.append(k)
    fields = [k for k in preferred if k in all_keys] + [k for k in all_keys if k not in preferred]

    csv_path = Path(args.csv) if args.csv else root / "summary.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    md_path = Path(args.markdown) if args.markdown else root / "summary.md"
    show = [
        "case", "request_throughput", "output_throughput",
        "p50_ttft_ms", "p99_ttft_ms", "p50_tpot_ms", "p99_tpot_ms",
        "p50_e2el_ms", "p99_e2el_ms", "peak_waiting_requests",
        "peak_gpu_kv_cache_usage", "preemptions_delta"
    ]
    show = [k for k in show if k in fields]
    with md_path.open("w", encoding="utf-8") as f:
        f.write("# vLLM Benchmark Summary\n\n")
        f.write("| " + " | ".join(show) + " |\n")
        f.write("| " + " | ".join(["---"] * len(show)) + " |\n")
        for r in rows:
            vals = []
            for k in show:
                v = r.get(k, "")
                if isinstance(v, float):
                    v = f"{v:.4f}"
                vals.append(str(v))
            f.write("| " + " | ".join(vals) + " |\n")

    print(csv_path)
    print(md_path)

if __name__ == "__main__":
    main()
