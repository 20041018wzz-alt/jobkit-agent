# -*- coding: utf-8 -*-
"""控制台编码兜底。

Windows 的默认标准输出编码可能是 cp1252（英文版 runner）/cp936（中文版系统 PowerShell），
此时 `print("中文")` 会抛 UnicodeEncodeError 直接让进程退出——CI 的 windows-latest 就是这样挂的。
所有命令行入口在打印前先调用 `enable_utf8()`，把 stdout/stderr 切到 UTF-8 并容错，
这样在任意语言、任意终端上输出中文都不会崩。
"""
from __future__ import annotations

import sys
from typing import Any


def enable_utf8(*streams: Any) -> None:
    """把给定流（默认 stdout/stderr）重新配置为 UTF-8；不支持 reconfigure 的流会静默跳过。"""
    targets = streams or (sys.stdout, sys.stderr)
    for stream in targets:
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # 已关闭或不可重配的流（如 pytest 捕获对象）
            continue
