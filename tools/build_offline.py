"""把部署要用的东西全收进 resources/，做一个解压即用的离线包。

产物：
    resources/napcat.zip        NapCat.Shell.Windows.Node（约 118 MB）
    resources/astrbot.zip       AstrBot 源码（约 8 MB）
    resources/wheels/*.whl      AstrBot 全部依赖的 wheel（约 300 MB）

有这三样，部署时一步网都不用联：napcat 和 astrbot 直接解压，依赖走
``pip install --no-index --find-links``。

用法：
    python -X utf8 tools/build_offline.py            # 缺什么补什么
    python -X utf8 tools/build_offline.py --force    # 全部重下
    python -X utf8 tools/build_offline.py --check    # 只看现状，不动文件

注意 wheel 是按**本机 Python 版本**（现在 3.12 / win_amd64）挑的。用户机器上
Python 版本不同时装不上，部署代码会自动回退成联网安装，但那就不再是离线包了。
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from astrbot_pc import deploy, download, paths  # noqa: E402

NAPCAT_MIN = 80 * 1024 * 1024      # 正常 118 MB，太小说明下坏了
ASTRBOT_MIN = 2 * 1024 * 1024      # 正常 8 MB
DEFAULT_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"


def _mb(n: float) -> str:
    return f"{n / 1024 / 1024:.1f} MB"


def _bar(label: str):
    """下载进度条，同一行刷新，别刷屏。"""
    last = [-1]

    def on_progress(got: int, total: int) -> None:
        pct = int(got * 100 / total) if total else -1
        if pct == last[0]:
            return
        last[0] = pct
        line = f"  {label} {_mb(got)}"
        if total:
            line += f" / {_mb(total)}  {pct:3d}%"
        print(f"\r{line}   ", end="", flush=True)

    return on_progress


def _download(label: str, sources: list[str], dest: Path, minimum: int) -> bool:
    if dest.exists() and dest.stat().st_size >= minimum:
        print(f"  {label} 已存在（{_mb(dest.stat().st_size)}），跳过")
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.unlink(missing_ok=True)
    print(f"  {label} 下到 {dest}")
    try:
        download.fetch(sources, dest, _bar(label))
    except download.DownloadError as e:
        print(f"\r  {label} 失败：{e}")
        return False
    print()
    size = dest.stat().st_size
    if size < minimum:
        print(f"  {label} 只有 {_mb(size)}，比预期小，可能下坏了")
        return False
    print(f"  {label} 完成（{_mb(size)}）")
    return True


def _read_requirements(astrbot_zip: Path) -> str | None:
    """从源码 zip 里直接读 requirements.txt，不用解压整个包。"""
    try:
        with zipfile.ZipFile(astrbot_zip) as zf:
            for name in zf.namelist():
                parts = name.split("/")
                # 只要顶层那个：AstrBot-master/requirements.txt
                if len(parts) == 2 and parts[1] == "requirements.txt":
                    return zf.read(name).decode("utf-8-sig")
    except (zipfile.BadZipFile, OSError) as e:
        print(f"  读源码包失败：{e}")
    return None


def _wheels(req_text: str, wheel_dir: Path, index: str, force: bool) -> bool:
    import subprocess
    import tempfile

    wheel_dir.mkdir(parents=True, exist_ok=True)
    if force:
        for old in wheel_dir.glob("*.whl"):
            old.unlink()
    existing = len(list(wheel_dir.glob("*.whl")))
    if existing:
        print(f"  wheels 里已有 {existing} 个包，只补缺的")

    with tempfile.TemporaryDirectory() as tmp:
        req = Path(tmp) / "requirements.txt"
        req.write_text(req_text, encoding="utf-8")
        base = [sys.executable, "-m", "pip", "download", "-r", str(req),
                "-d", str(wheel_dir), "--disable-pip-version-check",
                "--progress-bar", "off"]
        if index:
            base += ["-i", index]

        # 先只收 wheel。有些包压根不发 wheel，这时退回允许源码包，
        # 否则整个离线包都做不成。
        for extra, note in ((["--only-binary=:all:"], "只收 wheel"),
                            ([], "允许源码包（有些包没有 wheel）")):
            print(f"  pip download（{note}）…")
            r = subprocess.run(base + extra, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            if r.returncode == 0:
                break
            tail = (r.stderr or r.stdout or "").strip().splitlines()[-6:]
            print("  " + "\n  ".join(tail))
        else:
            return False

    got = list(wheel_dir.glob("*.whl"))
    total = sum(p.stat().st_size for p in got)
    print(f"  wheels 完成：{len(got)} 个包，{_mb(total)}")
    return True


def _report() -> dict:
    info = deploy.offline()
    print("\nresources/ 现状")
    print(f"  目录：{info['dir']}")
    print(f"  napcat.zip ：{'有' if info['napcat'] else '缺'}")
    print(f"  astrbot.zip：{'有' if info['astrbot'] else '缺'}")
    print(f"  wheels     ：{info['wheels']} 个")
    size = 0
    base = Path(info["dir"])
    if base.exists():
        size = sum(p.stat().st_size for p in base.rglob("*") if p.is_file())
    print(f"  合计       ：{_mb(size)}")
    print(f"  离线可用   ：{'是' if info['ready'] else '否'}")
    return info


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="收集离线部署资源")
    ap.add_argument("--force", action="store_true", help="已有也重下")
    ap.add_argument("--check", action="store_true", help="只报告现状")
    ap.add_argument("--index", default=DEFAULT_INDEX, help="pip 源")
    args = ap.parse_args(argv)

    if args.check:
        _report()
        return 0

    res = Path(paths.RESOURCES_DIR)
    res.mkdir(parents=True, exist_ok=True)

    print(f"目标目录：{res}")
    print("\n1/3  NapCat")
    napcat = res / "napcat.zip"
    ok_napcat = _download("NapCat", deploy.napcat_sources(), napcat, NAPCAT_MIN)

    print("\n2/3  AstrBot 源码")
    astrbot = res / "astrbot.zip"
    ok_astrbot = _download("AstrBot", deploy.astrbot_sources(), astrbot, ASTRBOT_MIN)

    print("\n3/3  AstrBot 依赖")
    ok_wheels = False
    req_text = _read_requirements(astrbot) if ok_astrbot else None
    if not req_text:
        print("  拿不到 requirements.txt，跳过依赖")
    else:
        ok_wheels = _wheels(req_text, res / "wheels", args.index, args.force)

    info = _report()
    if info["ready"]:
        print("\n可以了。打包时 build_exe.ps1 会自动把 resources/ 带进 offline 版。")
        return 0
    missing = [k for k in ("napcat", "astrbot") if not info[k]]
    if not info["wheels"]:
        missing.append("wheels")
    print(f"\n还差：{'、'.join(missing)}（分别：napcat {ok_napcat} / "
          f"astrbot {ok_astrbot} / wheels {ok_wheels}）")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
