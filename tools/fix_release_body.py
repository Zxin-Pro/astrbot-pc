# -*- coding: utf-8 -*-
"""按 release.py 的模板重写已有 Release 的正文（不重建、不动资产）。

用法：
    python -X utf8 tools/fix_release_body.py pc-v1.3.1
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from tools.release import BODY, HEADERS, NAME, REPO  # noqa: E402


def main() -> int:
    tag = sys.argv[1] if len(sys.argv) > 1 else "pc-v1.3.1"
    url = f"https://api.github.com/repos/{REPO}/releases/tags/{tag}"
    req = urllib.request.Request(url, headers=HEADERS)
    rel = json.load(urllib.request.urlopen(req, timeout=60))

    payload = json.dumps({"body": BODY.format(name=NAME)}).encode()
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/releases/{rel['id']}",
        data=payload,
        headers={**HEADERS, "Content-Type": "application/json"},
        method="PATCH",
    )
    out = json.load(urllib.request.urlopen(req, timeout=60))
    print("updated:", out["html_url"])
    print("head:", out["body"].splitlines()[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
