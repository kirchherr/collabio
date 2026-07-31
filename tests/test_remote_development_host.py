from pathlib import Path


REPO_ROOT = Path(__file__).parents[1]
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
RUNBOOK_PATH = REPO_ROOT / "docs" / "operations" / "REMOTE_DEVELOPMENT_HOST.md"


def test_all_compose_host_ports_default_to_loopback() -> None:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    published_ports = [
        line.strip()
        for line in compose.splitlines()
        if line.strip().startswith('- "${SUITE_') and line.rstrip().endswith('"')
    ]

    assert published_ports
    assert all(
        mapping.startswith('- "${SUITE_BIND_ADDRESS:-127.0.0.1}:')
        for mapping in published_ports
    )
    assert '"${SUITE_API_PORT:-8000}:8000"' not in compose
    assert '"${SUITE_POSTGRES_PORT:-5433}:5432"' not in compose


def test_remote_host_runbook_forbids_unauthenticated_docker_tcp() -> None:
    runbook = RUNBOOK_PATH.read_text(encoding="utf-8")

    assert "Never expose port `2375`" in runbook
    assert "SSH tunnel" in runbook
    assert "SUITE_BIND_ADDRESS" in runbook
    assert "BACKUP_FAILOVER.md" in runbook
