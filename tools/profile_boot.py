import time, os
import sys
sys.path.insert(0, r"C:\Users\zjh19\DSH\astrbot-pc")
from astrbot_pc import backup, config, deploy, envcheck, instances, stats, paths, services

paths.ensure_dirs(); config.load()
m = services.manager
def t(label, fn):
    s = time.perf_counter()
    try:
        fn()
    except Exception as e:
        print(label, "ERR", e)
        return
    print(f"{label}: {(time.perf_counter()-s)*1000:.0f}ms")

t("services.status", m.status)
t("envcheck.cached", lambda: envcheck.snapshot())
t("envcheck.force", lambda: envcheck.snapshot(force=True))
t("stats.overview", lambda: stats.overview(m.status()))
t("deploy.status", deploy.status)
t("deploy.stages", deploy.stages)
t("instances", instances.list_all)
t("backup.usage", backup.usage)
t("config.load", config.load)
