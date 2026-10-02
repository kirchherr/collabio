# Remote Development Host

The source workspace and Codex session may stay on the operator workstation while the Docker Compose runtime runs on a dedicated Linux host. Docker's unauthenticated TCP socket must not be exposed. Administration and application access use SSH.

## Trust boundary

- Use a dedicated SSH key for the development host.
- Keep the Docker daemon on its local Unix socket. Never expose port `2375`.
- Grant Docker group membership only to trusted development operators; it is equivalent to root access on the host.
- Keep published Compose ports on `127.0.0.1`, which is the default through `SUITE_BIND_ADDRESS`.
- Use a separate, read-only source checkout on the runtime host. Development commits and pushes remain on the operator workstation.
- Do not copy GitHub write keys, production secrets, customer data, or production backups to the development host.

## Host checkout

```bash
git clone --branch kirchherr/kb-write-unit-of-work --single-branch \
  https://github.com/kirchherr/collabio.git ~/collabio
cd ~/collabio
docker compose config --quiet
docker compose build
docker compose run --rm quality
docker compose up -d api
```

For later updates, first push the workstation branch and then fast-forward the host checkout:

```bash
cd ~/collabio
git pull --ff-only
docker compose build
docker compose run --rm quality
docker compose up -d api
```

## Operator access

Create an SSH tunnel from the operator workstation. This exposes only the selected remote loopback ports on the workstation:

```powershell
ssh -N -i $HOME\.ssh\id_ed25519_collabio_dev001 `
  -L 8000:127.0.0.1:8000 `
  -L 29001:127.0.0.1:29001 `
  extern@dev001
```

The API is then available at `http://127.0.0.1:8000`; the MinIO development console is available at `http://127.0.0.1:29001`.

To deliberately publish a service to an explicitly protected network interface, set `SUITE_BIND_ADDRESS` to that host address. `0.0.0.0` requires a documented firewall and access-control review.

## Verification

```bash
docker compose ps
docker compose logs --tail=100 api
curl --fail http://127.0.0.1:8000/health
ss -lnt
```

Expected published listeners bind to `127.0.0.1`; no Compose service should expose a host listener on `0.0.0.0` by default.

## Recovery

Runtime state remains in named Docker volumes and follows the suite-wide backup and restore policy in `docs/operations/BACKUP_FAILOVER.md`. Re-cloning source code is not a data recovery mechanism. Before the host carries non-disposable data, configure backup export to storage outside the host and exercise the documented restore drills.
