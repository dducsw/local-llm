#!/usr/bin/env bash
# Source this from BOTH vllm_head_no_ssh.sbatch and vllm_worker_no_ssh.sbatch
# after SESSION is known. This is for the NEXT controlled benchmark run.
#
# Example:
#   source "$ROOT/benchmarks/suite/gpu_telemetry.sh"
#   start_gpu_telemetry "$SESSION"
#   trap 'stop_gpu_telemetry' EXIT

GPU_TELEMETRY_PID=""

start_gpu_telemetry() {
  local session="${1:?session directory required}"
  mkdir -p "$session"
  local host
  host="$(hostname -s)"
  local out="$session/gpu-${host}.csv"

  {
    echo "timestamp,index,uuid,name,utilization_gpu_pct,utilization_memory_pct,memory_used_mib,memory_total_mib,power_draw_w,temperature_gpu_c,clocks_sm_mhz"
    nvidia-smi \
      --query-gpu=timestamp,index,uuid,name,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw,temperature.gpu,clocks.sm \
      --format=csv,noheader,nounits \
      -l 1
  } > "$out" 2>"$session/gpu-${host}.err" &

  GPU_TELEMETRY_PID=$!
  echo "GPU telemetry pid=$GPU_TELEMETRY_PID output=$out"
}

stop_gpu_telemetry() {
  if [[ -n "${GPU_TELEMETRY_PID:-}" ]]; then
    kill "$GPU_TELEMETRY_PID" 2>/dev/null || true
    wait "$GPU_TELEMETRY_PID" 2>/dev/null || true
  fi
}
