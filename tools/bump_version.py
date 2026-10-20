"""把工程里的版本号从旧值批量换成新值。

改动的文件（都在项目根下）：
    astrbot_pc/paths.py           APP_VERSION = "x.y.z"
    build/version_info.txt        filevers/prodvers/FileVersion/ProductVersion
    tools/build_exe.ps1           [string]$Version = 'x.y.z'
    tools/release.py              TAG / NAME / ZIP / OFFLINE / SINGLE
    README.md                     安装包文件名

保留原有 BOM：tools/build_exe.ps1 是 UTF-8 with BOM，PowerShell 5.1 读无 BOM
的中文 .ps1 会按 ANSI 解码，引号被吃掉就整份脚本报错。

用法：
    python -X utf8 tools/bump_version.py 1.2.0 1.3.0
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(path: Path) -> tuple[str, bool]:
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    return text, bom


def write(path: Path, text: str, bom: bool) -> None:
    data = text.encode("utf-8")
    path.write_bytes((b"\xef\xbb\xbf" + data) if bom else data)


def bump_file(path: Path, old: str, new: str, patterns: list[str]) -> int:
    text, bom = read(path)
    hits = 0
    for pat in patterns:
        rx = re.compile(pat.replace("{v}", re.escape(old)))
        text, n = rx.subn(lambda m: m.group(0).replace(old, new), text)
        hits += n
    if hits:
        write(path, text, bom)
    print(f"  {path.relative_to(ROOT)}：{hits} 处")
    return hits


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    old, new = argv
    if old == new:
        print("新旧一样，没意义")
        return 2
    parts = new.split(".")
    quad = f"({parts[0]}, {parts[1]}, {parts[2]}, 0)" if len(parts) >= 3 else None

    total = 0
    total += bump_file(ROOT / "astrbot_pc" / "paths.py", old, new,
                       [r'APP_VERSION = "{v}"'])
    if quad:
        total += bump_file(ROOT / "build" / "version_info.txt", old, new,
                           [r"filevers=\{v\}", r"prodvers=\{v\}"])
        text, bom = read(ROOT / "build" / "version_info.txt")
        text2 = text.replace(quad.replace("(", "(").replace(" ", " "), quad)
        # 版本元组的写法可能是 (1, 2, 0, 0)，直接整段替换更稳
        text2 = re.sub(r"filevers=\(\d+, \d+, \d+, \d+\)", f"filevers={quad}", text2)
        text2 = re.sub(r"prodvers=\(\d+, \d+, \d+, \d+\)", f"prodvers={quad}", text2)
        if text2 != text:
            write(ROOT / "build" / "version_info.txt", text2, bom)
            total += 1
    total += bump_file(ROOT / "build" / "version_info.txt", old, new,
                       [r"FileVersion', '{v}'", r"ProductVersion', '{v}'",
                        r'FileVersion", "{v}"', r'ProductVersion", "{v}"'])
    total += bump_file(ROOT / "tools" / "build_exe.ps1", old, new,
                       [r"\[string\]\$Version = '{v}'"])
    total += bump_file(ROOT / "tools" / "release.py", old, new,
                       [r"TAG = \"pc-v{v}\"",
                        r"烛之控制台 v{v} · PC 端",
                        r"AstrBotPC-{v}-win64\.zip",
                        r"AstrBotPC-{v}-win64-offline\.zip",
                        r"AstrBotPC-{v}-win64-single\.exe"])
    total += bump_file(ROOT / "README.md", old, new,
                       [r"AstrBotPC-{v}-win64(-offline|-single)?\.(zip|exe)"])

    # 最后复核一遍，漏了要能看见。更新日志里的老版本号是历史，不算残留，
    # 所以按「版本号在文件末尾出现几次」判断没意义——只认结构化字段。
    print("\n复核：")
    for rel, pat in (
        ("astrbot_pc/paths.py", r'APP_VERSION = "([^"]+)"'),
        ("tools/build_exe.ps1", r"\$Version = '([^']+)'"),
        ("tools/release.py", r'TAG = "pc-v([^"]+)"'),
        ("build/version_info.txt", r"filevers=\(([^)]+)\)"),
    ):
        m = re.search(pat, read(ROOT / rel)[0])
        print(f"  {rel} -> {m.group(1) if m else '没找到'}")
    leftovers = []
    for f, pats in (
        (ROOT / "astrbot_pc" / "paths.py", [r'APP_VERSION = "{v}"']),
        (ROOT / "tools" / "release.py", [r"TAG = \"pc-v{v}\"",
                                         r"烛之控制台 v{v} · PC 端",
                                         r"AstrBotPC-{v}-win64"]),
        (ROOT / "tools" / "build_exe.ps1", [r"\$Version = '{v}'"]),
        (ROOT / "build" / "version_info.txt", [r"\('FileVersion', '{v}'\)",
                                               r"filevers=\({old_re}\)",
                                               r"prodvers=\({old_re}\)"]),
    ):
        text = read(f)[0]
        for pat in pats:
            p = pat.replace("{v}", old).replace("{old_re}", re.escape(
                ", ".join(old.split(".") + ["0"])))
            if re.search(p, text):
                leftovers.append(f"{f.relative_to(ROOT)}（{pat}）")
                break
    print("  还有旧版本号：" + ("、".join(leftovers) if leftovers else "没有"))
    print(f"\n共 {total} 处")
    return 0 if not leftovers else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
