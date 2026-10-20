"""把部署要用的东西全收进 resources/，做一个解压即用的离线包。

产物：
    resources/napcat.zip        NapCat.Shell.Windows.Node（约 118 MB）
    resources/astrbot.zip       AstrBot 源码（约 8 MB）
    resources/wheels/*.whl      AstrBot 全部依赖的 wheel（约 118 MB）
    resources/python/**         便携 Python 3.12（约 37 MB，只有 --lazy 才放）

前三样让部署时一步网都不用联；再加第四样（便携 Python），用户机器上一个
Python 都不用装——这就是「懒人版」。

用法：
    python -X utf8 tools/build_offline.py            # 缺什么补什么（不含便携 Python）
    python -X utf8 tools/build_offline.py --lazy     # 连便携 Python 一起备齐
    python -X utf8 tools/build_offline.py --force    # 全部重下
    python -X utf8 tools/build_offline.py --check    # 只看现状，不动文件

注意 wheel 是按**打包用的 Python 版本**（现在 3.12 / win_amd64）挑的。带便携
Python 的懒人版永远配得上；不带的话用户机器版本不同时还要联网装。
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
PYTHON_MIN = 30 * 1024 * 1024      # 解出来的便携 Python 约 37 MB
DEFAULT_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"

# NuGet 的 python 包 = 一份完整 CPython 发行版放在 tools/ 下（含 Lib\venv 与
# ensurepip），解出来就能 `-m venv`。embeddable zip 更小但没有 venv，不能用。
PY_VERSION = "3.12.10"
PY_NUPKG = [
    f"https://www.nuget.org/api/v2/package/python/{PY_VERSION}",
    f"https://globalcdn.nuget.org/packages/python.{PY_VERSION}.nupkg",
]


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
    return _sdist_to_wheel(wheel_dir)


def _sdist_to_wheel(wheel_dir: Path) -> bool:
    """把源码包就地编译成 wheel。

    ``pip install --no-index`` 装 ``.tar.gz`` 要现场编译，而 Python 3.12 起的
    venv 不再自带 setuptools，纯离线环境下必然失败。所以这里先把它们转成
    wheel，安装时就不用编译了。
    """
    import shutil
    import subprocess
    import tempfile

    sdists = sorted(list(wheel_dir.glob("*.tar.gz")) + list(wheel_dir.glob("*.zip")))
    if not sdists:
        return True
    print(f"  有 {len(sdists)} 个源码包，就地转成 wheel…")
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", tmp]
            + [str(s) for s in sdists],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if r.returncode != 0:
            tail = (r.stderr or r.stdout or "").strip().splitlines()[-6:]
            print("  " + "\n  ".join(tail))
            return False
        for w in Path(tmp).glob("*.whl"):
            shutil.move(str(w), wheel_dir / w.name)
    for s in sdists:
        s.unlink(missing_ok=True)
    print(f"  转好了，现在 {len(list(wheel_dir.glob('*.whl')))} 个 whl")
    return True


def _python(res: Path, force: bool) -> bool:
    """把 NuGet 的便携 Python 解到 resources/python。"""
    import shutil

    dest = res / "python"
    exe = dest / "python.exe"
    if not force and exe.exists():
        size = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file())
        if size >= PYTHON_MIN:
            print(f"  便携 Python 已存在（{_mb(size)}），跳过")
            return True
        print("  便携 Python 不完整，重解一次")

    nupkg = res / f"_python-{PY_VERSION}.nupkg"
    if not _download(f"Python {PY_VERSION}", PY_NUPKG, nupkg, 10 * 1024 * 1024):
        return False

    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with zipfile.ZipFile(nupkg) as z:
        for info in z.infolist():
            if not info.filename.startswith("tools/") or info.is_dir():
                continue
            out = dest / info.filename[len("tools/"):]
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
    nupkg.unlink(missing_ok=True)

    size = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file())
    print(f"  便携 Python 完成（{_mb(size)}）")
    return exe.exists() and (dest / "Lib" / "venv" / "__init__.py").exists()


def _report() -> dict:
    info = deploy.offline()
    print("\nresources/ 现状")
    print(f"  目录：{info['dir']}")
    print(f"  napcat.zip ：{'有' if info['napcat'] else '缺'}")
    print(f"  astrbot.zip：{'有' if info['astrbot'] else '缺'}")
    print(f"  wheels     ：{info['wheels']} 个")
    print(f"  便携 Python：{'有' if info['python'] else '缺'}")
    size = 0
    base = Path(info["dir"])
    if base.exists():
        size = sum(p.stat().st_size for p in base.rglob("*") if p.is_file())
    print(f"  合计       ：{_mb(size)}")
    print(f"  离线可用   ：{'是' if info['ready'] else '否'}")
    print(f"  懒人版     ：{'是（不用另装 Python）' if info['lazy'] else '否'}")
    return info


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="收集离线部署资源")
    ap.add_argument("--force", action="store_true", help="已有也重下")
    ap.add_argument("--check", action="store_true", help="只报告现状")
    ap.add_argument("--lazy", action="store_true", help="连便携 Python 一起备齐")
    ap.add_argument("--index", default=DEFAULT_INDEX, help="pip 源")
    args = ap.parse_args(argv)

    if args.check:
        _report()
        return 0

    res = Path(paths.RESOURCES_DIR)
    res.mkdir(parents=True, exist_ok=True)

    print(f"目标目录：{res}")
    print("\n1/4  NapCat")
    napcat = res / "napcat.zip"
    ok_napcat = _download("NapCat", deploy.napcat_sources(), napcat, NAPCAT_MIN)

    print("\n2/4  AstrBot 源码")
    astrbot = res / "astrbot.zip"
    ok_astrbot = _download("AstrBot", deploy.astrbot_sources(), astrbot, ASTRBOT_MIN)

    print("\n3/4  AstrBot 依赖")
    ok_wheels = False
    req_text = _read_requirements(astrbot) if ok_astrbot else None
    if not req_text:
        print("  拿不到 requirements.txt，跳过依赖")
    else:
        ok_wheels = _wheels(req_text, res / "wheels", args.index, args.force)

    print("\n4/4  便携 Python")
    if args.lazy:
        ok_python = _python(res, args.force)
    else:
        print("  跳过（要懒人版请加 --lazy）")
        ok_python = (res / "python" / "python.exe").exists()

    info = _report()
    if info["ready"]:
        print("\n可以了。打包时 build_exe.ps1 会自动把 resources/ 带进 offline 版。")
        if args.lazy and not info["lazy"]:
            print("但便携 Python 没备齐，这一包还不是懒人版。")
            return 1
        return 0
    missing = [k for k in ("napcat", "astrbot") if not info[k]]
    if not info["wheels"]:
        missing.append("wheels")
    print(f"\n还差：{'、'.join(missing)}（分别：napcat {ok_napcat} / "
          f"astrbot {ok_astrbot} / wheels {ok_wheels} / python {ok_python}）")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
