"""Independent text-distribution proof for Roadmap 274 browser PDFs."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


def verify_pdf(path: Path, *, numbered: bool) -> dict[str, object]:
    data = path.read_bytes()
    info = subprocess.run(["pdfinfo", str(path)], check=True, capture_output=True, text=True).stdout
    page_count = next(int(line.split(":", 1)[1]) for line in info.splitlines() if line.startswith("Pages:"))
    if page_count != 3:
        raise ValueError(f"{path.name}: expected three pages")
    pages = [
        subprocess.run(
            ["pdftotext", "-f", str(number), "-l", str(number), str(path), "-"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        for number in range(1, page_count + 1)
    ]
    if not all(value in pages[0] for value in ("FIRST-PAGE COVER", "FIRST-PAGE ONLY", "FIRST-PAGE-BODY")):
        raise ValueError(f"{path.name}: first-page profile or body is missing")
    if any(value in pages[0] for value in ("RUNNING-HEADER", "RUNNING-FOOTER")):
        raise ValueError(f"{path.name}: general running text leaked onto page one")
    if ("Seite 1 von 3" in pages[0]) is not numbered:
        raise ValueError(f"{path.name}: first-page number visibility is wrong")
    for index, body in ((1, "SECOND-PAGE-BODY"), (2, "THIRD-PAGE-BODY")):
        if not all(
            value in pages[index] for value in ("RUNNING-HEADER", "RUNNING-FOOTER", body, f"Seite {index + 1} von 3")
        ):
            raise ValueError(f"{path.name}: following-page running text or numbering is wrong")
        if any(value in pages[index] for value in ("FIRST-PAGE COVER", "FIRST-PAGE ONLY")):
            raise ValueError(f"{path.name}: first-page text leaked onto a following page")
    return {
        "file": path.name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "page_count": page_count,
        "first_page_number_visible": numbered,
        "following_page_numbers": [2, 3],
        "profile_separation_verified": True,
    }


def main() -> int:
    root = Path(sys.argv[1])
    evidence = []
    for project in ("desktop-chromium", "mobile-chromium"):
        evidence.append(verify_pdf(root / f"office-running-first-page-{project}.pdf", numbered=False))
        evidence.append(verify_pdf(root / f"office-running-first-page-numbered-{project}.pdf", numbered=True))
    print(json.dumps({"schema_version": "office_first_page_pdf_qa.v1", "files": evidence}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
