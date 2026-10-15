#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from runsc_kvm_host import RunscKvmHostError, install_runsc_kvm_runtime

try:
    install_runsc_kvm_runtime()
except RunscKvmHostError as exc:
    raise SystemExit(str(exc)) from exc

print("runsc-kvm Docker runtime installed and registered")
