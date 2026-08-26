#!/usr/bin/env bash
# ==============================================================================
# Setup Environment for 1Cat-vLLM (Tesla V100 / SM70)
# ==============================================================================
# Requirements:
#   - OS: Ubuntu 20.04 / 22.04 / 24.04
#   - Python: 3.12
#   - CUDA Toolkit: 12.8 (or compatible with CUDA 12.8 runtime wheels)
# ==============================================================================

set -euo pipefail

ENV_NAME="${ENV_NAME:-1cat-vllm-sm70}"
CONDA_DIR="${CONDA_DIR:-$HOME/miniconda3}"
CUDA_HOME="${CUDA_HOME:-/usr/local/cuda-12.8}"

echo "=========================================================="
echo " Setting up 1Cat-vLLM Environment"
echo " Target GPU  : Tesla V100 (SM70)"
echo " Python      : 3.12"
echo " CUDA Home   : $CUDA_HOME"
echo " Conda Env   : $ENV_NAME"
echo "=========================================================="

# 1. Setup CUDA 12.8 Environment Variables
if [ -d "$CUDA_HOME" ]; then
    export CUDA_HOME="$CUDA_HOME"
    export PATH="$CUDA_HOME/bin:${PATH:-}"
    export LD_LIBRARY_PATH="$CUDA_HOME/lib64:${LD_LIBRARY_PATH:-}"
    echo "[✓] Configured CUDA 12.8 from $CUDA_HOME"
else
    echo "[!] Warning: $CUDA_HOME directory not found. Using system default CUDA."
fi

# 2. Initialize and activate Conda
if command -v conda &> /dev/null; then
    eval "$(conda shell.bash hook)"
elif [ -f "$CONDA_DIR/etc/profile.d/conda.sh" ]; then
    source "$CONDA_DIR/etc/profile.d/conda.sh"
else
    echo "[!] Conda not found in PATH or at $CONDA_DIR. Falling back to Python venv."
    VENV_DIR="$HOME/.venvs/$ENV_NAME"
    mkdir -p "$(dirname "$VENV_DIR")"
    if [ ! -d "$VENV_DIR" ]; then
        echo "[*] Creating virtual environment at $VENV_DIR..."
        python3 -m venv "$VENV_DIR"
    fi
    source "$VENV_DIR/bin/activate"
fi

# Create conda env if using conda
if command -v conda &> /dev/null; then
    if conda env list | grep -q "$ENV_NAME"; then
        echo "[*] Conda environment '$ENV_NAME' already exists. Activating..."
        conda activate "$ENV_NAME"
    else
        echo "[*] Creating Conda environment '$ENV_NAME' with Python 3.12..."
        conda create -y -n "$ENV_NAME" python=3.12
        conda activate "$ENV_NAME"
    fi
fi

# 3. Upgrade pip and build tools
echo "[*] Upgrading pip, setuptools, and wheel..."
python -m pip install --upgrade pip setuptools wheel

# 4. Install PyTorch with CUDA 12.8 runtime
echo "[*] Installing PyTorch with CUDA 12.8 runtime support..."
python -m pip install --prefer-binary --no-cache-dir \
    torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cu128

# 5. Fetch and install 1Cat-vLLM & FlashAttention-V100 Wheels from GitHub Releases
echo "[*] Fetching latest 1Cat-vLLM & FlashAttention-V100 release wheels..."
WHEEL_DIR="./wheels"
mkdir -p "$WHEEL_DIR"

WHEEL_URLS=$(curl -s https://api.github.com/repos/1CatAI/1Cat-vLLM/releases/latest | \
    grep "browser_download_url.*\.whl" | cut -d '"' -f 4 || true)

if [ -n "$WHEEL_URLS" ]; then
    for url in $WHEEL_URLS; do
        wheel_file="$WHEEL_DIR/$(basename "$url")"
        if [ ! -f "$wheel_file" ]; then
            echo "[*] Downloading wheel: $(basename "$url")..."
            curl -L "$url" -o "$wheel_file"
        else
            echo "[✓] Wheel already cached at $wheel_file"
        fi
    done

    echo "[*] Installing 1Cat-vLLM wheels..."
    python -m pip install --prefer-binary --no-cache-dir \
        --extra-index-url https://download.pytorch.org/whl/cu128 \
        "$WHEEL_DIR"/*.whl
else
    echo "[!] Could not automatically fetch latest release wheel URLs via GitHub API."
    echo "[*] Attempting to install from local ./wheels directory..."
    if ls "$WHEEL_DIR"/*.whl 1> /dev/null 2>&1; then
        python -m pip install --prefer-binary --no-cache-dir \
            --extra-index-url https://download.pytorch.org/whl/cu128 \
            "$WHEEL_DIR"/*.whl
    else
        echo "[*] Installing auxiliary utilities..."
        python -m pip install --no-cache-dir huggingface-hub hf-transfer openai
        echo "=========================================================="
        echo "Please manually download the .whl files from:"
        echo "  https://github.com/1CatAI/1Cat-vLLM/releases/latest"
        echo "Place them in $PWD/$WHEEL_DIR and rerun this script."
        echo "=========================================================="
        exit 1
    fi
fi

# 6. Install helpful dependencies
python -m pip install --no-cache-dir huggingface-hub hf-transfer openai

echo "=========================================================="
echo " 1Cat-vLLM Environment Setup Complete!"
echo " Activate with: conda activate $ENV_NAME"
echo " Test vLLM with: vllm --version"
echo "=========================================================="
