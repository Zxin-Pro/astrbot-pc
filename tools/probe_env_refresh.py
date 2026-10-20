# -*- coding: utf-8 -*-
"""回归：部署跑完后，右侧体检必须自己刷新，不能停在开页时那份旧快照。

做法：用一个空数据目录起服务 → 打开部署页（此刻体检必然显示 NapCat / AstrBot 缺失）
→ 在页面开着的时候把 stack 目录「变出来」→ 跑一次演练部署（很快）→
看右侧体检是不是自己变成了「就绪」。

没有这个修复时，renderEnv() 只读 store.env（进页面时那份），永远是「缺失」。
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / ".devdata" / "env-refresh"
PORT = 17658


def wait_port(port: int, timeout: float = 40.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.2)
    return False


def post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return json.load(urllib.request.urlopen(req, timeout=30))


def get(path: str) -> dict:
    return json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=30))


def fake_stack(home: Path) -> None:
    """只造 envcheck 认得出来的最小结构，不是真安装。"""
    stack = home / "stack"
    nap = stack / "napcat"
    nap.mkdir(parents=True, exist_ok=True)
    (nap / "napcat.bat").write_text("@echo off\n", encoding="utf-8")

    ab = stack / "astrbot"
    ab.mkdir(parents=True, exist_ok=True)
    (ab / "requirements.txt").write_text("requests\n", encoding="utf-8")
    (ab / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n', encoding="utf-8")

    vpy = stack / "venv" / "Scripts"
    vpy.mkdir(parents=True, exist_ok=True)
    (vpy / "python.exe").write_bytes(b"MZ")


def main() -> int:
    if HOME.exists():
        shutil.rmtree(HOME, ignore_errors=True)
    HOME.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["ASTRBOT_PC_HOME"] = str(HOME)
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-m", "astrbot_pc", "--web", "--port", str(PORT)],
        cwd=str(ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_port(PORT):
            print("FAIL: 服务没起来")
            return 1

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            errors: list[str] = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.goto(f"http://127.0.0.1:{PORT}/#/deploy", wait_until="networkidle")
            page.wait_for_timeout(1200)

            def env_text() -> str:
                return page.eval_on_selector("#env-list", "el => el.innerText") or ""

            before = env_text()
            print("before:", " | ".join(before.split("\n")))

            # 页面开着的时候把 stack 造出来——模拟「部署刚把东西装好」
            fake_stack(HOME)

            # 跑一次演练部署，让它发出 finished 事件
            post("/api/deploy/start", {"dryRun": True})
            end = time.time() + 90
            while time.time() < end:
                st = get("/api/deploy/status")
                if not st.get("running") and st.get("finished"):
                    break
                time.sleep(0.5)
            page.wait_for_timeout(3500)  # 等前端 refreshEnv 回来

            after = env_text()
            print("after :", " | ".join(after.split("\n")))

            ok = ("缺失" not in after) and ("就绪" in after)
            print("console errors:", errors)
            print("PASS" if ok and not errors else "FAIL")
            browser.close()
            return 0 if ok and not errors else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
