# vLLM Benchmark Summary

| case | request_throughput | output_throughput | p50_ttft_ms | p99_ttft_ms | p50_tpot_ms | p99_tpot_ms | p50_e2el_ms | p99_e2el_ms | peak_waiting_requests | peak_gpu_kv_cache_usage | preemptions_delta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 00_smoke_c1_i32_o16 | 0.8516 | 13.6263 | 162.4846 | 178.3995 | 67.4114 | 67.6483 | 1172.2682 | 1193.0705 | 0.0000 | 0.0003 | 0.0000 |
| 01_baseline_c1_i128_o64 | 0.2238 | 14.3228 | 198.7409 | 263.0475 | 67.6493 | 68.3489 | 4457.7987 | 4527.4124 | 0.0000 | 0.0009 | 0.0000 |
| 02_baseline_c4_i512_o128 | 0.3541 | 45.3196 | 705.0684 | 1162.2039 | 83.5700 | 86.9580 | 11274.6620 | 11525.0656 | 1.0000 | 0.0106 | 0.0000 |
