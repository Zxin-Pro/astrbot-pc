"""扫一遍界面里用到的 CSS 自定义属性，找出没定义的那些。

两套主题都定义在 ``tokens.css``，但组件里允许写局部变量（比如
``.btn--primary { --btn-bg: ... }``），所以定义处要连所有 CSS 一起扫，
JS 里 ``style.setProperty('--x', ...)`` 动态设的也算定义。
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent / "ui"

defined: set[str] = set()
used: dict[str, set[str]] = {}

css_files = list(ROOT.rglob("*.css"))
js_files = list(ROOT.rglob("*.js"))

for f in css_files:
    txt = f.read_text(encoding="utf-8", errors="replace")
    # 声明（含局部作用域里的自定义属性）
    defined |= set(re.findall(r"(--[a-z0-9-]+)\s*:", txt))
    for m in re.finditer(r"var\(\s*(--[a-z0-9-]+)", txt):
        used.setdefault(m.group(1), set()).add(f.name)

for f in js_files:
    txt = f.read_text(encoding="utf-8", errors="replace")
    # JS 里 setProperty('--x', ...) 或 el.style['--x'] = ...
    defined |= set(re.findall(r"setProperty\(\s*['\"](--[a-z0-9-]+)", txt))
    defined |= set(re.findall(r"['\"](--[a-z0-9-]+)['\"]\s*:", txt))
    for m in re.finditer(r"var\(\s*(--[a-z0-9-]+)", txt):
        used.setdefault(m.group(1), set()).add(f.name)

missing = {k: sorted(v) for k, v in used.items() if k not in defined}
for k in sorted(missing):
    print(k, "->", missing[k])
print("total missing:", len(missing))
