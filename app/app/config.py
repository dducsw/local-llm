import json
import logging
import os
import secrets
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = APP_DIR.parent

# Auto-load .env from either app/.env or root .env
for env_candidate in [APP_DIR / ".env", ROOT_DIR / ".env", Path(".env")]:
    if env_candidate.is_file():
        try:
            for line in env_candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v
        except Exception:
            pass
        break

def _resolve_config_path(env_var: str, default_rel: str) -> Path:
    val = os.getenv(env_var, "")
    if val:
        p = Path(val)
        if p.is_absolute() and p.exists():
            return p
        if (APP_DIR / p).exists():
            return APP_DIR / p
        if (ROOT_DIR / p).exists():
            return ROOT_DIR / p
        if (APP_DIR / p.name).exists():
            return APP_DIR / p.name
    return APP_DIR / default_rel

DB_PATH = _resolve_config_path("KEY_DB", "data/gateway.db")
MODEL_CONFIG = _resolve_config_path("MODEL_CONFIG", "config/models.json")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", os.getenv("ADMIN_TOKEN", ""))
if not ADMIN_PASSWORD:
    ADMIN_PASSWORD = secrets.token_urlsafe(16)
    print(f"\n{'='*50}\nSECURITY WARNING: No ADMIN_PASSWORD set in .env!\nGenerated random admin password: {ADMIN_PASSWORD}\n{'='*50}\n")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", ADMIN_PASSWORD)
UPSTREAM_TIMEOUT = float(os.getenv("UPSTREAM_TIMEOUT", "3600"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# HPC SSH / Slurm Supervision Configurations
HPC_SSH_HOST = os.getenv("HPC_SSH_HOST", "")
HPC_SSH_USER = os.getenv("HPC_SSH_USER", "")
HPC_SSH_KEY = os.getenv("HPC_SSH_KEY", "")
if not HPC_SSH_KEY and os.path.exists("/run/secrets/hpc_ssh_key"):
    HPC_SSH_KEY = "/run/secrets/hpc_ssh_key"
HPC_REMOTE_DIR = os.getenv("HPC_REMOTE_DIR", "~/local-llm/infra")
HPC_LOG_DIR = os.getenv("HPC_LOG_DIR", f"{HPC_REMOTE_DIR}/logs")
HPC_SLURM_ACCOUNT = os.getenv("HPC_SLURM_ACCOUNT", "summer-school")

# In-memory session and rate-limiting stores
ADMIN_SESSIONS: dict[str, float] = {}  # session_token -> expiry_timestamp
LOGIN_ATTEMPTS: dict[str, list[float]] = defaultdict(list)  # ip -> list of timestamps
WINDOWS: dict[int, deque[float]] = defaultdict(deque)  # key_id -> deque of timestamps
RECENT_LOGS: deque[dict[str, Any]] = deque(maxlen=200)
ACTIVE_SLURM_JOBS: list[dict[str, Any]] = []

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("local-llm-api")


def load_models() -> dict[str, dict[str, Any]]:
    global MODELS
    if not MODEL_CONFIG.is_file():
        return {}
    try:
        data = json.loads(MODEL_CONFIG.read_text(encoding="utf-8"))
        models = {}
        for item in data.get("models", []):
            models[item["id"]] = item
        MODELS = models
        return models
    except Exception as exc:
        return MODELS if 'MODELS' in globals() else {}


MODELS = load_models()
