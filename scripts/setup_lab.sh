#!/usr/bin/env bash
# Set up the ReverseAI lab on a fresh Debian/Ubuntu host.
# Installs the sandbox + analysis system dependencies and the optional Python
# power-ups. The core runs without any of this; these make it stronger.
set -euo pipefail

echo "==> System packages (sandbox + binutils + compiler)"
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y bubblewrap binutils gcc qemu-user qemu-system-x86 || true
else
  echo "    (non-apt host: install bubblewrap, binutils, gcc manually)"
fi

echo "==> Enable unprivileged user namespaces (needed by bubblewrap)"
sudo sysctl -w kernel.unprivileged_userns_clone=1 2>/dev/null || true

echo "==> Optional Python analysis/emulation libraries"
python3 -m pip install --user lief capstone pyelftools || \
  echo "    (lief/capstone/pyelftools install skipped or failed — core still works)"
echo "    (qiling is heavy; install separately with: pip install qiling)"

echo "==> Capability check"
python3 -m reverseai caps || true

echo "Done. Set DEEPSEEK_API_KEY to enable the agent."
