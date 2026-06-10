import os
from pathlib import Path


def suite_data_dir() -> Path:
    return Path(os.getenv("SUITE_DATA_DIR", "data"))
