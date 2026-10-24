# -*- coding: utf-8 -*-
"""回归：出厂口令必须真的落到配置里，且 AstrBot 自己认这个密码。

做法：用一个空数据目录，建默认实例 -> 一键接线（等价于部署的「写入配置」）
-> 读 cmd_config.json / onebot11.json / 实例配置，断言：
  * 控制台密码是 Astrbot123，md5 与 pbkdf2 两套哈希都在且都能验过
  * OneBot 令牌与 NapCat WebUI 密钥都是 zhuxin，两边同值
  * 老实例里空着的令牌会被 migrate_ports 补回 zhuxin
最后用 AstrBot 自己的 auth_password.py 复核哈希（源码在 stack 里就用它，
不在就跳过这一条）。

用法：python tools/probe_creds.py [--home 目录]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

fails: list[str] = []


def check(name: str, ok: bool, extra: object = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (f" {extra}" if extra != "" else ""))
    if not ok:
        fails.append(name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", default=str(ROOT / ".devdata" / "probe-creds"))
    args = ap.parse_args()
    home = Path(args.home).resolve()
    if home.exists():
        shutil.rmtree(home)
    home.mkdir(parents=True)
    os.environ["ASTRBOT_PC_HOME"] = str(home)

    from astrbot_pc import config, creds, deploy, instances, paths, runtime, services

    instances.ensure_defaults()
    iid = runtime.active_id()
    check("默认实例 id", iid == "bot1", iid)

    item = runtime.get(iid)
    check("实例 OneBot 令牌", item.get("token") == paths.DEFAULT_ONEBOT_TOKEN, item.get("token"))
    check("实例 NapCat 密钥", item.get("napcatSecret") == paths.DEFAULT_NAPCAT_SECRET, item.get("napcatSecret"))

    wired = deploy.write_wiring(item)
    check("一键接线", bool(wired[0]) if isinstance(wired, tuple) else bool(wired), wired)

    cmd = json.loads(runtime.cmd_path(iid).read_text(encoding="utf-8-sig"))
    dash = cmd.get("dashboard") or {}
    check("控制台账号", dash.get("username") == "astrbot", dash.get("username"))
    check("md5 是出厂密码", creds._default_plain(dash.get("password", "")) == paths.DEFAULT_DASHBOARD_PASSWORD)
    check("pbkdf2 已写入", str(dash.get("pbkdf2_password", "")).startswith("pbkdf2_sha256$"))
    check("不强制改密", dash.get("password_change_required") is False, dash.get("password_change_required"))

    plats = cmd.get("platform") or []
    check("AstrBot 侧令牌", bool(plats) and all(p.get("ws_reverse_token") == paths.DEFAULT_ONEBOT_TOKEN for p in plats),
          [p.get("ws_reverse_token") for p in plats])

    ob = runtime.napcat_config(iid) / "onebot11.json"
    if ob.exists():
        data = json.loads(ob.read_text(encoding="utf-8-sig"))
        clients = ((data.get("network") or {}).get("websocketClients") or [])
        check("协议端侧令牌", bool(clients) and all(c.get("token") == paths.DEFAULT_ONEBOT_TOKEN for c in clients),
              [c.get("token") for c in clients])
    else:
        check("协议端配置存在", False, str(ob))

    env = services._child_env(iid, "napcat")
    check("NapCat WebUI 密钥", env.get("NAPCAT_WEBUI_SECRET_KEY") == paths.DEFAULT_NAPCAT_SECRET,
          env.get("NAPCAT_WEBUI_SECRET_KEY"))

    info = api_info = None
    from astrbot_pc import api
    _, info = api.dispatch("GET", "/api/console/creds", {}, {})
    check("接口回明文出厂密码", info.get("password") == paths.DEFAULT_DASHBOARD_PASSWORD, info.get("password"))
    check("接口标默认密码", info.get("defaultPassword") == paths.DEFAULT_DASHBOARD_PASSWORD)

    # 老实例：清空令牌后 migrate_ports 要补回来
    config.save({"instances": [dict(item, token="", napcatSecret="")]})
    runtime.migrate_ports()
    back = runtime.get(iid)
    check("老实例令牌补回", back.get("token") == paths.DEFAULT_ONEBOT_TOKEN and back.get("napcatSecret") == paths.DEFAULT_NAPCAT_SECRET,
          (back.get("token"), back.get("napcatSecret")))

    # 用 AstrBot 自己的校验函数复核
    cands = [
        paths.STACK_DIR / "astrbot" / "astrbot" / "core" / "utils" / "auth_password.py",
        ROOT / ".devdata" / "stack" / "astrbot" / "astrbot" / "core" / "utils" / "auth_password.py",
    ]
    auth = next((c for c in cands if c.exists()), None)
    if auth:
        spec = importlib.util.spec_from_file_location("ab_auth", auth)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        verify = getattr(mod, "verify_dashboard_password", None)
        if verify:
            check("AstrBot 验密码", bool(verify(dash["pbkdf2_password"], paths.DEFAULT_DASHBOARD_PASSWORD)))
            check("AstrBot 拒错密码", not verify(dash["pbkdf2_password"], "Astrbot124"))
    else:
        print("SKIP AstrBot 源码不在 stack 里，跳过官方校验")

    print("\n结果:", "全部通过" if not fails else f"{len(fails)} 项失败 -> {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
