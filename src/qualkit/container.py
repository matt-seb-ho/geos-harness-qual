"""One container invocation, rendered for docker or enroot.

The lab servers withdrew docker access (the daemon socket is root-only) and
point users at enroot instead. The container is used only for filesystem
isolation and a reproducible toolchain -- never for anything privileged -- so
enroot is a straight substitute. Rather than fork the command builder, it emits
a :class:`ContainerSpec` and a renderer turns it into argv.

Pick the backend with ``QUAL_CONTAINER_BACKEND=docker|enroot``. The default is
enroot, because that is what works on the machine you were most likely given.

Differences the renderers absorb, so you do not have to think about them:

``--user uid:gid``
    docker needs it or the container writes root-owned files into your
    workspace. enroot is unprivileged by construction and has no equivalent.

mount syntax
    docker's ``-v src:dst:ro`` becomes enroot's fstab form. ``x-create=dir``
    matters: the enroot rootfs is read-only, so a mountpoint that does not
    already exist in the image cannot be created implicitly the way docker
    does it.

WORKDIR
    docker honours the image's ``WORKDIR``; enroot does not read the OCI config
    at start time, so the renderer wraps the command in a ``cd``.

``$HOME`` must exist
    enroot chdirs into ``$HOME`` while entering the container and aborts if it
    is missing. ``prepare_workspace`` creates it on the host, which is inside
    the bind mount and therefore inside the container.
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path

DOCKER, ENROOT = "docker", "enroot"
_VALID_BACKENDS = (DOCKER, ENROOT)

#: Image tag (docker) / container name (enroot). Built from ``run/Dockerfile``
#: in the SIGA repo; on the lab server it already exists under this name.
IMAGE = os.environ.get("QUAL_CONTAINER_IMAGE", "geos-eval")

WORKDIR = "/workspace"


def active_backend() -> str:
    backend = os.environ.get("QUAL_CONTAINER_BACKEND", ENROOT).strip().lower()
    if backend not in _VALID_BACKENDS:
        raise ValueError(f"QUAL_CONTAINER_BACKEND={backend!r} not in {_VALID_BACKENDS}")
    return backend


@dataclass(frozen=True)
class Mount:
    source: Path | str
    target: Path | str
    read_only: bool = False


@dataclass
class ContainerSpec:
    image: str
    argv: list[str]
    mounts: list[Mount] = field(default_factory=list)
    #: ``VAR`` forwards the host value; ``VAR=value`` sets it explicitly.
    env: list[str] = field(default_factory=list)
    workdir: str | None = WORKDIR

    def render(self, backend: str | None = None) -> list[str]:
        backend = backend or active_backend()
        return {DOCKER: render_docker, ENROOT: render_enroot}[backend](self)


def render_docker(spec: ContainerSpec) -> list[str]:
    cmd = ["docker", "run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}"]
    for m in spec.mounts:
        cmd += ["-v", f"{m.source}:{m.target}{':ro' if m.read_only else ':rw'}"]
    for e in spec.env:
        cmd += ["-e", e]
    cmd += [spec.image, *spec.argv]
    return cmd


def render_enroot(spec: ContainerSpec) -> list[str]:
    cmd = ["enroot", "start"]
    for m in spec.mounts:
        flags = ["none", "bind", "ro" if m.read_only else "rw", "x-create=dir"]
        cmd += ["--mount", f"{m.source}:{m.target}:{','.join(flags)}"]
    for e in spec.env:
        cmd += ["--env", e]
    cmd += [str(spec.image)]
    if spec.workdir:
        # The argv may legitimately contain a leading `--`, so wrap rather than
        # prepend a cd.
        inner = " ".join(shlex.quote(a) for a in spec.argv)
        cmd += ["sh", "-c", f"cd {shlex.quote(spec.workdir)} && exec {inner}"]
    else:
        cmd += spec.argv
    return cmd


def prepare_workspace(workspace: Path) -> Path:
    """Create the directories the container expects to already exist.

    Safe and idempotent under docker; required under enroot.
    """
    workspace = Path(workspace)
    for sub in ("inputs", "outputs", ".claude_home", ".claude_home/.config", ".uv_cache"):
        (workspace / sub).mkdir(parents=True, exist_ok=True)
    return workspace


def preflight() -> list[str]:
    """Every reason this machine cannot run a rollout, collected rather than raised.

    Returned as a list on purpose: fixing these one crash at a time costs a run
    each, and you may reasonably decide to develop against the mock runner
    instead.
    """
    import shutil
    import subprocess

    problems: list[str] = []
    backend = active_backend()
    if shutil.which(backend) is None:
        problems.append(f"{backend} is not on PATH (set QUAL_CONTAINER_BACKEND)")
        return problems
    if backend == DOCKER:
        probe = subprocess.run(["docker", "info"], capture_output=True, text=True)
        if probe.returncode != 0:
            problems.append(
                "docker binary is present but the daemon is not reachable: "
                f"`docker info` exited {probe.returncode}. On the lab servers use "
                "QUAL_CONTAINER_BACKEND=enroot."
            )
    else:
        probe = subprocess.run(["enroot", "list"], capture_output=True, text=True)
        if probe.returncode != 0:
            problems.append(f"`enroot list` exited {probe.returncode}: {probe.stderr.strip()[:200]}")
        elif IMAGE not in probe.stdout.split():
            problems.append(
                f"enroot container {IMAGE!r} does not exist. Build it with "
                f"`bash run/build_enroot_image.sh` in the SIGA repo, or set "
                f"QUAL_CONTAINER_IMAGE."
            )
    if not os.environ.get("OPENROUTER_API_KEY"):
        problems.append("OPENROUTER_API_KEY is not set (copy .env.example to .env)")
    return problems
