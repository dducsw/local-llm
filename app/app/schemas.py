from typing import Any
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


class CreateKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    allowed_models: list[str] = Field(default_factory=lambda: ["*"])
    rpm: int = Field(default=60, ge=1, le=100000)


class SubmitJobRequest(BaseModel):
    model: str = "Qwen3.5-9B-Q4_K_M.gguf"
    partition: str = "gpu-queue"
    gres: str = "gpu:1"
    time_limit: str = "01:00:00"
    tp: int = 1


class StartTunnelRequest(BaseModel):
    node: str = ""
    local_port: int = 18000
    remote_port: int = 8000
