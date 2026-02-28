#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

TARGET_USER="${SUDO_USER:-${1:-}}"
if [[ -z "${TARGET_USER}" ]]; then
  echo "Target user is required. Example: sudo $0 den" >&2
  exit 1
fi

if ! id "${TARGET_USER}" >/dev/null 2>&1; then
  echo "User not found: ${TARGET_USER}" >&2
  exit 1
fi

echo "[1/5] Installing virtualization packages..."
pacman -S --needed --noconfirm qemu-desktop libvirt edk2-ovmf virt-install swtpm dnsmasq

echo "[2/5] Enabling libvirt sockets..."
systemctl enable --now virtqemud.socket
systemctl enable --now virtnetworkd.socket

echo "[3/5] Adding user '${TARGET_USER}' to kvm/libvirt groups..."
usermod -aG kvm,libvirt "${TARGET_USER}"

echo "[4/5] Ensuring default libvirt network exists and is active..."
if ! virsh -c qemu:///system net-info default >/dev/null 2>&1; then
  if [[ -f /usr/share/libvirt/networks/default.xml ]]; then
    virsh -c qemu:///system net-define /usr/share/libvirt/networks/default.xml
  fi
fi
virsh -c qemu:///system net-autostart default || true
virsh -c qemu:///system net-start default || true

echo "[5/5] Creating VM storage directory for ${TARGET_USER}..."
install -d -m 0755 -o "${TARGET_USER}" -g "${TARGET_USER}" "/home/${TARGET_USER}/vms/windows-gate"

echo ""
echo "Host root setup complete."
echo "IMPORTANT: user '${TARGET_USER}' must log out/in (or reboot) to apply new group membership."
