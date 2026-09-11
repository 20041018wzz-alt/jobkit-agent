# -*- coding: utf-8 -*-
"""控制台编码兜底测试：模拟 cp1252 的 stdout，验证中文输出不再抛 UnicodeEncodeError。"""
from __future__ import annotations

import io
import sys

from console import enable_utf8


def test_enable_utf8_allows_chinese_output():
    raw = io.BytesIO()
    wrapper = io.TextIOWrapper(raw, encoding="cp1252")
    original = sys.stdout
    sys.stdout = wrapper
    try:
        enable_utf8()
        print("中文输出：评测报告 ✓")  # 修复前这里会抛 UnicodeEncodeError
        sys.stdout.flush()
    finally:
        sys.stdout = original
    assert raw.getvalue().decode("utf-8").strip() == "中文输出：评测报告 ✓"


def test_enable_utf8_skips_streams_without_reconfigure():
    class Plain:
        def write(self, text):  # pragma: no cover - 仅用于确认不抛异常
            return len(text)

    enable_utf8(Plain())  # 不应抛异常
