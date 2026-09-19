# ==============================================================================
# Local LLM Serving Gateway — Hardened Multi-Stage Dockerfile
# ==============================================================================

# Stage 1: Build dependencies
FROM python:3.11-slim-bookworm AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Minimal Runtime
FROM python:3.11-slim-bookworm AS runtime

# Install OpenSSH client (for Slurm SSH tunnel) and curl (for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder stage
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1

WORKDIR /workspace/app

# Copy application source files
COPY . /workspace/app

# Ensure data and config directories exist
RUN mkdir -p /workspace/app/data /workspace/app/config

EXPOSE 9001

# Health check against gateway health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:9001/health || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9001"]
