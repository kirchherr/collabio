from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]
PROFILE_PATH = REPO_ROOT / "security" / "apparmor" / "usr.bin.runsc"
INSTALLER_PATH = REPO_ROOT / "security" / "apparmor" / "install-runsc-profile.sh"
VERIFIER_PATH = REPO_ROOT / "security" / "apparmor" / "verify-runsc-profile.sh"
KVM_HOST_PATH = REPO_ROOT / "security" / "gvisor" / "runsc_kvm_host.py"
KVM_INSTALLER_PATH = REPO_ROOT / "security" / "gvisor" / "install-runsc-kvm-runtime.py"
KVM_VERIFIER_PATH = REPO_ROOT / "security" / "gvisor" / "verify-runsc-kvm-runtime.py"


def test_runsc_profile_is_path_bound_and_keeps_global_restriction() -> None:
    profile = PROFILE_PATH.read_text(encoding="utf-8")

    assert "/usr/bin/runsc flags=(default_allow)" in profile
    assert "  userns," in profile
    assert "unconfined" not in profile
    assert "capability," not in profile
    assert "network," not in profile


def test_runsc_profile_scripts_are_valid_fail_closed_shell() -> None:
    for script_path in (INSTALLER_PATH, VERIFIER_PATH):
        subprocess.run(["sh", "-n", str(script_path)], check=True)

    installer = INSTALLER_PATH.read_text(encoding="utf-8")
    verifier = VERIFIER_PATH.read_text(encoding="utf-8")
    assert "requires root" in installer
    assert "refusing to overwrite" in installer
    assert "apparmor_parser --replace --skip-cache --Werror" in installer
    assert "systemctl" not in installer
    assert "sysctl" not in installer
    assert "apparmor_restrict_unprivileged_userns" in verifier
    assert "apparmor_restrict_unprivileged_unconfined" in verifier
    assert "genoffice_runsc_host_profile_verification.v1" in verifier


def test_runsc_kvm_installer_is_additive_atomic_and_reload_only() -> None:
    host_module = KVM_HOST_PATH.read_text(encoding="utf-8")
    installer = KVM_INSTALLER_PATH.read_text(encoding="utf-8")
    verifier = KVM_VERIFIER_PATH.read_text(encoding="utf-8")

    assert '"runsc-kvm"' in host_module
    assert '["--platform=kvm"]' in host_module
    assert "daemon.json.collabio-pre-runsc-kvm" in host_module
    assert '"dockerd", "--validate"' in host_module
    assert "os.replace" in host_module
    assert '_run("systemctl", "reload", "docker")' in host_module
    assert '"restart"' not in host_module
    assert "_assert_containers_preserved(before)" in host_module
    assert "runtime_authorization_granted" in host_module
    assert "install_runsc_kvm_runtime()" in installer
    assert "verify_runsc_kvm_runtime()" in verifier


def test_runsc_host_verifiers_require_root_and_never_disable_userns_hardening() -> None:
    profile_verifier = VERIFIER_PATH.read_text(encoding="utf-8")
    kvm_host = KVM_HOST_PATH.read_text(encoding="utf-8")

    assert "verification requires root" in profile_verifier
    assert "os.geteuid() != 0" in kvm_host
    assert "apparmor_restrict_unprivileged_userns" in kvm_host
    assert "apparmor_restrict_unprivileged_unconfined" in kvm_host
    assert "sysctl" not in kvm_host


def test_backup_policy_carries_runsc_host_profile_without_global_disable() -> None:
    policy = json.loads((REPO_ROOT / "docs" / "operations" / "backup_failover_policy.json").read_text())
    office_documents = next(item for item in policy["continuity_domains"] if item["domain_id"] == "office_documents")
    object_storage = next(item for item in policy["targets"] if item["target_id"] == "object_storage_records")

    assert any("runsc AppArmor profile" in item for item in office_documents["state_artifacts"])
    assert any("runsc-kvm Docker runtime" in item for item in office_documents["state_artifacts"])
    assert (
        "genoffice_runsc_apparmor_profile_exact_byte_and_loaded_state_check"
        in object_storage["restore_verification_gates"]
    )
    assert (
        "genoffice_runsc_global_apparmor_userns_restrictions_enabled_check"
        in object_storage["restore_verification_gates"]
    )
    assert "genoffice_runsc_kvm_additive_runtime_argument_check" in object_storage["restore_verification_gates"]
    assert "apparmor_restrict_unprivileged_userns=0" not in json.dumps(policy)
