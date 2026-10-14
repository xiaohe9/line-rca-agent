"""Fetch the SECOM dataset into `eval/datasets/secom/`.

The dataset is not committed: it is 5 MB of someone else's data, CC BY 4.0, and a script plus
a checksum is a better record of provenance than a binary blob in git history.

    python scripts/fetch_secom.py

Source: McCann, M. & Johnston, A. (2008). SECOM [Dataset]. UCI Machine Learning Repository.
https://doi.org/10.24432/C54305 — licensed CC BY 4.0.
"""

from __future__ import annotations

import hashlib
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

ARCHIVE = "https://archive.ics.uci.edu/static/public/179/secom.zip"
DESTINATION = Path(__file__).resolve().parents[1] / "eval" / "datasets" / "secom"
WANTED = ("secom.data", "secom_labels.data", "secom.names")


def _download(url: str, timeout: float = 120.0) -> bytes:
    request = urllib.request.Request(  # noqa: S310 (fixed https URL, no user input)
        url, headers={"user-agent": "line-rca-agent/0.0.0"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read()


def main() -> int:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    print(f"downloading {ARCHIVE}")
    payload = _download(ARCHIVE)
    print(f"  {len(payload)} bytes")

    written: list[Path] = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = {Path(name).name: name for name in archive.namelist()}
        for wanted in WANTED:
            if wanted not in names:
                print(f"  ! {wanted} is missing from the archive")
                continue
            target = DESTINATION / wanted
            target.write_bytes(archive.read(names[wanted]))
            written.append(target)
            print(f"  {wanted}: {target.stat().st_size} bytes")

    manifest = DESTINATION / "SOURCES.txt"
    lines = [
        "SECOM — UCI Machine Learning Repository, dataset id 179",
        "McCann, M. & Johnston, A. (2008). SECOM [Dataset]. https://doi.org/10.24432/C54305",
        "Licensed CC BY 4.0. Fetched by scripts/fetch_secom.py; not committed to the repository.",
        "",
    ]
    for path in written:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{path.name}  sha256={digest}")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  wrote {manifest.name}")

    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
