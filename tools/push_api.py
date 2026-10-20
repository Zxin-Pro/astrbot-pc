"""通过 GitHub REST API 把本地提交推上去，不依赖 git 的 443 通道。

适用场景：只放行了 api.github.com，`git push` 到 github.com:443 会被重置。
流程和 git 自己做的一样，只是拆成了 HTTP 调用：

    blob（逐文件） → tree → commit → ref

用法：

    set GITHUB_TOKEN=ghp_xxx
    python tools/push_api.py

为什么用 Python 而不是 PowerShell：中文路径 + 79 个并发请求 + 实时进度，
Python 的 urllib 行为更可预期；PowerShell 5.1 下这条链路实测会卡住。
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO = "Zxin-Pro/astrbot-pc"
BRANCH = "main"
MESSAGE_FILE = ".git/COMMIT_MSG_TMP.txt"
API = f"https://api.github.com/repos/{REPO}"
WORKERS = 4

TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "User-Agent": "AstrBotPC-push",
    "Accept": "application/vnd.github+json",
    "Content-Type": "application/json; charset=utf-8",
}


def call(method: str, url: str, payload: dict | None = None, timeout: int = 60) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return json.loads(raw or b"{}")


def upload_blob(rel_path: str) -> dict:
    with open(rel_path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("ascii")
    res = call("POST", f"{API}/git/blobs", {"content": b64, "encoding": "base64"})
    return {"path": rel_path.replace("\\", "/"), "mode": "100644", "type": "blob", "sha": res["sha"]}


def main() -> int:
    if not TOKEN:
        print("GITHUB_TOKEN 没有设置", file=sys.stderr)
        return 2

    files = subprocess.check_output(["git", "ls-files"], text=True, encoding="utf-8").splitlines()
    files = [f for f in files if f.strip()]
    if not files:
        print("git ls-files 是空的，先在本地提交", file=sys.stderr)
        return 2
    print(f"files: {len(files)}")

    entries: list[dict] = []
    done = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(upload_blob, f): f for f in files}
        for fut in as_completed(futures):
            f = futures[fut]
            try:
                entries.append(fut.result())
            except Exception as e:
                print(f"  ! {f}: {e}", file=sys.stderr)
                return 3
            done += 1
            if done % 10 == 0 or done == len(files):
                print(f"  blob {done}/{len(files)}  ({time.time() - t0:.0f}s)")

    tree = call("POST", f"{API}/git/trees", {"tree": entries})
    print(f"tree: {tree['sha']}")

    with open(MESSAGE_FILE, encoding="utf-8") as fh:
        message = fh.read()

    parents: list[str] = []
    try:
        head = call("GET", f"{API}/git/ref/heads/{BRANCH}", timeout=30)
        parents = [head["object"]["sha"]]
        print(f"parent: {parents[0]}")
    except Exception:
        print("parent: (空仓库，做根提交)")

    commit = call("POST", f"{API}/git/commits",
                  {"message": message, "tree": tree["sha"], "parents": parents})
    print(f"commit: {commit['sha']}")

    try:
        ref = call("POST", f"{API}/git/refs", {"ref": f"refs/heads/{BRANCH}", "sha": commit["sha"]})
        print(f"ref created: {ref['ref']}")
    except Exception:
        ref = call("PATCH", f"{API}/git/refs/heads/{BRANCH}", {"sha": commit["sha"], "force": True})
        print(f"ref updated: {ref['ref']}")

    print(f"PUSH_OK {commit['sha']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
