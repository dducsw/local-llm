import threading
from collections import defaultdict, deque
from typing import Any

# Session store: token -> {"username": str, "role": str, "expires_at": float}
ADMIN_SESSIONS: dict[str, dict[str, Any]] = {}
SESSIONS_LOCK = threading.Lock()

# Login rate-limiting store: ip -> list of timestamps
LOGIN_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
LOGIN_LOCK = threading.Lock()

# Per-key sliding window rate-limiting: key_id -> deque of timestamps
WINDOWS: dict[int, deque[float]] = defaultdict(deque)

# In-memory recent logs circular buffer
RECENT_LOGS: deque[dict[str, Any]] = deque(maxlen=200)

# Slurm active jobs cache / tracking
ACTIVE_SLURM_JOBS: list[dict[str, Any]] = []
SLURM_JOBS_LOCK = threading.Lock()
