from typing import Any, Literal
from pydantic import BaseModel, Field


class Identity(BaseModel):
    id: int
    prefix: str
    name: str
    allowed_models: list[str]
    rpm: int


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    role: str
    username: str
    expires_at: float


class UserInfo(BaseModel):
    username: str
    role: str


class CreateKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    allowed_models: list[str] = Field(default_factory=lambda: ["*"])
    rpm: int = Field(default=60, ge=1, le=100000)
    duration: Literal["never", "1d", "7d", "30d", "90d"] = "never"


class SubmitJobRequest(BaseModel):
    model: str = "Qwen3.5-9B-Q4_K_M.gguf"
    partition: str = "gpu-queue"
    gres: str = "gpu:1"
    time_limit: str = "01:00:00"
    tp: int = Field(default=1, ge=1, le=8)


class StartTunnelRequest(BaseModel):
    node: str = Field(default="", max_length=128)
    local_port: int = Field(default=18000, ge=1024, le=65535)
    remote_port: int = Field(default=8000, ge=1, le=65535)
