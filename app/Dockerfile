# ==============================================================================
# V100-local — Application Gateway & UI Dockerfile
# ==============================================================================
FROM python:3.11-slim

# Install OpenSSH client (for remote Slurm HPC supervision) and curl (for healthchecks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source files
COPY . /workspace/app

WORKDIR /workspace/app

# Ensure data and config directories exist
RUN mkdir -p /workspace/app/data /workspace/app/config

EXPOSE 9000

# Health check against gateway health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:9000/health || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]
