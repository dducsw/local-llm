from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST

# 1. Traffic & Request Metrics
LLM_REQUESTS_TOTAL = Counter(
    "llm_requests_total",
    "Total count of LLM inference requests received",
    ["model", "status", "key_prefix", "stream"],
)

LLM_ACTIVE_REQUESTS = Gauge(
    "llm_active_requests",
    "Number of active in-flight LLM requests currently being processed",
    ["model"],
)

# 2. Latency & Performance Histograms
LLM_TTFT_SECONDS = Histogram(
    "llm_time_to_first_token_seconds",
    "Time to first token (TTFT) in seconds for streaming responses",
    ["model"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0],
)

LLM_LATENCY_SECONDS = Histogram(
    "llm_request_duration_seconds",
    "End-to-end request duration in seconds",
    ["model", "stream"],
    buckets=[0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0],
)

LLM_TOKENS_PER_SEC = Histogram(
    "llm_tokens_per_second",
    "Inference throughput in tokens per second on GPU cluster",
    ["model"],
    buckets=[10, 25, 50, 75, 90, 100, 125, 150, 200],
)

# 3. Token Accounting Counters
LLM_TOKENS_TOTAL = Counter(
    "llm_tokens_total",
    "Total token count processed by model and token type",
    ["model", "type", "key_prefix"],
)

# 4. Reliability & Infrastructure Metrics
LLM_UPSTREAM_ERRORS_TOTAL = Counter(
    "llm_upstream_errors_total",
    "Total count of errors encountered contacting HPC upstream",
    ["model", "error_type"],
)

LLM_SSH_TUNNEL_UP = Gauge(
    "llm_ssh_tunnel_up",
    "State of the SSH port-forwarding tunnel to HPC cluster (1=UP, 0=DOWN)",
)


def export_prometheus_metrics() -> tuple[bytes, str]:
    """Generate and return current Prometheus metrics scrape payload."""
    return generate_latest(), CONTENT_TYPE_LATEST
