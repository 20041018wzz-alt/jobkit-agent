# -*- coding: utf-8 -*-
"""LLM 抽象层：OpenAI 兼容客户端 + 离线 Mock。

Mock 不是"随便返回点东西"：它按与真实模型完全相同的**提示词协议**作答
（`RESPOND_WITH=ACTION_JSON` 走工具决策，`RESPOND_WITH=FINAL_TEXT` 走回答生成），
因此所有单元测试、评测脚本都能在**无网络、无 API Key** 的情况下确定性运行，
真实模型只替换这一个类，Agent 主流程不变。
"""
from __future__ import annotations

import json
import re
from typing import Dict, Iterator, List, Optional

import httpx

import config

REFUSAL_TEXT = "记录里没有这方面的信息。"
KNOWLEDGE_OPEN = "<<<KNOWLEDGE"
KNOWLEDGE_CLOSE = ">>>"
PROTOCOL_ACTION = "RESPOND_WITH=ACTION_JSON"
PROTOCOL_FINAL = "RESPOND_WITH=FINAL_TEXT"

_KNOWLEDGE_RE = re.compile(
    re.escape(KNOWLEDGE_OPEN) + r"\n(?P<body>.*?)\n" + re.escape(KNOWLEDGE_CLOSE), re.S
)
_ENTRY_RE = re.compile(r"^\[(?P<id>[A-Za-z]+-\d+)\]\s*(?P<title>.*)$", re.M)
_TOOLS_RE = re.compile(r"^AVAILABLE_TOOLS:\s*(?P<names>.+)$", re.M)
_MISSING_RE = re.compile(r"^MISSING_FACTS:.*\n(?P<body>.*)$", re.M | re.S)


class LLMError(RuntimeError):
    """LLM 调用失败（网络/鉴权/格式）。"""


class BaseLLM:
    """LLM 接口：一次完整调用 + 一次流式调用。"""

    is_mock = False

    def complete(self, messages: List[Dict[str, str]]) -> str:  # pragma: no cover - 接口
        raise NotImplementedError

    def stream(self, messages: List[Dict[str, str]]) -> Iterator[str]:  # pragma: no cover - 接口
        yield self.complete(messages)


class OpenAICompatLLM(BaseLLM):
    """DeepSeek / OpenAI 兼容的 /chat/completions 客户端。"""

    def __init__(self, api_key: str, base_url: str, model: str, timeout: float = 60.0,
                 temperature: float = 0.2) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.temperature = temperature

    @property
    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _payload(self, messages: List[Dict[str, str]], stream: bool) -> dict:
        return {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": stream,
        }

    def complete(self, messages: List[Dict[str, str]]) -> str:
        url = f"{self.base_url}/chat/completions"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, headers=self._headers, json=self._payload(messages, False))
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001 - 统一收敛成 LLMError 交由 Agent 降级
            raise LLMError(f"LLM 调用失败: {exc}") from exc
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"LLM 响应格式异常: {data}") from exc

    def stream(self, messages: List[Dict[str, str]]) -> Iterator[str]:
        url = f"{self.base_url}/chat/completions"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                with client.stream("POST", url, headers=self._headers,
                                   json=self._payload(messages, True)) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        chunk = line[5:].strip()
                        if chunk == "[DONE]":
                            break
                        try:
                            delta = json.loads(chunk)["choices"][0]["delta"].get("content")
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
                        if delta:
                            yield delta
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"LLM 流式调用失败: {exc}") from exc


class MockLLM(BaseLLM):
    """离线确定性模型：按提示词协议从知识块里作答，绝不编造。"""

    is_mock = True

    # 关键词 → 工具名：模拟真实模型的 Function Calling 决策
    TOOL_TRIGGERS = (
        (("口径", "冲突", "不一致", "对不上"), "check_number_consistency"),
        (("简历条目", "写进简历", "star", "简历里写", "项目经历条目"), "draft_resume_bullet"),
        (("面试题", "模拟面试", "追问我", "考考我", "考我"), "mock_interview"),
        (("一句话", "概括一下他", "总结一下他", "自我介绍"), "summarize_profile"),
        (("查一下", "知识库", "具体条目", "哪一条"), "query_knowledge"),
    )

    def complete(self, messages: List[Dict[str, str]]) -> str:
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        if PROTOCOL_ACTION in system:
            return self._plan(system, user, messages)
        return self._answer(system, messages)

    def stream(self, messages: List[Dict[str, str]]) -> Iterator[str]:
        text = self._answer(
            next((m["content"] for m in messages if m["role"] == "system"), ""), messages
        )
        for i in range(0, len(text), 12):
            yield text[i:i + 12]

    # ── 内部 ────────────────────────────────────────────────────────────────
    def _plan(self, system: str, user: str, messages: List[Dict[str, str]]) -> str:
        available = self._available_tools(system)
        already_called = {m.get("name", "") for m in messages if m["role"] == "tool"}
        lowered = user.lower()
        for keywords, tool in self.TOOL_TRIGGERS:
            if tool in available and tool not in already_called and any(k in lowered for k in keywords):
                return json.dumps({"action": "tool", "tool": tool, "args": self._guess_args(tool, user)},
                                  ensure_ascii=False)
        return json.dumps({"action": "answer"}, ensure_ascii=False)

    @staticmethod
    def _guess_args(tool: str, user: str) -> Dict[str, object]:
        """从提问里抽取条目号（模拟真实模型的参数填充）。"""
        if tool not in {"draft_resume_bullet", "mock_interview", "query_knowledge"}:
            return {}
        match = re.search(r"\b([A-Za-z]+-\d+)\b", user)
        if not match:
            return {}
        value = match.group(1).upper()
        return {"keyword": value} if tool == "query_knowledge" else {"project_id": value}

    def _answer(self, system: str, messages: List[Dict[str, str]]) -> str:
        entries = self._parse_entries(system)
        tool_notes = [m["content"] for m in messages if m["role"] == "tool"]
        prefix = ("\n\n".join(tool_notes) + "\n\n") if tool_notes else ""
        if not entries:
            if tool_notes:
                # 工具已经给出可直接使用的内容，此时不该说"没有记录"
                return prefix.strip() + "\n\n（以上内容由工具基于知识库条目生成，可直接使用。）"
            missing = self._parse_missing(system)
            hint = f"\n按缺失清单，这些信息确实没有记录：{missing}。" if missing else ""
            return prefix + REFUSAL_TEXT + "（知识库里没有可支撑该问题的条目，我不会替你编造。）" + hint

        blocks: List[str] = []
        for entry_id, title, body in entries[:2]:
            bullets = [ln.strip(" -") for ln in body.splitlines() if ln.strip().startswith(("- ", "1.", "2.", "3."))]
            detail = "；".join(bullets[:3]) if bullets else " ".join(body.split())[:160]
            blocks.append(f"**{title}**（[{entry_id}]）\n- {detail}")
        citations = "、".join(f"[{e[0]}]" for e in entries[:2])
        return f"{prefix}根据记录：\n\n" + "\n\n".join(blocks) + f"\n\n参考：{citations}"

    @staticmethod
    def _available_tools(system: str) -> List[str]:
        match = _TOOLS_RE.search(system)
        if not match:
            return []
        return [name.strip() for name in match.group("names").split(",") if name.strip()]

    @staticmethod
    def _parse_entries(system: str) -> List[tuple]:
        match = _KNOWLEDGE_RE.search(system)
        if not match:
            return []
        body = match.group("body").strip()
        if not body:
            return []
        entries: List[tuple] = []
        marks = list(_ENTRY_RE.finditer(body))
        for index, mark in enumerate(marks):
            start = mark.end()
            end = marks[index + 1].start() if index + 1 < len(marks) else len(body)
            entries.append((mark.group("id"), mark.group("title").strip(), body[start:end].strip()))
        return entries

    @staticmethod
    def _parse_missing(system: str) -> str:
        """读取提示词里的缺失清单标记（只用于说明"没有记录"）。"""
        match = _MISSING_RE.search(system)
        if not match:
            return ""
        raw = match.group("body").split("MISSING_FACTS", 1)[0]
        items = [ln.strip().lstrip("-* ").strip() for ln in raw.splitlines() if ln.strip()]
        cleaned = [re.sub(r"^[^：:]{0,12}[：:]", "", item) for item in items]
        return "、".join(cleaned[:6])


def build_llm() -> BaseLLM:
    """按配置装配 LLM：有 Key 用真模型，没有就用 Mock（保证项目能跑）。"""
    if config.USE_MOCK:
        return MockLLM()
    return OpenAICompatLLM(
        api_key=config.LLM_API_KEY,
        base_url=config.LLM_BASE_URL,
        model=config.LLM_MODEL,
        timeout=config.LLM_TIMEOUT,
        temperature=config.LLM_TEMPERATURE,
    )


def parse_action(text: str) -> Optional[dict]:
    """从模型输出里解析工具决策 JSON（容忍 ```json 包裹与前后噪声）。"""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?|```$", "", cleaned).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None
