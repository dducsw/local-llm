#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_nccl_port_range.py <path-to-nccl-source>")

src = Path(sys.argv[1]).expanduser().resolve()
path = src / "src" / "misc" / "socket.cc"

if not path.is_file():
    raise SystemExit(f"ERROR: not found: {path}")

text = path.read_text()
marker = "NCCL_PORT_RANGE_PATCH_v1"

if marker in text:
    print(f"Patch already present: {path}")
    raise SystemExit(0)

old_helper = '''static uint16_t socketToPort(union ncclSocketAddress *addr) {
  struct sockaddr *saddr = &addr->sa;
  return ntohs(saddr->sa_family == AF_INET ? addr->sin.sin_port : addr->sin6.sin6_port);
}
'''

new_helper = '''static uint16_t socketToPort(union ncclSocketAddress *addr) {
  struct sockaddr *saddr = &addr->sa;
  return ntohs(saddr->sa_family == AF_INET ? addr->sin.sin_port : addr->sin6.sin6_port);
}

/* NCCL_PORT_RANGE_PATCH_v1
 *
 * Optional user-space listener port range for environments where compute
 * nodes can communicate only through an administrator-approved TCP range.
 *
 * When NCCL_PORT_MIN and NCCL_PORT_MAX are both set, ncclSocketListen()
 * binds port-0 listeners to the first available port in that inclusive
 * range. Explicit non-zero ports (for example from NCCL_COMM_ID) retain
 * the upstream behavior.
 */
static void socketSetPort(union ncclSocketAddress* addr, uint16_t port) {
  struct sockaddr* saddr = &addr->sa;
  if (saddr->sa_family == AF_INET) {
    addr->sin.sin_port = htons(port);
  } else if (saddr->sa_family == AF_INET6) {
    addr->sin6.sin6_port = htons(port);
  }
}

static ncclResult_t socketGetPortRange(int* minPort, int* maxPort, int* enabled) {
  const char* minValue = ncclGetEnv("NCCL_PORT_MIN");
  const char* maxValue = ncclGetEnv("NCCL_PORT_MAX");

  *enabled = 0;
  if (minValue == NULL && maxValue == NULL) return ncclSuccess;

  if (minValue == NULL || maxValue == NULL) {
    WARN("NCCL_PORT_MIN and NCCL_PORT_MAX must be set together");
    return ncclInvalidArgument;
  }

  char* minEnd = NULL;
  char* maxEnd = NULL;

  errno = 0;
  long minParsed = strtol(minValue, &minEnd, 10);
  if (errno != 0 || minEnd == minValue || *minEnd != '\\0') {
    WARN("Invalid NCCL_PORT_MIN value '%s'", minValue);
    return ncclInvalidArgument;
  }

  errno = 0;
  long maxParsed = strtol(maxValue, &maxEnd, 10);
  if (errno != 0 || maxEnd == maxValue || *maxEnd != '\\0') {
    WARN("Invalid NCCL_PORT_MAX value '%s'", maxValue);
    return ncclInvalidArgument;
  }

  if (minParsed < 1 || maxParsed > 65535 || minParsed > maxParsed) {
    WARN("Invalid NCCL port range %ld-%ld", minParsed, maxParsed);
    return ncclInvalidArgument;
  }

  *minPort = (int)minParsed;
  *maxPort = (int)maxParsed;
  *enabled = 1;
  return ncclSuccess;
}

static ncclResult_t socketBindPortRange(struct ncclSocket* sock, int minPort, int maxPort) {
  for (int port = minPort; port <= maxPort; port++) {
    socketSetPort(&sock->addr, (uint16_t)port);

    int ret = bind(sock->fd, &sock->addr.sa, sock->salen);
    if (ret == 0) {
      INFO(NCCL_ENV, "NCCL_PORT_RANGE bound listener to port %d", port);
      return ncclSuccess;
    }

    if (errno == EADDRINUSE) continue;

    WARN("NCCL_PORT_RANGE bind failed on port %d: %s", port, strerror(errno));
    return ncclSystemError;
  }

  WARN("NCCL_PORT_RANGE no free listener port in range %d-%d", minPort, maxPort);
  return ncclSystemError;
}
'''

if old_helper not in text:
    raise SystemExit("ERROR: socketToPort anchor not found; unexpected NCCL source")

text = text.replace(old_helper, new_helper, 1)

old_bind = '''  // addr port should be 0 (Any port)
  SYSCHECK(bind(sock->fd, &sock->addr.sa, sock->salen), "bind");

  /* Get the assigned Port */
'''

new_bind = '''  // Upstream behavior uses port 0 (kernel-selected ephemeral port).
  // If NCCL_PORT_MIN/MAX are configured, constrain only port-0 listeners.
  if (socketToPort(&sock->addr) == 0) {
    int minPort = 0;
    int maxPort = 0;
    int rangeEnabled = 0;
    NCCLCHECK(socketGetPortRange(&minPort, &maxPort, &rangeEnabled));

    if (rangeEnabled) {
      NCCLCHECK(socketBindPortRange(sock, minPort, maxPort));
    } else {
      SYSCHECK(bind(sock->fd, &sock->addr.sa, sock->salen), "bind");
    }
  } else {
    // Preserve explicit non-zero port behavior.
    SYSCHECK(bind(sock->fd, &sock->addr.sa, sock->salen), "bind");
  }

  /* Get the assigned Port */
'''

if old_bind not in text:
    raise SystemExit("ERROR: bind anchor not found; unexpected NCCL source")

backup = path.with_suffix(path.suffix + ".pre-nccl-port-range")
if not backup.exists():
    backup.write_text(text)

text = text.replace(old_bind, new_bind, 1)
path.write_text(text)

print(f"Patched: {path}")
print(f"Backup : {backup}")
print("New env vars: NCCL_PORT_MIN, NCCL_PORT_MAX")
