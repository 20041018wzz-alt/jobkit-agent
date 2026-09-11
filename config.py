# -*- coding: utf-8 -*-
"""wzz-agent 配置。

所有配置来自环境变量（支持同目录 .env 文件，零依赖解析），默认值保证
**无 API Key 也能完整跑通**（Mock 模式）。
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    """把同目录 .env 载入环境变量（已存在的变量不覆盖）。"""
    path = BASE_DIR / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

# ── 知识库 ──────────────────────────────────────────────────────────────────
# 三级解析：环境变量 > 本地私有知识库（data/knowledge.local，不入库）> 示例知识库（data/knowledge，随仓库分发）。
# 这样开源仓库里只有脱敏的示例数据，本地跑起来用的仍是自己的真实档案。
SAMPLE_KNOWLEDGE_DIR = BASE_DIR / "data" / "knowledge"
LOCAL_KNOWLEDGE_DIR = BASE_DIR / "data" / "knowledge.local"
SAMPLE_EVAL_SET = BASE_DIR / "data" / "eval_set.json"
LOCAL_EVAL_SET = BASE_DIR / "data" / "eval_set.local.json"


def _has_markdown(directory: Path) -> bool:
    return directory.is_dir() and any(directory.glob("*.md"))


_ENV_KNOWLEDGE = os.getenv("WZZ_KNOWLEDGE_DIR", "").strip()
if _ENV_KNOWLEDGE:
    KNOWLEDGE_DIR = Path(_ENV_KNOWLEDGE)
    KNOWLEDGE_SOURCE = "env"
elif _has_markdown(LOCAL_KNOWLEDGE_DIR):
    KNOWLEDGE_DIR = LOCAL_KNOWLEDGE_DIR
    KNOWLEDGE_SOURCE = "local"
else:
    KNOWLEDGE_DIR = SAMPLE_KNOWLEDGE_DIR
    KNOWLEDGE_SOURCE = "sample"

_ENV_EVAL_SET = os.getenv("WZZ_EVAL_SET", "").strip()
if _ENV_EVAL_SET:
    EVAL_SET_PATH = Path(_ENV_EVAL_SET)
elif KNOWLEDGE_SOURCE == "local" and LOCAL_EVAL_SET.exists():
    EVAL_SET_PATH = LOCAL_EVAL_SET
else:
    EVAL_SET_PATH = SAMPLE_EVAL_SET

# ── 检索 ────────────────────────────────────────────────────────────────────
TOP_K = int(os.getenv("TOP_K", "4"))
# BM25 覆盖率分数的阈值：低于它视为"知识库里没有相关内容"
RELEVANCE_THRESHOLD = float(os.getenv("RELEVANCE_THRESHOLD", "0.35"))
# 缺失清单条目的"胜出比例"：达到最强证据的这个比例就按"没有记录"处理（安全优先，宁可拒答不可编造）
GAP_DOMINANCE_RATIO = float(os.getenv("GAP_DOMINANCE_RATIO", "0.7"))

# ── LLM（OpenAI 兼容；不配 Key 自动 Mock） ──────────────────────────────────
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
FORCE_MOCK = os.getenv("LLM_MOCK", "").lower() in {"1", "true", "yes", "on"}
USE_MOCK = FORCE_MOCK or not LLM_API_KEY

# ── Agent 行为 ──────────────────────────────────────────────────────────────
AGENT_NAME = os.getenv("AGENT_NAME", "wzz-agent")
AGENT_VERSION = "1.0.0"
MAX_TOOL_STEPS = int(os.getenv("MAX_TOOL_STEPS", "3"))
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "10"))

# ── 服务 ────────────────────────────────────────────────────────────────────
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8100"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
