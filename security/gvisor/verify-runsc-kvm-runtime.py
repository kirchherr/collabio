#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from runsc_kvm_host import RunscKvmHostError, verify_runsc_kvm_runtime

try:
    report = verify_runsc_kvm_runtime()
except RunscKvmHostError as exc:
    raise SystemExit(str(exc)) from exc

print(json.dumps(report, sort_keys=True, separators=(",", ":")))
