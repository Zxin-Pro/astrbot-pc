"""给 PowerShell 脚本补 BOM。

Windows PowerShell 5.1 读无 BOM 的 UTF-8 中文脚本会按 ANSI 解码，引号被吃掉后
报 "string is missing the terminator"。用编辑器/写文件工具改完 .ps1 之后跑一遍这个。
"""

from __future__ import annotations

import sys
from pathlib import Path

BOM = b"\xef\xbb\xbf"


def fix(path: Path) -> bool:
    raw = path.read_bytes()
    if raw.startswith(BOM):
        return False
    path.write_bytes(BOM + raw)
    return True


def main(argv: list[str]) -> int:
    targets = [Path(a) for a in argv] or sorted(Path("tools").glob("*.ps1"))
    for p in targets:
        if not p.is_file():
            print(f"跳过（不存在）{p}")
            continue
        changed = fix(p)
        print(f"{'补上 BOM' if changed else '已有 BOM'}  {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
