import sys, time
sys.path.insert(0, r"C:\Users\zjh19\DSH\astrbot-pc")
from astrbot_pc import api

t0 = time.perf_counter()
def lap(label):
    global t0
    now = time.perf_counter()
    print(f"{label}: {(now-t0)*1000:.0f}ms")
    t0 = now

lap("import")
for i in range(3):
    t0 = time.perf_counter()
    api.bootstrap()
    lap(f"bootstrap #{i}")
