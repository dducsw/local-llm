#!/usr/bin/env python3
import os
import socket
import torch
import torch.distributed as dist

rank = int(os.environ["RANK"])
world_size = int(os.environ["WORLD_SIZE"])

print(
    f"START host={socket.gethostname()} rank={rank}/{world_size} "
    f"torch={torch.__version__} torch_file={torch.__file__}",
    flush=True,
)

dist.init_process_group(
    backend="gloo",
    init_method="env://",
    rank=rank,
    world_size=world_size,
)

print(
    f"GLOO_OK host={socket.gethostname()} rank={rank} "
    f"range={os.environ.get('GLOO_PORT_MIN')}-{os.environ.get('GLOO_PORT_MAX')}",
    flush=True,
)

dist.barrier()
dist.destroy_process_group()
print(f"DONE host={socket.gethostname()} rank={rank}", flush=True)
