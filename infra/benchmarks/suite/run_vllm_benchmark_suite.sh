#!/usr/bin/env bash
set -euo pipefail

# vLLM HPC benchmark suite for the proven 2-node / 8x V100 deployment.
#
# Usage:
#   SUITE_LEVEL=basic  ./run_vllm_benchmark_suite.sh
#   SUITE_LEVEL=full   ./run_vllm_benchmark_suite.sh
#   SUITE_LEVEL=stress ./run_vllm_benchmark_suite.sh
#
# Optional:
#   RUN_SOAK=1 SOAK_SECONDS=300 SUITE_LEVEL=stress ./run_vllm_benchmark_suite.sh

ROOT="${ROOT:-$HOME/llm_serving}"
SB="${SB:-$ROOT/build/vllm-gloo-nccl-patched.sandbox}"
API_BASE="${API_BASE:-http://10.1.1.238:50380}"
SERVED_MODEL="${SERVED_MODEL:-qwen2.5-72b}"
SERVING_RUN_ID="${SERVING_RUN_ID:-20260818-111259-1292391}"
SUITE_LEVEL="${SUITE_LEVEL:-full}"
RUN_SOAK="${RUN_SOAK:-0}"
SOAK_SECONDS="${SOAK_SECONDS:-300}"
RPS_WINDOW_SECONDS="${RPS_WINDOW_SECONDS:-90}"

CACHE_ROOT="${CACHE_ROOT:-${SCRATCH:-$HOME/.cache}/llm-serving}"
READY="${READY:-$CACHE_ROOT/huggingface/Qwen--Qwen2.5-72B-Instruct.READY}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COLLECTOR="$SCRIPT_DIR/collect_vllm_metrics.py"
SUMMARIZER="$SCRIPT_DIR/summarize_benchmarks.py"

BENCH_PY="${BENCH_PY:-$ROOT/build/vllm-custom/vllm/benchmarks/benchmark_serving.py}"

test -r "$READY" || { echo "ERROR: missing READY marker: $READY" >&2; exit 1; }
MODEL_CONTAINER="$(cat "$READY")"
MODEL_PATH="${MODEL_CONTAINER/#\/cache/$CACHE_ROOT}"

test -d "$MODEL_PATH" || { echo "ERROR: model path not found: $MODEL_PATH" >&2; exit 1; }
test -f "$BENCH_PY" || { echo "ERROR: benchmark_serving.py not found: $BENCH_PY" >&2; exit 1; }
test -f "$COLLECTOR" || { echo "ERROR: collector not found: $COLLECTOR" >&2; exit 1; }

STAMP="$(date +%Y%m%d-%H%M%S)"
OUT_ROOT="${OUT_ROOT:-$ROOT/benchmarks/results/$STAMP}"
mkdir -p "$OUT_ROOT"

echo "============================================================"
echo " vLLM HPC BENCHMARK SUITE"
echo "============================================================"
echo "suite_level=$SUITE_LEVEL"
echo "serving_run_id=$SERVING_RUN_ID"
echo "api=$API_BASE"
echo "model=$MODEL_PATH"
echo "served_model=$SERVED_MODEL"
echo "results=$OUT_ROOT"
echo "============================================================"

# ---------- preflight and evidence ----------
curl -fsS "$API_BASE/health" >/dev/null
curl -fsS "$API_BASE/v1/models" > "$OUT_ROOT/models.json"
curl -fsS "$API_BASE/metrics" > "$OUT_ROOT/metrics_initial.prom"

grep -q '"qwen2.5-72b"' "$OUT_ROOT/models.json" || {
  echo "ERROR: served model qwen2.5-72b not found in /v1/models" >&2
  exit 1
}

grep -q '^vllm:' "$OUT_ROOT/metrics_initial.prom" || {
  echo "ERROR: no vLLM metrics found at $API_BASE/metrics" >&2
  exit 1
}

{
  echo "timestamp=$STAMP"
  echo "suite_level=$SUITE_LEVEL"
  echo "serving_run_id=$SERVING_RUN_ID"
  echo "api_base=$API_BASE"
  echo "served_model=$SERVED_MODEL"
  echo "model_path=$MODEL_PATH"
  echo "sandbox=$SB"
  echo "benchmark_script=$BENCH_PY"
  echo "hostname=$(hostname -f 2>/dev/null || hostname)"
} > "$OUT_ROOT/suite.env"

apptainer exec --cleanenv "$SB" python3 - <<'PY' > "$OUT_ROOT/runtime_versions.txt"
import sys
import torch
import vllm
import xformers
import ray
print("python =", sys.version.replace("\n", " "))
print("torch =", torch.__version__)
print("torch_git =", torch.version.git_version)
print("torch_abi =", int(torch._C._GLIBCXX_USE_CXX11_ABI))
print("cuda =", torch.version.cuda)
print("vllm =", vllm.__version__)
print("xformers =", xformers.__version__)
print("ray =", ray.__version__)
PY

run_case() {
  local name="$1"
  local input_len="$2"
  local output_len="$3"
  local prompts="$4"
  local concurrency="$5"
  local rate="$6"

  local case_dir="$OUT_ROOT/$name"
  mkdir -p "$case_dir"

  echo
  echo "============================================================"
  echo " CASE: $name"
  echo " input=$input_len output=$output_len prompts=$prompts"
  echo " concurrency=$concurrency request_rate=$rate"
  echo "============================================================"

  curl -fsS "$API_BASE/metrics" > "$case_dir/metrics_before.prom"

  python3 "$COLLECTOR" \
    --url "$API_BASE/metrics" \
    --output "$case_dir/metrics_timeseries.csv" \
    --interval 1.0 \
    > "$case_dir/metrics_collector.log" 2>&1 &
  local mpid=$!

  cleanup_case() {
    kill -INT "$mpid" 2>/dev/null || true
    wait "$mpid" 2>/dev/null || true
  }
  trap cleanup_case RETURN

  local -a cargs=()
  if [[ "$concurrency" != "0" && "$concurrency" != "none" ]]; then
    cargs+=(--max-concurrency "$concurrency")
  fi

  set +e
  apptainer exec \
    --cleanenv \
    --env HF_HUB_OFFLINE=1 \
    --env TRANSFORMERS_OFFLINE=1 \
    "$SB" \
    python3 "$BENCH_PY" \
      --backend openai-chat \
      --base-url "$API_BASE" \
      --endpoint /v1/chat/completions \
      --model "$MODEL_PATH" \
      --tokenizer "$MODEL_PATH" \
      --served-model-name "$SERVED_MODEL" \
      --dataset-name random \
      --random-input-len "$input_len" \
      --random-output-len "$output_len" \
      --random-range-ratio 0.0 \
      --num-prompts "$prompts" \
      --request-rate "$rate" \
      "${cargs[@]}" \
      --ignore-eos \
      --percentile-metrics ttft,tpot,itl,e2el \
      --metric-percentiles 50,90,95,99 \
      --save-result \
      --save-detailed \
      --result-dir "$case_dir" \
      --result-filename client.json \
      --metadata \
        "case=$name" \
        "input_len=$input_len" \
        "output_len=$output_len" \
        "serving_run_id=$SERVING_RUN_ID" \
        "tp=4" \
        "pp=2" \
        "gpu=V100-SXM2-32GB" \
      2>&1 | tee "$case_dir/client.log"
  local rc=${PIPESTATUS[0]}
  set -e

  cleanup_case
  trap - RETURN

  curl -fsS "$API_BASE/metrics" > "$case_dir/metrics_after.prom" || true

  if [[ $rc -ne 0 ]]; then
    echo "$rc" > "$case_dir/FAILED"
    echo "CASE FAILED: $name rc=$rc" >&2
    return $rc
  fi
  touch "$case_dir/PASS"
}

# BASIC: correctness + single-request latency + normal server concurrency.
run_case "00_smoke_c1_i32_o16"       32   16   4   1   inf
run_case "01_baseline_c1_i128_o64"   128  64   12  1   inf
run_case "02_baseline_c4_i512_o128"  512  128  40  4   inf

if [[ "$SUITE_LEVEL" == "full" || "$SUITE_LEVEL" == "stress" ]]; then
  # Concurrency sweep around the current server max_num_seqs=4.
  run_case "03_concurrency_c2_i512_o128"   512 128 24  2  inf
  run_case "04_concurrency_c8_i512_o128"   512 128 64  8  inf
  run_case "05_concurrency_c16_i512_o128"  512 128 96 16  inf

  # Shape-specific tests.
  run_case "06_prefill_heavy_c4_i1536_o64" 1536 64  16 4 inf
  run_case "07_decode_heavy_c4_i256_o512"   256 512 16 4 inf
fi

if [[ "$SUITE_LEVEL" == "stress" ]]; then
  # Closed-loop burst saturation. With server max_num_seqs=4 this should
  # intentionally create a waiting queue and expose saturation behavior.
  run_case "08_stress_c32_i512_o128" 512 128 128 32 inf

  # Long/balanced requests while staying below max_model_len=2048.
  run_case "09_long_c4_i1024_o512" 1024 512 16 4 inf

  # Derive an approximate closed-loop capacity from the c4 baseline,
  # then test open-loop arrival rates around that capacity.
  BASE_JSON="$OUT_ROOT/02_baseline_c4_i512_o128/client.json"
  CAPACITY="$(python3 - "$BASE_JSON" <<'PY'
import json, sys
x=json.load(open(sys.argv[1]))
print(float(x["request_throughput"]))
PY
)"
  echo "derived_closed_loop_capacity_rps=$CAPACITY" | tee -a "$OUT_ROOT/suite.env"

  for pct in 25 50 75 100 125; do
    RATE="$(python3 - "$CAPACITY" "$pct" <<'PY'
import sys
cap=float(sys.argv[1]); pct=float(sys.argv[2])
print(max(cap*pct/100.0, 0.001))
PY
)"
    NP="$(python3 - "$RATE" "$RPS_WINDOW_SECONDS" <<'PY'
import math, sys
r=float(sys.argv[1]); sec=float(sys.argv[2])
print(max(16, int(math.ceil(r*sec))))
PY
)"
    run_case "10_openloop_${pct}pct_i512_o128" 512 128 "$NP" 0 "$RATE"
  done

  if [[ "$RUN_SOAK" == "1" ]]; then
    SOAK_RATE="$(python3 - "$CAPACITY" <<'PY'
import sys
print(max(float(sys.argv[1])*0.70, 0.001))
PY
)"
    SOAK_N="$(python3 - "$SOAK_RATE" "$SOAK_SECONDS" <<'PY'
import math, sys
print(max(20, int(math.ceil(float(sys.argv[1])*float(sys.argv[2])))))
PY
)"
    run_case "11_soak_70pct_i512_o128" 512 128 "$SOAK_N" 0 "$SOAK_RATE"
  fi
fi

curl -fsS "$API_BASE/metrics" > "$OUT_ROOT/metrics_final.prom"
if [[ -f "$ROOT/logs/vllm-run/$SERVING_RUN_ID/vllm-server.log" ]]; then
  tail -n 1000 "$ROOT/logs/vllm-run/$SERVING_RUN_ID/vllm-server.log" \
    > "$OUT_ROOT/vllm_server_tail.log"
fi

python3 "$SUMMARIZER" "$OUT_ROOT"

echo
echo "============================================================"
echo " BENCHMARK SUITE COMPLETE"
echo "============================================================"
echo "results:  $OUT_ROOT"
echo "summary:  $OUT_ROOT/summary.csv"
echo "markdown: $OUT_ROOT/summary.md"
echo
echo "Archive command:"
echo "  tar -C \"$(dirname "$OUT_ROOT")\" -czf \"$OUT_ROOT.tar.gz\" \"$(basename "$OUT_ROOT")\""
echo "============================================================"
