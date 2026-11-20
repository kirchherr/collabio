from __future__ import annotations

import grp
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

DAEMON_CONFIG_PATH = Path("/etc/docker/daemon.json")
DAEMON_BACKUP_PATH = Path("/etc/docker/daemon.json.collabio-pre-runsc-kvm")
RUNSC_PATH = Path("/usr/bin/runsc")
APPARMOR_PROFILE_PATH = Path("/etc/apparmor.d/usr.bin.runsc")
APPARMOR_PROFILE_SOURCE = Path(__file__).parents[1] / "apparmor" / "usr.bin.runsc"
DESIRED_RUNTIME = {"path": str(RUNSC_PATH), "runtimeArgs": ["--platform=kvm"]}


class RunscKvmHostError(RuntimeError):
    pass


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, capture_output=True, text=True)


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _load_daemon_config(path: Path = DAEMON_CONFIG_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RunscKvmHostError(f"Docker daemon configuration is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise RunscKvmHostError("Docker daemon configuration must be an object")
    runtimes = value.get("runtimes")
    if not isinstance(runtimes, dict):
        raise RunscKvmHostError("Docker daemon runtimes configuration is missing")
    if runtimes.get("runsc") != {"path": str(RUNSC_PATH)}:
        raise RunscKvmHostError("existing runsc runtime configuration drifted")
    return value


def _assert_root() -> None:
    if os.geteuid() != 0:
        raise RunscKvmHostError("runsc-kvm host operation requires root")


def _assert_package_managed_runsc() -> str:
    owner = _run("dpkg-query", "-S", str(RUNSC_PATH)).stdout.strip()
    if owner != "runsc: /usr/bin/runsc":
        raise RunscKvmHostError("/usr/bin/runsc is not owned by the runsc Debian package")
    metadata = RUNSC_PATH.stat()
    if metadata.st_uid != 0 or metadata.st_gid != 0 or stat.S_IMODE(metadata.st_mode) != 0o755:
        raise RunscKvmHostError("/usr/bin/runsc ownership or mode is unexpected")
    return _run("dpkg-query", "-W", "-f=${Version}", "runsc").stdout.strip()


def _assert_apparmor_boundary() -> tuple[str, bool]:
    if not APPARMOR_PROFILE_SOURCE.is_file() or not APPARMOR_PROFILE_PATH.is_file():
        raise RunscKvmHostError("runsc AppArmor profile is missing")
    if APPARMOR_PROFILE_SOURCE.read_bytes() != APPARMOR_PROFILE_PATH.read_bytes():
        raise RunscKvmHostError("installed runsc AppArmor profile drifted")
    profiles = Path("/sys/kernel/security/apparmor/profiles").read_text(encoding="utf-8")
    if "/usr/bin/runsc (" not in profiles:
        raise RunscKvmHostError("runsc AppArmor profile is not loaded")
    if Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns").read_text().strip() != "1":
        raise RunscKvmHostError("global AppArmor unprivileged-userns restriction must remain enabled")
    unconfined_restriction_enabled = (
        Path("/proc/sys/kernel/apparmor_restrict_unprivileged_unconfined").read_text().strip() == "1"
    )
    return _sha256(APPARMOR_PROFILE_SOURCE), unconfined_restriction_enabled


def _assert_kvm_host() -> None:
    virtualization = _run("systemd-detect-virt", check=False).stdout.strip()
    if virtualization != "none":
        raise RunscKvmHostError("runsc-kvm is permitted only on verified bare metal")
    metadata = Path("/dev/kvm").stat()
    if not stat.S_ISCHR(metadata.st_mode) or grp.getgrgid(metadata.st_gid).gr_name != "kvm":
        raise RunscKvmHostError("/dev/kvm is not the expected kvm character device")
    modules = Path("/proc/modules").read_text(encoding="utf-8")
    if "kvm " not in modules or not any(name in modules for name in ("kvm_intel ", "kvm_amd ")):
        raise RunscKvmHostError("KVM kernel modules are not loaded")


def _running_containers() -> set[tuple[str, str]]:
    output = _run("docker", "ps", "--format", "{{.ID}}\t{{.Names}}").stdout
    containers: set[tuple[str, str]] = set()
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", maxsplit=1)
        if len(parts) != 2:
            raise RunscKvmHostError("Docker container inventory output is malformed")
        containers.add((parts[0], parts[1]))
    return containers


def _assert_containers_preserved(before: set[tuple[str, str]]) -> None:
    after = _running_containers()
    missing = sorted(before - after)
    if missing:
        raise RunscKvmHostError(f"Docker reload removed running containers: {missing}")


def _runtime_registered() -> bool:
    value = json.loads(_run("docker", "info", "--format", "{{json .Runtimes}}").stdout)
    return isinstance(value, dict) and "runsc-kvm" in value


def install_runsc_kvm_runtime() -> None:
    _assert_root()
    _assert_package_managed_runsc()
    _assert_apparmor_boundary()
    _assert_kvm_host()
    config = _load_daemon_config()
    runtimes = config["runtimes"]
    existing = runtimes.get("runsc-kvm")
    if existing is not None and existing != DESIRED_RUNTIME:
        raise RunscKvmHostError("existing runsc-kvm runtime configuration drifted")
    if existing == DESIRED_RUNTIME and _runtime_registered():
        return
    if DAEMON_BACKUP_PATH.exists():
        raise RunscKvmHostError(f"rollback backup already exists: {DAEMON_BACKUP_PATH}")

    before = _running_containers()
    shutil.copy2(DAEMON_CONFIG_PATH, DAEMON_BACKUP_PATH)
    os.chmod(DAEMON_BACKUP_PATH, 0o600)
    runtimes["runsc-kvm"] = DESIRED_RUNTIME
    serialized = f"{json.dumps(config, indent=4, sort_keys=True)}\n".encode()
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=DAEMON_CONFIG_PATH.parent, delete=False) as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        os.chmod(temporary_path, 0o644)
        _run("dockerd", "--validate", f"--config-file={temporary_path}")
        os.replace(temporary_path, DAEMON_CONFIG_PATH)
        temporary_path = None
        _run("systemctl", "reload", "docker")
        for _ in range(20):
            if _runtime_registered():
                break
            time.sleep(0.25)
        else:
            raise RunscKvmHostError("runsc-kvm runtime was not registered after Docker reload")
        _assert_containers_preserved(before)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        shutil.copy2(DAEMON_BACKUP_PATH, DAEMON_CONFIG_PATH)
        os.chmod(DAEMON_CONFIG_PATH, 0o644)
        _run("systemctl", "reload", "docker", check=False)
        raise


def verify_runsc_kvm_runtime() -> dict[str, object]:
    _assert_root()
    runsc_version = _assert_package_managed_runsc()
    profile_sha256, unconfined_restriction_enabled = _assert_apparmor_boundary()
    _assert_kvm_host()
    config = _load_daemon_config()
    if config["runtimes"].get("runsc-kvm") != DESIRED_RUNTIME:
        raise RunscKvmHostError("runsc-kvm daemon configuration is missing or drifted")
    if not _runtime_registered():
        raise RunscKvmHostError("runsc-kvm is not registered in Docker")
    return {
        "schema_version": "genoffice_runsc_kvm_host_verification.v1",
        "apparmor_profile_sha256": profile_sha256,
        "daemon_config_sha256": _sha256(DAEMON_CONFIG_PATH),
        "runsc_package_version": runsc_version,
        "runtime_name": "runsc-kvm",
        "platform": "kvm",
        "bare_metal_verified": True,
        "kvm_device_verified": True,
        "package_managed": True,
        "profile_loaded": True,
        "global_userns_restriction_enabled": True,
        "global_unconfined_restriction_enabled": unconfined_restriction_enabled,
        "docker_runtime_registered": True,
        "tenant_content_included": False,
        "runtime_authorization_granted": False,
    }
