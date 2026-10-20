"""验证离线部署：resources/ 齐全时八步不该碰网络。

跑法：
    python -X utf8 tools/probe_offline_deploy.py            # 演练，只验证判定
    python -X utf8 tools/probe_offline_deploy.py --real     # 真装一遍（占 1 GB，几分钟）

隔离在 .devdata\\offline-deploy 下，不碰真实数据目录。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HOME = ROOT / ".devdata" / "offline-deploy"
os.environ["ASTRBOT_PC_HOME"] = str(HOME)

from astrbot_pc import config, deploy, paths  # noqa: E402


def main(argv: list[str]) -> int:
    real = "--real" in argv
    print(f"数据目录：{paths.ROOT}")
    print(f"资源目录：{paths.RESOURCES_DIR}")

    info = deploy.offline()
    print(f"offline()：{info}")
    assert info["napcat"] and info["astrbot"], "resources/ 里缺源码包，先跑 build_offline.py"
    assert info["wheels"] > 0, "resources/wheels 是空的，先跑 build_offline.py"
    assert info["ready"] and info["sources"], "offline().ready/sources 应当为真"

    config.load()
    config.save({"deploy": {"dryRun": not real, "astrbotMethod": "git"}})

    runner = deploy.runner()
    ok = runner.start(dry_run=not real)
    print(f"start() -> {ok}")
    if not ok:
        return 2

    t0 = time.time()
    while True:
        st = runner.status()
        if not st["running"] and st["finished"]:
            break
        if time.time() - t0 > 1800:
            print("超时")
            return 3
        time.sleep(1.5)

    print(f"\n总耗时 {time.time() - t0:.1f}s  ok={st['ok']}  {st['message']}")
    bad = []
    for s in st["steps"]:
        line = f"  {s['key']:<12} {s['status']:<8} {s['ms'] / 1000:6.1f}s  {s['detail']}"
        print(line)
        if s["status"] == "failed":
            bad.append(s)
        # 离线包在的时候，这两个步骤的说明里不该出现「下载」「git」
        if s["key"] in ("napcat", "astrbot") and s["status"] == "done":
            if "离线包" not in (s["detail"] or ""):
                print(f"    !! {s['key']} 没走离线包：{s['detail']}")
                bad.append(s)

    if bad:
        print(f"\nFAIL：{len(bad)} 个步骤不对")
        return 1
    print("\nPASS：全程走离线包")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
