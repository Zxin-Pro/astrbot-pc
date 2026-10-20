"""把任意文件传到某个 Release 当资产。

    set GITHUB_TOKEN=ghp_xxx
    python tools/upload_asset.py dist\\AstrBotPC-1.0.0-win64-single.exe --tag pc-v1.0.0
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = "Zxin-Pro/astrbot-pc"
TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "User-Agent": "AstrBotPC-release",
    "Accept": "application/vnd.github+json",
}


def call(method: str, url: str, payload: dict | None = None, ctype: str = "application/json",
         raw: bytes | None = None, timeout: int = 60) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else raw
    headers = dict(HEADERS)
    headers["Content-Type"] = ctype
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--tag", default="pc-v1.0.0")
    ap.add_argument("--name", default="")
    args = ap.parse_args()

    if not TOKEN:
        print("GITHUB_TOKEN 没有设置", file=sys.stderr)
        return 2

    path = Path(args.file).resolve()
    if not path.is_file():
        print(f"找不到文件：{path}", file=sys.stderr)
        return 2
    name = args.name or path.name

    api = f"https://api.github.com/repos/{REPO}"
    rel = call("GET", f"{api}/releases/tags/{args.tag}")
    payload = path.read_bytes()
    print(f"release {rel['id']} ({args.tag}), upload {name} ({len(payload)/1024/1024:.1f} MB)")

    for host in ("https://uploads.github.com", "https://api.github.com"):
        url = f"{host}/repos/{REPO}/releases/{rel['id']}/assets?name={name}"
        try:
            res = call("POST", url, raw=payload, ctype="application/octet-stream", timeout=900)
            print(f"ok id={res['id']} size={res['size']}")
            print(res["browser_download_url"])
            return 0
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            print(f"  {host} -> http {e.code}: {body}", file=sys.stderr)
            if e.code == 422:
                print("  同名资产已存在，跳过")
                return 0
        except Exception as e:
            print(f"  {host} -> {type(e).__name__}: {e}", file=sys.stderr)
    print("上传失败", file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())
