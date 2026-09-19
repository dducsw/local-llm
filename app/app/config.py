import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

# Re-export runtime state stores for convenience and backwards-compatibility
from app.state import (
    ADMIN_SESSIONS,
    LOGIN_ATTEMPTS,
    LOGIN_LOCK,
    WINDOWS,
    RECENT_LOGS,
    ACTIVE_SLURM_JOBS,
    SLURM_JOBS_LOCK,
    SESSIONS_LOCK,
)

APP_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = APP_DIR.parent

# Auto-load .env with python-dotenv
for env_candidate in [APP_DIR / ".env", ROOT_DIR / ".env", Path(".env")]:
    if env_candidate.is_file():
        load_dotenv(dotenv_path=env_candidate, override=False)
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

GATEWAY_VERSION = os.getenv("GATEWAY_VERSION", "1.1.0")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
if not ADMIN_PASSWORD:
    # If explicitly passed via ADMIN_TOKEN, warn and use it, otherwise generate random
    fallback_token = os.getenv("ADMIN_TOKEN", "")
    if fallback_token:
        ADMIN_PASSWORD = fallback_token
    else:
        ADMIN_PASSWORD = secrets.token_urlsafe(16)
        print(f"\n{'='*50}\nSECURITY WARNING: No ADMIN_PASSWORD set in .env!\nGenerated random admin password: {ADMIN_PASSWORD}\n{'='*50}\n")

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

VIEWER_USERNAME = os.getenv("VIEWER_USERNAME", "viewer")
VIEWER_PASSWORD = os.getenv("VIEWER_PASSWORD", "viewer123")

UPSTREAM_TIMEOUT = float(os.getenv("UPSTREAM_TIMEOUT", "3600"))
MAX_CONCURRENT_REQUESTS = int(os.getenv("MAX_CONCURRENT_REQUESTS", "16"))
MAX_CONCURRENT_PER_KEY = int(os.getenv("MAX_CONCURRENT_PER_KEY", "4"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# HPC SSH / Slurm Supervision Configurations
HPC_SSH_HOST = os.getenv("HPC_SSH_HOST", "")
HPC_SSH_USER = os.getenv("HPC_SSH_USER", "")
HPC_SSH_KEY = os.getenv("HPC_SSH_KEY", "")
if not HPC_SSH_KEY or not os.path.exists(os.path.expanduser(HPC_SSH_KEY)):
    host_key = os.getenv("HPC_HOST_SSH_KEY", "")
    if host_key and os.path.exists(os.path.expanduser(host_key)):
        HPC_SSH_KEY = host_key
    elif os.path.exists("/root/.ssh/id_ed25519"):
        HPC_SSH_KEY = "/root/.ssh/id_ed25519"
    elif os.path.exists(os.path.expanduser("~/.ssh/id_ed25519")):
        HPC_SSH_KEY = os.path.expanduser("~/.ssh/id_ed25519")
HPC_REMOTE_DIR = os.getenv("HPC_REMOTE_DIR", "~/local-llm/infra")
HPC_LOG_DIR = os.getenv("HPC_LOG_DIR", f"{HPC_REMOTE_DIR}/logs")
HPC_SLURM_ACCOUNT = os.getenv("HPC_SLURM_ACCOUNT", "summer-school")

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("local-llm-api")


class ModelRegistry:
    """Registry with 5-second TTL and file mtime check to eliminate disk I/O per request."""
    def __init__(self, config_path: Path, ttl_seconds: float = 5.0):
        self._path = config_path
        self._ttl = ttl_seconds
        self._cache: dict[str, dict[str, Any]] = {}
        self._last_loaded: float = 0.0
        self._last_mtime: float = 0.0

    def get_models(self) -> dict[str, dict[str, Any]]:
        now = time.time()
        try:
            current_mtime = self._path.stat().st_mtime if self._path.is_file() else 0.0
        except OSError:
            current_mtime = 0.0

        if (now - self._last_loaded < self._ttl) and (current_mtime == self._last_mtime) and self._cache:
            return self._cache

        if not self._path.is_file():
            return self._cache

        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            models = {}
            for item in data.get("models", []):
                models[item["id"]] = item
            self._cache = models
            self._last_loaded = now
            self._last_mtime = current_mtime
            return models
        except Exception as exc:
            log.warning("Failed to reload model configuration from %s: %s", self._path, exc)
            return self._cache


model_registry = ModelRegistry(MODEL_CONFIG)


def load_models() -> dict[str, dict[str, Any]]:
    return model_registry.get_models()


class _ModelsProxy(dict):
    """Dynamic dict proxy reflecting ModelRegistry cache without stale reads."""
    def __getitem__(self, key: str) -> dict[str, Any]:
        return load_models()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return load_models().get(key, default)

    def __contains__(self, key: object) -> bool:
        return key in load_models()

    def __iter__(self):
        return iter(load_models())

    def __len__(self) -> int:
        return len(load_models())

    def values(self):
        return load_models().values()

    def items(self):
        return load_models().items()

    def keys(self):
        return load_models().keys()


MODELS = _ModelsProxy()
