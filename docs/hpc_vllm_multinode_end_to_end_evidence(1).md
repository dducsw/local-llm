# Multi-Node vLLM Inference on an HPC Cluster
## End-to-End Engineering Evidence, Troubleshooting Record, and Reproduction Guide

**Project root:** `/home/u001013/llm_serving`  
**Final status:** **PASS — end-to-end inference verified**  
**Canonical successful run:** `20260818-111259-1292391`  
**Final model:** `Qwen/Qwen2.5-72B-Instruct`  
**Serving name:** `qwen2.5-72b`  
**API endpoint:** `http://10.1.1.238:50380`  
**Parallelism:** Tensor Parallel = 4, Pipeline Parallel = 2  
**Hardware:** 2 nodes × 4 NVIDIA Tesla V100-SXM2-32GB = 8 GPUs total

---

## 1. Purpose

The goal of this work was to deploy a large language model with vLLM across two GPU nodes in an HPC environment with strict inter-node TCP firewall constraints.

The target environment had the following characteristics:

- Slurm-managed GPU nodes.
- Two GPU nodes used for inference.
- Four NVIDIA Tesla V100-SXM2-32GB GPUs per node.
- Eight GPUs total.
- Tensor parallelism across four GPUs.
- Pipeline parallelism across two nodes.
- Ray used as the distributed executor.
- Inter-node TCP traffic allowed only in the range `50000-51000`.
- No reliable lateral SSH between GPU nodes.
- Nested `srun` was not reliable for this workflow.
- NVIDIA V100 GPUs are Volta architecture, compute capability `7.0`.

The final deployment successfully served `Qwen/Qwen2.5-72B-Instruct` through the OpenAI-compatible vLLM API and returned a real chat-completion response.

---

## 2. Final Result

```text
Model: Qwen/Qwen2.5-72B-Instruct
Serving name: qwen2.5-72b

Nodes:
  gpunode1 = 10.1.1.238
  gpunode3 = 10.1.1.236

GPUs:
  4 × Tesla V100-SXM2-32GB on gpunode1
  4 × Tesla V100-SXM2-32GB on gpunode3
  8 GPUs total

Distributed layout:
  TP = 4
  PP = 2

Ray:
  10.1.1.238:50000

vLLM API:
  http://10.1.1.238:50380

Firewall allocation:
  Ray / control plane = 50000-50399
  Gloo               = 50400-50599
  NCCL Socket         = 50600-51000
```

| Component | Status |
|---|---|
| Slurm two-node allocation | PASS |
| Ray 2-node cluster | PASS |
| Ray 8-GPU visibility | PASS |
| Gloo cross-node communication | PASS |
| Gloo port-range enforcement | PASS |
| Gloo same-host port collision mitigation | PASS |
| NCCL Socket cross-node communication | PASS |
| NCCL port-range enforcement | PASS |
| vLLM PyNccl using patched NCCL | PASS |
| Custom PyTorch native runtime | PASS |
| Rebuilt vLLM native extension | PASS |
| Rebuilt xFormers native extension | PASS |
| xFormers CUTLASS forward on V100 | PASS |
| Qwen2.5-72B model load | PASS |
| `/v1/models` | PASS |
| `/v1/chat/completions` | PASS |

---

## 3. Final Architecture

```text
                           node16
                    Login / submit node
                            |
              +-------------+-------------+
              |                           |
              v                           v
        Slurm HEAD job              Slurm WORKER job
          gpunode1                     gpunode3
        10.1.1.238                   10.1.1.236
        4 × V100                      4 × V100
              |                           |
              +-------------+-------------+
                            |
                       Ray cluster
                    2 nodes / 8 GPUs
                            |
                  vLLM distributed engine
                            |
                      TP = 4, PP = 2
                            |
                Qwen2.5-72B-Instruct
                            |
                OpenAI-compatible API
                            |
                 http://10.1.1.238:50380
```

The final orchestration intentionally does **not** depend on SSH between GPU nodes. `node16` submits separate head and worker jobs; the jobs coordinate through the shared filesystem, and application traffic flows directly between `gpunode1` and `gpunode3`.

---

## 4. HPC Environment

### 4.1 Nodes and GPUs

```text
gpunode1
  IP: 10.1.1.238
  GPUs: 4 × NVIDIA Tesla V100-SXM2-32GB

gpunode3
  IP: 10.1.1.236
  GPUs: 4 × NVIDIA Tesla V100-SXM2-32GB

Primary TCP interface: ens11f0
GPU compute capability: 7.0 / SM70
```

### 4.2 Slurm

```text
Partition: gpu-queue
QoS:       gpu-q
```

### 4.3 Firewall

Inter-node TCP communication was restricted to:

```text
50000-51000
```

The Linux ephemeral range was:

```text
32768-60999
```

The final allocation was:

```text
50000-50399   Ray / vLLM control plane
50400-50599   Gloo
50600-51000   NCCL Socket
```

---

## 5. Final Software Stack

| Component | Final value |
|---|---|
| Original image | `/home/u001013/llm_serving/build/vllm.sif` |
| Final sandbox | `/home/u001013/llm_serving/build/vllm-gloo-nccl-patched.sandbox` |
| Python | `3.12.10` |
| CUDA | `12.4` |
| PyTorch | `2.6.0+cu124` |
| PyTorch commit | `2236df1770800ffea5697b11b0bb0d910b2e59e1` |
| Torch C++ ABI | `1` |
| Gloo commit | `5354032ea08eadd7fc4456477f7f7c6308818509` |
| NCCL | patched `2.21.5` |
| Ray | `2.45.0` |
| vLLM base | `0.8.5.post1` |
| Rebuilt vLLM | `0.8.5.post2.dev0+g3015d56.d20260817` |
| xFormers source tag | `v0.0.29.post2` |
| xFormers source commit | `1298453cf117c63dd691c55925fe1f41d3c874d6` |
| xFormers GPU target | `TORCH_CUDA_ARCH_LIST=7.0` |
| Final model | `Qwen/Qwen2.5-72B-Instruct` |

Final native-runtime verification:

```text
torch = 2.6.0+cu124
torch git = 2236df1770800ffea5697b11b0bb0d910b2e59e1
torch ABI = 1
NCCL = (2, 21, 5)
torchvision = None
vllm = 0.8.5.post2.dev0+g3015d56.d20260817
vllm._C import = OK
ALL GOOD
```

---

## 6. Important Artifacts

```text
build/vllm.sif
build/vllm-gloo-nccl-patched.sandbox

build/torch-gloo-port/
build/torch-gloo-port/wheelhouse/
  torch-2.6.0+cu124-cp312-cp312-linux_x86_64.whl

build/vllm-custom/
build/vllm-custom/wheelhouse/
  vllm-0.8.5.post2.dev0+g3015d56.d20260817-cp312-cp312-linux_x86_64.whl

build/xformers-0.0.29.post2/
build/xformers-custom/
build/xformers-custom/wheelhouse/

slurm/vllm_2node_common.sh
slurm/wait_ray_2node.py
slurm/vllm_head_no_ssh.sbatch
slurm/vllm_worker_no_ssh.sbatch
slurm/run_vllm_2node.sh
slurm/stop_vllm_2node.sh
```

---

## 7. Troubleshooting Timeline

```text
Ray orchestration
    ↓
Gloo ephemeral-port firewall failure
    ↓
Patch Gloo listener
    ↓
NCCL ephemeral-port firewall failure
    ↓
Patch NCCL Socket listener
    ↓
Replace PyTorch with custom build
    ↓
vLLM native ABI mismatch
    ↓
Rebuild vLLM against custom Torch
    ↓
Gloo same-host listener collision
    ↓
Add per-rank Gloo subranges
    ↓
vLLM PyNccl still loads system NCCL 2.20.5
    ↓
Force VLLM_NCCL_SO_PATH to patched NCCL 2.21.5
    ↓
Qwen3 GPTQ auto-selects BitBLAS
    ↓
Force GPTQ
    ↓
Qwen3 MoE GPTQ incompatibility
    ↓
Switch to Qwen2.5-72B dense model
    ↓
Model loads, but stock xFormers fails
    ↓
Rebuild xFormers for Torch 2.6 + Python 3.12.10 + SM70
    ↓
1-GPU V100 xFormers smoke test
    ↓
Final 2-node / 8-GPU run
    ↓
vLLM READY
    ↓
Real chat completion PASS
```

---

## 8. Ray Multi-Node Orchestration

### Problem

Nested `srun` and SSH-based orchestration were unreliable in this cluster. GPU nodes could not be treated as a normal lateral SSH mesh.

### Fix

Use two independent Slurm jobs:

```text
node16
  +--> worker job --> gpunode3
  +--> head job   --> gpunode1
```

The head publishes Ray rendezvous information through the shared filesystem. The worker joins the published endpoint.

### Evidence

```text
RAY_WAIT nodes=1 gpus=4 cpus=16
RAY_WAIT nodes=2 gpus=8 cpus=32
RAY_CLUSTER_READY nodes>=2 gpus>=8
```

**Result: PASS**

---

## 9. Gloo Firewall Failure and Source Patch

### Problem

vLLM creates CPU process groups with Gloo. Stock Gloo selected TCP listener ports from the ephemeral range, which could fall outside `50000-51000`.

### Exact source versions

PyTorch:

```text
2236df1770800ffea5697b11b0bb0d910b2e59e1
```

Vendored Gloo:

```text
5354032ea08eadd7fc4456477f7f7c6308818509
```

### Fix

Patch the Gloo TCP listener to support:

```bash
GLOO_PORT_MIN
GLOO_PORT_MAX
```

Final values:

```bash
GLOO_PORT_MIN=50400
GLOO_PORT_MAX=50599
```

Custom Torch wheel:

```text
/home/u001013/llm_serving/build/torch-gloo-port/wheelhouse/
torch-2.6.0+cu124-cp312-cp312-linux_x86_64.whl
```

A two-node Gloo `all_reduce` smoke test passed after the patch.

**Result: PASS**

---

## 10. NCCL Socket Firewall Failure and Patch

### Problem

NCCL Socket also opened listeners on random TCP ports outside the firewall range.

Examples observed during debugging included:

```text
10.1.1.238:47251
10.1.1.238:37723
```

The failure appeared as:

```text
No route to host
```

### Important distinction

```bash
NCCL_SOCKET_IFNAME=ens11f0
NCCL_SOCKET_FAMILY=AF_INET
```

select the interface and IP family, but they do not constrain the TCP listener range.

### Fix

Patch the NCCL Socket listener to support:

```bash
NCCL_PORT_MIN
NCCL_PORT_MAX
```

Final values:

```bash
NCCL_PORT_MIN=50600
NCCL_PORT_MAX=51000
```

Patched NCCL library:

```text
/home/u001013/llm_serving/build/torch-gloo-port/pytorch/build/nccl/lib/libnccl.so.2.21.5
```

Direct validation:

```text
version_int = 22105
version = 2.21.5
```

Patch markers:

```text
NCCL_PORT_MIN
NCCL_PORT_MAX
NCCL_PORT_RANGE bound listener to port %d
NCCL_PORT_RANGE bind failed on port %d: %s
NCCL_PORT_RANGE no free listener port in range %d-%d
```

Two-node NCCL smoke jobs:

```text
4676  ncclp-head
4677  ncclp-worker
```

Both completed with exit code `0:0` and logged:

```text
Connected all rings
Connected all trees
Init COMPLETE
```

**Result: PASS**

---

## 11. Replacing Torch Broke the Existing vLLM Native Extension

### Failure

After installing the custom Torch build, the existing vLLM native extension failed with an undefined Torch symbol:

```text
ImportError: vllm/_C.abi3.so: undefined symbol:
_ZN5torch3jit17parseSchemaOrNameERKSsb
```

### Root cause

The prebuilt vLLM `_C` extension was linked against the previous Torch binary. Replacing Torch changed the native compatibility boundary.

### Fix

Rebuild vLLM from source against the custom Torch runtime.

Build parameters:

```bash
TORCH_CUDA_ARCH_LIST=7.0
MAX_JOBS=8
NVCC_THREADS=1
```

### Failed build attempt

The first build failed because `ccache` tried to write under a read-only container path:

```text
ccache: error:
Failed to create directory /cache/xdg/ccache/tmp:
Read-only file system
```

### Fix for build environment

Writable build caches were moved under the project:

```text
build/vllm-custom/ccache
build/vllm-custom/ccache/tmp
build/vllm-custom/xdg-cache
build/vllm-custom/xdg-config
```

Final rebuilt wheel:

```text
/home/u001013/llm_serving/build/vllm-custom/wheelhouse/
vllm-0.8.5.post2.dev0+g3015d56.d20260817-cp312-cp312-linux_x86_64.whl
```

Verification:

```text
vllm._C import = OK
ALL GOOD
```

**Result: PASS**

---

## 12. torchvision Compatibility

The stock torchvision native extension was no longer compatible with the custom Torch build. One observed failure was:

```text
RuntimeError: operator torchvision::nms does not exist
```

This serving stack is text-only, so torchvision was intentionally removed instead of rebuilt.

Final verification:

```text
torchvision = None
vllm._C import = OK
```

**Result: PASS — intentionally removed**

---

## 13. Correcting the Intended Model

The early launcher referenced:

```text
Qwen/Qwen2.5-32B-Instruct
```

The actual intended model from the download workflow was:

```text
Qwen/Qwen3-235B-A22B-GPTQ-Int4
```

Correct local snapshot:

```text
/home/u001013/.cache/llm-serving/huggingface/hub/
models--Qwen--Qwen3-235B-A22B-GPTQ-Int4/
snapshots/dff138951f3898772fc0d795a4b5b30f417577f4
```

The launcher was changed to resolve the model path from the `.READY` marker instead of relying on an outdated hard-coded model name.

---

## 14. Qwen3 GPTQ and BitBLAS

### Failure

vLLM automatically detected that the model could use the BitBLAS GPTQ backend:

```text
The model is convertible to gptq_bitblas during runtime.
Using gptq_bitblas kernel.
```

Then:

```text
ModuleNotFoundError: No module named 'bitblas'
```

### Fix attempt

The launcher forced standard GPTQ:

```bash
--quantization gptq
```

vLLM then reported that GPTQ was being forced instead of BitBLAS.

This bypassed the missing BitBLAS dependency.

**BitBLAS blocker: bypassed successfully**

---

## 15. Same-Host Gloo Port Collision

### Failure

After limiting Gloo to `50400-50599`, several Ray workers on the same host could still race while allocating listeners:

```text
RuntimeError:
... gloo/transport/tcp/socket.cc:100
listen: Address already in use
```

This was not a firewall problem. It was a same-host port-allocation race.

### Fix

Patch:

```text
vllm/distributed/parallel_state.py
```

and divide the global Gloo range into per-rank subranges:

```text
rank 0   50400-50424
rank 1   50425-50449
rank 2   50450-50474
rank 3   50475-50499
rank 4   50500-50524
rank 5   50525-50549
rank 6   50550-50574
rank 7   50575-50599
```

Runtime evidence:

```text
[VLLM_GLOO_RANK_RANGE] rank=0/8 range=50400-50424
[GLOO_PORT_RANGE] ... bound listener port=50403 ...
```

**Result: PASS**

---

## 16. vLLM PyNccl Loaded System NCCL 2.20.5

### Failure

Even after PyTorch used patched NCCL 2.21.5, vLLM's `PyNcclCommunicator` independently loaded:

```text
libnccl.so.2
```

and reported:

```text
vLLM is using nccl==2.20.5
```

That runtime then attempted the firewall-blocked port `37723`.

### Root cause

There were effectively two NCCL discovery paths:

```text
torch.distributed -> patched NCCL 2.21.5
vLLM PyNccl      -> system NCCL 2.20.5
```

### Fix

Force vLLM to load the patched NCCL library:

```bash
VLLM_NCCL_SO_PATH=/home/u001013/llm_serving/build/torch-gloo-port/pytorch/build/nccl/lib/libnccl.so.2.21.5
```

Final evidence:

```text
Found nccl from environment variable VLLM_NCCL_SO_PATH=...
vLLM is using nccl==2.21.5
NCCL_PORT_RANGE bound listener to port 50613
NCCL_PORT_RANGE bound listener to port 50617
NCCL_PORT_RANGE bound listener to port 50618
```

Cross-node PP communicators then logged:

```text
Connected all rings
Connected all trees
Init COMPLETE
```

**Result: PASS**

---

## 17. Why Qwen3-235B-A22B-GPTQ-Int4 Was Abandoned

After Ray, Gloo, and NCCL were all working, Qwen3 reached model construction and failed in the MoE quantization path:

```text
Qwen3MoeSparseMoeBlock
    ↓
FusedMoE
    ↓
assert self.quant_method is not None
    ↓
AssertionError
```

This was no longer an infrastructure failure.

At that point:

```text
Ray                PASS
Gloo               PASS
NCCL intra-node    PASS
NCCL cross-node    PASS
PP communicator    PASS
```

The remaining blocker was the combination of:

```text
Qwen3 MoE
+ GPTQ
+ vLLM 0.8.5-era implementation
+ V100 / SM70 constraints
```

The objective of the lab was to demonstrate large-model multi-node inference, not to patch Qwen3 MoE quantization internals. Therefore the Qwen3 path was intentionally abandoned.

```text
Qwen/Qwen3-235B-A22B-GPTQ-Int4
Final status: ABANDONED for this deployment
Reason: model/backend compatibility
```

---

## 18. Model Switch to Qwen2.5-72B-Instruct

Replacement model:

```text
Qwen/Qwen2.5-72B-Instruct
```

Reasons:

1. It is a large dense model.
2. It avoids the Qwen3 MoE + GPTQ path.
3. It is large enough to make an 8-V100 deployment meaningful.
4. The existing distributed infrastructure can be reused unchanged.

Downloaded cache:

```text
/home/u001013/.cache/llm-serving/huggingface/hub/
models--Qwen--Qwen2.5-72B-Instruct
```

Observed local size:

```text
136G
```

Snapshot:

```text
495f39366efef23836d0cfae4fbe635880d2be31
```

Initial conservative runtime:

```bash
MAX_MODEL_LEN=2048
MAX_NUM_SEQS=4
GPU_MEMORY_UTILIZATION=0.90
```

The GPTQ flag was removed.

---

## 19. Qwen2.5-72B Loaded but xFormers Failed

The first Qwen2.5-72B attempt successfully loaded all model shards:

```text
Loading safetensors checkpoint shards:
100% Completed | 37/37
```

Observed load statistics:

```text
Loading weights took 69.97 seconds
Model loading took 16.9957 GiB and 70.150939 seconds
```

The model then failed during the dummy/profile forward pass used for KV-cache sizing:

```text
NotImplementedError:
No operator found for `memory_efficient_attention_forward`
```

The stock xFormers package reported a build/runtime mismatch:

```text
built Python: 3.12.8
runtime Python: 3.12.10
```

Detailed inspection showed the native binary mismatch:

```text
OSError: xformers/_C.so: undefined symbol:
_ZNK5torch8autograd4Node4nameEv
```

### Root cause

The prebuilt xFormers native extension was binary-incompatible with the custom Torch runtime.

---

## 20. Rebuilding xFormers for Torch 2.6 + Python 3.12.10 + SM70

Source verification:

```text
tag:    v0.0.29.post2
commit: 1298453cf117c63dd691c55925fe1f41d3c874d6
```

Build environment:

```text
Python: 3.12.10
PyTorch: 2.6.0+cu124
Torch ABI: 1
CUDA: 12.4
TORCH_CUDA_ARCH_LIST=7.0
```

Generated wheel:

```text
xformers-0.0.30+1298453c.d20260818-cp312-cp312-linux_x86_64.whl
```

The generated version string was unusual, but the source repository itself was verified at `v0.0.29.post2` and commit `1298453c...`.

After installation:

```text
build.python_version: 3.12.10
build.torch_version: 2.6.0+cu124
build.env.TORCH_CUDA_ARCH_LIST: 7.0

memory_efficient_attention.cutlassF-pt: available
memory_efficient_attention.cutlassB-pt: available
```

Native loader verification:

```text
xformers.ops import = OK
XFORMERS_NATIVE_LOAD_OK
```

---

## 21. One-GPU V100 xFormers Smoke Test

Before using eight GPUs again, xFormers was tested directly on one V100.

Actual result:

```text
torch = 2.6.0+cu124
xformers = 0.0.30+1298453c.d20260818
GPU = Tesla V100-SXM2-32GB
CC = (7, 0)
out = (1, 2048, 2, 8, 128)
finite = True
XFORMERS_V100_OK
```

Slurm job:

```text
4783
```

The `.err` file was empty.

**Result: PASS**

This proved that the CUTLASS attention forward path executed successfully on an actual SM70 GPU.

---

## 22. Canonical Successful End-to-End Run

```text
RUN_ID=20260818-111259-1292391
```

Configuration:

```text
model=/home/u001013/.cache/llm-serving/huggingface/hub/models--Qwen--Qwen2.5-72B-Instruct/snapshots/495f39366efef23836d0cfae4fbe635880d2be31

tp=4
pp=2
ray=10.1.1.238:50000
api=http://10.1.1.238:50380
ray_ports=50000-50399
gloo_ports=50400-50599
nccl_ports=50600-51000
```

Ray readiness:

```text
RAY_WAIT nodes=2 gpus=8 cpus=32
RAY_CLUSTER_READY nodes>=2 gpus>=8
```

vLLM selected:

```text
Using XFormers backend.
```

Model loading:

```text
Loading safetensors checkpoint shards: 100% Completed | 37/37
Loading weights took 51.20 seconds
Model loading took 16.9957 GiB and 51.382544 seconds
```

Final readiness:

```text
============================================================
 VLLM READY
============================================================
API_URL=http://10.1.1.238:50380
MODEL=qwen2.5-72b
session=/home/u001013/llm_serving/logs/vllm-run/20260818-111259-1292391
```

**Result: PASS**

---

## 23. API Validation

### `/v1/models`

```bash
curl -sS http://10.1.1.238:50380/v1/models \
  | python3 -m json.tool
```

Response included:

```json
{
  "id": "qwen2.5-72b",
  "owned_by": "vllm",
  "max_model_len": 2048
}
```

**Result: PASS**

---

## 24. Actual Chat Completion Evidence

Request:

```bash
curl -sS http://10.1.1.238:50380/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen2.5-72b",
    "messages": [
      {
        "role": "user",
        "content": "Explain what tensor parallelism and pipeline parallelism are in 3 short sentences."
      }
    ],
    "temperature": 0.2,
    "max_tokens": 128
  }' | python3 -m json.tool
```

Actual response:

```text
Tensor parallelism splits large tensors across multiple GPUs to
parallelize computations, reducing memory requirements and increasing
throughput. Pipeline parallelism divides the model into stages, each
processed by different GPUs in a sequence, allowing for efficient use
of resources and faster training. Both techniques are used to scale
deep learning models beyond the capacity of a single GPU.
```

Token usage:

```text
prompt_tokens     = 46
completion_tokens = 67
total_tokens      = 113
finish_reason     = stop
```

This validates the entire serving path:

```text
HTTP request
  ↓
tokenization
  ↓
Ray scheduling
  ↓
distributed prefill
  ↓
TP communication
  ↓
PP cross-node communication
  ↓
xFormers attention on V100
  ↓
distributed decoding
  ↓
token generation
  ↓
OpenAI-compatible response
```

**Result: PASS**

---

## 25. Final Network Configuration

### Ray / control plane

```text
50000-50399
```

Representative values:

```bash
RAY_GCS_PORT=50000
RAY_NODE_MANAGER_PORT=50001
RAY_OBJECT_MANAGER_PORT=50002
RAY_RUNTIME_ENV_PORT=50003
RAY_WORKER_MIN_PORT=50020
RAY_WORKER_MAX_PORT=50179
VLLM_INTERNAL_PORT=50300
API_PORT=50380
```

### Gloo

```bash
GLOO_SOCKET_IFNAME=ens11f0
GLOO_PORT_MIN=50400
GLOO_PORT_MAX=50599
```

plus the per-rank subrange patch.

### NCCL

```bash
NCCL_NET=Socket
NCCL_IB_DISABLE=1
NCCL_SOCKET_IFNAME==ens11f0
NCCL_SOCKET_FAMILY=AF_INET
NCCL_PORT_MIN=50600
NCCL_PORT_MAX=51000
VLLM_NCCL_SO_PATH=/home/u001013/llm_serving/build/torch-gloo-port/pytorch/build/nccl/lib/libnccl.so.2.21.5
```

---

## 26. Final vLLM Launch Shape

```bash
vllm serve "$MODEL" \
  --served-model-name "$SERVED_MODEL" \
  --host 0.0.0.0 \
  --port "$API_PORT" \
  --dtype half \
  --tensor-parallel-size 4 \
  --pipeline-parallel-size 2 \
  --distributed-executor-backend ray \
  --gpu-memory-utilization 0.90 \
  --max-model-len 2048 \
  --max-num-seqs 4 \
  --disable-custom-all-reduce \
  --generation-config vllm
```

No GPTQ flag is used in the final Qwen2.5-72B deployment.

---

## 27. Reproduction from the Final Working State

```bash
cd ~/llm_serving

CACHE_ROOT="${SCRATCH:-$HOME/.cache}/llm-serving"
READY="$CACHE_ROOT/huggingface/Qwen--Qwen2.5-72B-Instruct.READY"
MODEL_CONTAINER="$(cat "$READY")"

export MODEL="${MODEL_CONTAINER/#\/cache/$CACHE_ROOT}"
export SERVED_MODEL="qwen2.5-72b"

export MAX_MODEL_LEN=2048
export MAX_NUM_SEQS=4
export GPU_MEMORY_UTILIZATION=0.90

./slurm/run_vllm_2node.sh
```

Wait for:

```text
RAY_CLUSTER_READY nodes>=2 gpus>=8
```

then:

```text
VLLM READY
```

Model endpoint:

```bash
curl -sS http://10.1.1.238:50380/v1/models \
  | python3 -m json.tool
```

Inference:

```bash
curl -sS http://10.1.1.238:50380/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen2.5-72b",
    "messages": [
      {"role": "user", "content": "Explain tensor parallelism briefly."}
    ],
    "temperature": 0.2,
    "max_tokens": 128
  }' | python3 -m json.tool
```

Stop:

```bash
./slurm/stop_vllm_2node.sh
```

or:

```bash
scancel HEAD_JOB WORKER_JOB
```

---

## 28. Failure/Fix Matrix

| Stage | Observed problem | Root cause | Fix | Final status |
|---|---|---|---|---|
| Orchestration | Nested `srun` / SSH unreliable | Cluster execution model | Independent Slurm head + worker jobs | PASS |
| Ray | Need 2 nodes / 8 GPUs | Distributed control-plane setup | Fixed Ray ports + shared rendezvous | PASS |
| Gloo | Cross-node connection failure | Ephemeral listener outside firewall | Patch Gloo listener | PASS |
| Gloo | `Address already in use` | Workers competing for same Gloo range | Per-rank Gloo subranges | PASS |
| NCCL | `No route to host` on random port | Socket listener outside firewall | Patch NCCL listener | PASS |
| Torch | Need patched communication libraries | Stock runtime did not contain patches | Rebuild exact PyTorch source | PASS |
| vLLM `_C` | Undefined Torch symbol | Native extension linked to old Torch | Rebuild vLLM | PASS |
| vLLM build | ccache read-only error | Cache path inside read-only container | Writable project cache | PASS |
| torchvision | `torchvision::nms` missing | Binary mismatch | Remove unused torchvision | PASS |
| Qwen3 GPTQ | Missing BitBLAS | vLLM auto-selected BitBLAS | Force GPTQ | Bypassed |
| Qwen3 MoE | `FusedMoE` assertion | Model/backend compatibility | Switch model | Abandoned |
| PyNccl | vLLM used NCCL 2.20.5 | Separate NCCL library discovery | `VLLM_NCCL_SO_PATH` | PASS |
| Qwen2.5-72B | Model loaded but profile failed | xFormers native mismatch | Rebuild xFormers | PASS |
| V100 attention | No usable stock attention op | V100/SM70 + old extension | xFormers CUTLASS SM70 | PASS |
| Final inference | Needed real request | End-to-end validation | `/v1/chat/completions` | PASS |

---

## 29. Engineering Lessons

### 29.1 Ray readiness is not inference readiness

A Ray cluster showing `2 nodes / 8 GPUs` validates orchestration, not the complete inference path. Gloo, NCCL, native extensions, attention kernels, model loading, KV-cache profiling, and request execution must all be validated separately.

### 29.2 Interface selection and port selection are different

`NCCL_SOCKET_IFNAME=ens11f0` selects the interface but does not constrain NCCL to an allowed listener range. The same principle applies to Gloo.

### 29.3 vLLM may use a different NCCL library from PyTorch

Checking `torch.cuda.nccl.version()` is insufficient. vLLM PyNccl must also be checked. In this deployment, `VLLM_NCCL_SO_PATH` was required to force vLLM onto patched NCCL 2.21.5.

### 29.4 Replacing Torch can invalidate every native extension above it

The following all required attention after the Torch rebuild:

```text
vllm._C
xformers._C
torchvision
```

Native compatibility depends on the actual Torch binary/ABI, Python version, CUDA build, compiler ABI, and GPU target — not only package version strings.

### 29.5 V100 needs an attention backend that truly supports SM70

The final working path used xFormers CUTLASS built with:

```bash
TORCH_CUDA_ARCH_LIST=7.0
```

A real one-GPU kernel test was performed before retrying the expensive eight-GPU job.

### 29.6 Stop debugging networking once the error moves into model internals

The Qwen3 failure occurred in `FusedMoE` after Ray/Gloo/NCCL were already healthy. At that point the correct action was to classify it as a model/backend compatibility issue rather than continuing to modify networking.

### 29.7 Isolate expensive failures with small smoke tests

NCCL was validated with a minimal two-node `all_reduce`, and xFormers was validated on one V100 before the final eight-GPU retry. This reduced iteration cost significantly.

---

## 30. Canonical Evidence to Preserve

### Final successful run

```text
RUN_ID=20260818-111259-1292391
```

Session directory:

```text
/home/u001013/llm_serving/logs/vllm-run/20260818-111259-1292391
```

API:

```text
http://10.1.1.238:50380
```

Model:

```text
qwen2.5-72b
```

### NCCL patched smoke

```text
4676  ncclp-head
4677  ncclp-worker
COMPLETED 0:0
```

### xFormers V100 smoke

```text
Job 4783
GPU = Tesla V100-SXM2-32GB
CC = (7, 0)
finite = True
XFORMERS_V100_OK
```

### API evidence

```text
GET /v1/models
  -> qwen2.5-72b

POST /v1/chat/completions
  -> successful generated response
  -> 46 prompt tokens
  -> 67 completion tokens
  -> 113 total tokens
```

---

## 31. Failed Runs to Keep as Debugging Evidence

The failed Qwen3 runs should not be represented as successful deployments. They are still valuable as evidence of individual infrastructure milestones.

Useful failure categories to preserve:

```text
Gloo random-port firewall failure
NCCL random-port firewall failure
Gloo same-host listener collision
PyNccl loading system NCCL 2.20.5
BitBLAS missing
Qwen3 FusedMoE quantization assertion
stock xFormers native extension mismatch
```

These failures explain why each final patch exists.

---

## 32. Known Limitations and Future Work

### 32.1 Final transport is TCP Socket

The validated baseline uses:

```bash
NCCL_NET=Socket
NCCL_IB_DISABLE=1
```

InfiniBand/RDMA optimization should be treated as a separate follow-up experiment.

### 32.2 Context and concurrency are conservative

The successful smoke configuration uses:

```text
max_model_len = 2048
max_num_seqs = 4
```

These values were chosen for correctness validation, not maximum throughput.

### 32.3 Performance benchmarking remains separate

A follow-up benchmark should measure:

- Time to first token (TTFT)
- Inter-token latency
- Output tokens/second
- Request throughput
- Concurrency 1 / 4 / 8 / 16
- Prompt-length sensitivity
- GPU utilization
- GPU memory usage
- Cross-node network utilization
- TP/PP scaling behavior

### 32.4 Qwen3-235B-A22B-GPTQ-Int4 remains a future compatibility target

The Qwen3 checkpoint was not made operational in this stack. It should be revisited with a newer model/quantization implementation rather than represented as a success in this report.

---

## 33. Final Conclusion

The successful deployment required fixes across the entire distributed inference stack:

```text
Slurm
  ↓
separate head / worker jobs
  ↓
Ray fixed-port 2-node cluster
  ↓
custom Gloo port-range patch
  ↓
per-rank Gloo port subdivision
  ↓
custom NCCL Socket port-range patch
  ↓
custom PyTorch build
  ↓
vLLM native-extension rebuild
  ↓
VLLM_NCCL_SO_PATH → patched NCCL 2.21.5
  ↓
Qwen3 compatibility investigation
  ↓
switch to Qwen2.5-72B dense model
  ↓
xFormers rebuild for Python 3.12.10 + Torch 2.6 + SM70
  ↓
single-V100 CUTLASS validation
  ↓
2-node / 8-GPU model load
  ↓
vLLM READY
  ↓
OpenAI-compatible API
  ↓
real chat completion
```

Final verified deployment:

```text
Model:
  Qwen/Qwen2.5-72B-Instruct

Hardware:
  2 nodes
  8 × NVIDIA Tesla V100-SXM2-32GB

Parallelism:
  TP = 4
  PP = 2

Distributed runtime:
  Ray

CPU collective backend:
  patched Gloo

GPU collective backend:
  patched NCCL 2.21.5 over Socket

Attention backend:
  rebuilt xFormers CUTLASS for SM70

API:
  http://10.1.1.238:50380

Result:
  END-TO-END INFERENCE PASS
```

The canonical successful evidence run is:

```text
RUN_ID=20260818-111259-1292391
```

This run should be used as the primary HPC Lab deployment evidence. Earlier Qwen3 runs should be retained as troubleshooting and failure-analysis evidence, not as deployment success.
