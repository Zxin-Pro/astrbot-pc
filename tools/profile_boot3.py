import sys, time
sys.path.insert(0, r"C:\Users\zjh19\DSH\astrbot-pc")
from astrbot_pc import api, services, stats, instances, backup, deploy, config, envcheck, paths

paths.ensure_dirs(); config.load()
m = services.manager

def lap(fn, label):
    s = time.perf_counter(); v = fn(); print(f"{label}: {(time.perf_counter()-s)*1000:.0f}ms"); return v

svc = lap(m.status, "manager.status")
lap(lambda: stats.overview(svc), "stats.overview")
lap(lambda: envcheck.snapshot(), "envcheck.snapshot")
lap(deploy.status, "deploy.status")
lap(deploy.stages, "deploy.stages")
lap(instances.list_all, "instances.list_all")
lap(backup.usage, "backup.usage")
lap(config.load, "config.load")
lap(lambda: api._server_info(), "_server_info")
import astrbot_pc
lap(lambda: astrbot_pc.__version__, "__version__")
