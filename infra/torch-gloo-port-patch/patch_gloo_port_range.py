#!/usr/bin/env python3
from pathlib import Path
import subprocess
import sys

EXPECTED_GLOO = "5354032ea08eadd7fc4456477f7f7c6308818509"
TARGET = Path("third_party/gloo/gloo/transport/tcp/listener.cc")
MARKER = "GLOO_PORT_MIN"

HELPER = r'''
namespace {

long parseGlooPort(const char* name, const char* value) {
  errno = 0;
  char* end = nullptr;
  const long port = std::strtol(value, &end, 10);
  GLOO_ENFORCE(
      errno == 0 && end != value && *end == '\0' &&
          port >= 1 && port <= 65535,
      "Invalid ",
      name,
      ": ",
      value);
  return port;
}

void setPort(struct sockaddr_storage& addr, uint16_t port) {
  if (addr.ss_family == AF_INET) {
    auto* a = reinterpret_cast<struct sockaddr_in*>(&addr);
    a->sin_port = htons(port);
    return;
  }
  if (addr.ss_family == AF_INET6) {
    auto* a = reinterpret_cast<struct sockaddr_in6*>(&addr);
    a->sin6_port = htons(port);
    return;
  }
  GLOO_ENFORCE(false, "Unsupported address family: ", addr.ss_family);
}

socklen_t addressLength(const struct sockaddr_storage& addr) {
  if (addr.ss_family == AF_INET) {
    return sizeof(struct sockaddr_in);
  }
  if (addr.ss_family == AF_INET6) {
    return sizeof(struct sockaddr_in6);
  }
  GLOO_ENFORCE(false, "Unsupported address family: ", addr.ss_family);
  return 0;
}

void bindListenerInConfiguredRange(
    std::shared_ptr<Socket>& listener,
    const struct sockaddr_storage& baseAddr) {
  const char* minValue = std::getenv("GLOO_PORT_MIN");
  const char* maxValue = std::getenv("GLOO_PORT_MAX");

  GLOO_ENFORCE(
      (minValue == nullptr) == (maxValue == nullptr),
      "GLOO_PORT_MIN and GLOO_PORT_MAX must be set together");

  if (minValue == nullptr) {
    listener->bind(baseAddr);
    return;
  }

  const long minPort = parseGlooPort("GLOO_PORT_MIN", minValue);
  const long maxPort = parseGlooPort("GLOO_PORT_MAX", maxValue);
  GLOO_ENFORCE_LE(minPort, maxPort);

  int lastErrno = 0;

  for (long port = minPort; port <= maxPort; ++port) {
    auto addr = baseAddr;
    setPort(addr, static_cast<uint16_t>(port));

    auto candidate = Socket::createForFamily(addr.ss_family);
    candidate->reuseAddr(true);

    const auto rv = ::bind(
        candidate->fd(),
        reinterpret_cast<const struct sockaddr*>(&addr),
        addressLength(addr));

    if (rv == 0) {
      listener = std::move(candidate);
      std::fprintf(
          stderr,
          "[GLOO_PORT_RANGE] pid=%d bound listener port=%ld range=%ld-%ld\n",
          static_cast<int>(::getpid()),
          port,
          minPort,
          maxPort);
      std::fflush(stderr);
      return;
    }

    lastErrno = errno;

    if (lastErrno == EADDRINUSE) {
      continue;
    }

    GLOO_ENFORCE(
        false,
        "Gloo listener bind failed for port ",
        port,
        ": ",
        std::strerror(lastErrno));
  }

  GLOO_ENFORCE(
      false,
      "No free Gloo listener port in configured range ",
      minPort,
      "-",
      maxPort,
      "; last error: ",
      std::strerror(lastErrno));
}

} // namespace
'''

def run(*args):
    return subprocess.check_output(args, text=True).strip()

def main():
    repo = Path.cwd()
    target = repo / TARGET

    if not target.exists():
        sys.exit(f"ERROR: run this from the PyTorch repo root; missing {TARGET}")

    actual = run(
        "git", "-C", str(repo / "third_party/gloo"), "rev-parse", "HEAD"
    )
    if actual != EXPECTED_GLOO:
        sys.exit(
            "ERROR: unexpected Gloo commit.\n"
            f"expected: {EXPECTED_GLOO}\n"
            f"actual:   {actual}"
        )

    text = target.read_text()
    if MARKER in text:
        print("Patch already present:", target)
        return

    include_anchor = "#include <unistd.h>\n"
    if include_anchor not in text:
        sys.exit("ERROR: include anchor not found")

    text = text.replace(
        include_anchor,
        include_anchor
        + "#include <cerrno>\n"
        + "#include <cstdio>\n"
        + "#include <cstdlib>\n"
        + "#include <cstring>\n",
        1,
    )

    constructor_anchor = "Listener::Listener("
    idx = text.find(constructor_anchor)
    if idx < 0:
        sys.exit("ERROR: Listener constructor anchor not found")

    text = text[:idx] + HELPER + "\n" + text[idx:]

    bind_line = "  listener_->bind(attr.ai_addr);\n"
    if text.count(bind_line) != 1:
        sys.exit(
            f"ERROR: expected one listener bind line; found {text.count(bind_line)}"
        )

    text = text.replace(
        bind_line,
        "  bindListenerInConfiguredRange(listener_, attr.ai_addr);\n",
        1,
    )

    target.write_text(text)
    print("Patched:", target)
    print("Added env vars: GLOO_PORT_MIN, GLOO_PORT_MAX")
    print("Gloo commit:", actual)

if __name__ == "__main__":
    main()
