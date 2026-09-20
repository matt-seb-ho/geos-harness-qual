#!/usr/bin/env bash
# Build the `geos-eval` container image for enroot, without docker.
#
# The lab servers withdrew docker access (the daemon socket is root-only) and
# point users at enroot instead. enroot cannot execute a Dockerfile, so this
# reproduces run/Dockerfile's RUN steps inside an unprivileged container and
# exports the result as squashfs. If you *do* have a docker daemon, you do not
# need this script:
#
#   docker build -t geos-eval -f run/Dockerfile run/
#   export QUAL_CONTAINER_BACKEND=docker
#
# Otherwise:
#
#   bash run/build_enroot_image.sh            # build to the default location
#   bash run/build_enroot_image.sh --force    # rebuild over an existing image
#
# Output: ~/.local/share/enroot/images/geos-eval.sqsh
#         (override with $QUAL_ENROOT_IMAGE)
#
# Takes several minutes, mostly pulling node and the npm packages.
set -euo pipefail

BASE_URI="docker://ubuntu:24.04"
BUILD_NAME="geos-eval-build"
OUT="${QUAL_ENROOT_IMAGE:-$HOME/.local/share/enroot/images/geos-eval.sqsh}"
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

command -v enroot >/dev/null || { echo "enroot not found on PATH" >&2; exit 1; }
mkdir -p "$(dirname "$OUT")"

if [ -f "$OUT" ] && [ "$FORCE" -eq 0 ]; then
  echo "image already exists: $OUT  (use --force to rebuild)"; exit 0
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cd "$WORK"

echo "==> importing $BASE_URI"
enroot import -o base.sqsh "$BASE_URI"

echo "==> creating build container"
enroot remove -f "$BUILD_NAME" 2>/dev/null || true
enroot create --name "$BUILD_NAME" base.sqsh

# The Dockerfile's RUN steps, verbatim in intent. Run as root inside the
# container (--root is a *namespace* remap, not host privilege) with a writable
# rootfs (--rw), which is what `docker build` gave us.
cat > provision.sh <<'PROVISION'
set -eux
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y curl git python3 python3-pip ca-certificates gnupg libxml2-utils
rm -rf /var/lib/apt/lists/*

# Node.js 22.x -- acpx requires >= 22.12.0
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get install -y nodejs
rm -rf /var/lib/apt/lists/*

# cursor-agent
curl -fsSL https://cursor.com/install | bash

# uv, in /usr/local/bin so a non-root container user can execute it
export UV_INSTALL_DIR=/usr/local/bin
curl -LsSf https://astral.sh/uv/install.sh | sh

npm install -g @anthropic-ai/claude-code
npm install -g acpx@latest

mkdir -p /workspace

# The Dockerfile sets ENV PATH="/root/.local/bin:${PATH}". enroot does not read
# the OCI config at start time, so persist it where a login shell will find it.
echo 'export PATH="/root/.local/bin:/usr/local/bin:$PATH"' > /etc/profile.d/geos-eval.sh
chmod 0644 /etc/profile.d/geos-eval.sh

# The three mountpoints a rollout uses (qualkit/rollout.py). They must exist:
# the rootfs is read-only at run time, and although the renderer passes
# x-create=dir, pre-creating them keeps failures legible.
mkdir -p /geos_lib /harness
PROVISION

echo "==> provisioning (this pulls node + npm packages; several minutes)"
# x-create=dir: /build does not exist in the base image, and enroot -- unlike
# docker -- will not create a missing mountpoint implicitly.
enroot start --root --rw --mount "$WORK:/build:none,bind,ro,x-create=dir" "$BUILD_NAME" \
    bash /build/provision.sh

echo "==> exporting to $OUT"
enroot export --force --output "$OUT" "$BUILD_NAME"
enroot remove -f "$BUILD_NAME"

# The kit starts a *named container*, not the .sqsh: `enroot start IMG.sqsh`
# needs squashfuse to fuse-mount, and squashfuse is not installed on the lab
# servers (installing it needs admin). `enroot create` unpacks with unsquashfs,
# which is present. The unpacked rootfs is read-only at start, so concurrent
# starts are safe -- verified with three simultaneous starts, which matters
# whenever you evaluate with more than one worker.
RUNTIME_NAME="${QUAL_CONTAINER_IMAGE:-geos-eval}"
echo "==> creating runtime container '$RUNTIME_NAME'"
enroot remove -f "$RUNTIME_NAME" 2>/dev/null || true
enroot create --name "$RUNTIME_NAME" "$OUT"

echo
echo "done."
echo "  image:     $OUT"
echo "  container: $RUNTIME_NAME  (enroot list)"
echo
echo "smoke test:"
echo "  enroot start $RUNTIME_NAME sh -lc 'claude --version; uv --version; xmllint --version'"
echo
echo "then check the kit agrees:"
echo "  QUAL_CONTAINER_BACKEND=enroot qual doctor"
