# -*- coding: utf-8 -*-
"""Function Calling 工具集。

每个工具都是**真实可用**的能力（不是占位）：简历条目生成、数字口径一致性
检查、模拟面试出题、档案提问、概览生成——全部基于结构化知识库，
因此结果可复现、可测试。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from knowledge import Chunk, KnowledgeBase

import config

# 简历条目里需要保留的量化信号（没有数字的条目排在后面）
_NUMBER_RE = re.compile(r"\d")
_PERIOD_RE = re.compile(r"时间[与和]?角色[:：]\s*(?P<period>[^，,。;；]+)")
_GENERIC_FOLLOWUPS = [
    "这个项目如果 QPS 提升到 500，你会怎么改造？",
    "项目里最难的取舍是什么，为什么这么选？",
    "如果让你重做一遍，你会改哪里？",
    "这套设计怎么证明它真的有效（指标与评测）？",
    "线上出故障时，你怎么定位是这个模块的问题？",
    "为什么用现在这套技术，而不是更简单的方案？",
    "这个项目里你亲手写的代码占多少，难点在哪一段？",
    "如果要把它做成团队可维护的工程，下一步补什么？",
]
_INTERVIEW_LINE_RE = re.compile(r"面试考点[:：]?\s*(?P<body>.+)")
# 这些不是"做出来的成果"，不能进简历条目（Roadmap / 待办 / 限制说明）
_NOT_ACHIEVEMENT_RE = re.compile(r"未实现|尚未|优化方向|roadmap|todo|待补|未做|面试考点|隐私规则|简历未提及")
# 条目里的元信息行（时间/仓库/技术栈/定位）也不是成果描述
_META_LINE_RE = re.compile(r"^(时间|仓库|技术栈|定位|角色|简历未提及|隐私规则)[^：:]{0,8}[：:]")
# 带单位的量化数据最值钱（秒 / % / 个 / 字 / 块 …）
_QUANTIFIED_RE = re.compile(r"\d+(\.\d+)?\s*(秒|毫秒|s\b|%|个|字|块|页|倍|条|张|轮|QPS)")
_ACHIEVE_VERBS = ("实现", "改造", "降低", "降到", "提升", "支持", "完成", "构建", "接入",
                  "优化", "设计", "落地", "保证", "沉淀", "复用", "兜底", "评测", "验证")


@dataclass
class Tool:
    """一个可被 Function Calling 调用的工具。"""

    name: str
    description: str
    parameters: dict
    func: Callable[..., dict]

    def run(self, **kwargs) -> dict:
        return self.func(**kwargs)

    def as_spec(self) -> dict:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


def build_tools(kb: KnowledgeBase) -> Dict[str, Tool]:
    """装配工具注册表。"""

    def query_knowledge(keyword: str = "", domain: Optional[str] = None, top_k: int = 3) -> dict:
        hits = kb.search(keyword, top_k=top_k, threshold=config.RELEVANCE_THRESHOLD)
        if domain:
            hits = [h for h in hits if h.chunk.doc == domain] or hits
        if not hits:
            return {"ok": False, "text": f"知识库里没有与「{keyword}」相关的条目。"}
        lines = [f"[{h.chunk.id}] {h.chunk.title}（相关度 {h.score:.2f}）" for h in hits]
        return {"ok": True, "text": "命中条目：\n" + "\n".join(lines),
                "data": {"hits": [h.as_dict() for h in hits]}}

    def draft_resume_bullet(project_id: str = "PROJECT-01", role: str = "") -> dict:
        chunk = kb.get(project_id)
        if chunk is None:
            return {"ok": False, "text": f"没有找到项目 {project_id}，可用项目：{_project_ids(kb)}"}
        bullets = chunk.bullets
        ranked = sorted(bullets, key=_bullet_rank)
        picked = [b for b in ranked[:3] if len(b) > 6]
        period = _PERIOD_RE.search(chunk.text)
        header = f"{chunk.title}" + (f"｜{period.group('period')}" if period else "")
        if role:
            header += f"（面向：{role}）"
        lines = [header] + [f"- {b}" for b in picked]
        return {"ok": True, "text": "可直接粘贴进简历的项目条目：\n" + "\n".join(lines),
                "data": {"project": chunk.id, "header": header, "bullets": picked}}

    def check_number_consistency() -> dict:
        chunk = kb.get("PROJECT-10")
        conflicts: List[dict] = []
        if chunk is not None:
            for line in chunk.text.splitlines():
                if not line.strip().startswith("|"):
                    continue
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) < 3 or set(cells[0]) <= set("-: "):
                    continue
                if cells[0] in {"项目", "条目"}:
                    continue
                conflicts.append({"item": cells[0], "variants": cells[1], "adopted": cells[2]})
        if not conflicts:
            return {"ok": True, "text": "没有发现数字口径冲突记录。", "data": {"conflicts": []}}
        lines = [f"- {c['item']}：版本间为 {c['variants']}，对外统一用「{c['adopted']}」" for c in conflicts]
        return {"ok": True, "text": "数字口径冲突（对外材料统一按「采用」列写）：\n" + "\n".join(lines),
                "data": {"conflicts": conflicts}}

    def mock_interview(project_id: str = "PROJECT-01", count: int = 5) -> dict:
        chunk = kb.get(project_id)
        if chunk is None:
            return {"ok": False, "text": f"没有找到项目 {project_id}，可用项目：{_project_ids(kb)}"}
        questions: List[str] = []
        for line in chunk.text.splitlines():
            stripped = line.strip()
            match = _INTERVIEW_LINE_RE.search(stripped)
            if match:
                questions.extend(q.strip() for q in re.split(r"[；;]", match.group("body")) if q.strip())
        for extra in _GENERIC_FOLLOWUPS:
            if len(questions) >= count:
                break
            questions.append(extra)
        questions = questions[:max(1, count)]
        numbered = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions))
        return {"ok": True, "text": f"针对《{chunk.title}》的模拟面试题：\n{numbered}",
                "data": {"project": chunk.id, "questions": questions}}

    def summarize_profile() -> dict:
        basic = kb.get("PROFILE-01")
        career = kb.get("PROFILE-04")
        skill = kb.get("PROFILE-03")
        if basic is None:
            return {"ok": False, "text": "知识库里没有档案条目。"}
        school = _first_match(basic.text, r"学校[:：]\s*(.+)")
        major = _first_match(basic.text, r"专业\s*/\s*学历[:：]\s*(.+)")
        grade = _first_match(basic.text, r"届别[:：]\s*(.+)")
        direction = ""
        if career is not None:
            first = career.bullets[0] if career.bullets else ""
            direction = first
        top_skill = ""
        if skill is not None:
            ai_line = next((b for b in skill.bullets if b.startswith("AI 与大模型")), "")
            top_skill = ai_line
        text = (
            f"{school} · {major} · {grade}\n"
            f"主攻方向：{direction}\n"
            f"代表技能：{top_skill}\n"
            f"参考：[PROFILE-01]、[PROFILE-03]、[PROFILE-04]"
        )
        return {"ok": True, "text": text,
                "data": {"school": school, "major": major, "grade": grade,
                         "direction": direction, "skill": top_skill}}

    tools = [
        Tool("query_knowledge", "按关键词检索个人知识库，返回命中的条目编号与标题。",
             {"type": "object", "properties": {
                 "keyword": {"type": "string", "description": "检索关键词"},
                 "domain": {"type": "string", "enum": ["profile", "projects", "job_search"],
                            "description": "限定知识域（可选）"},
                 "top_k": {"type": "integer", "description": "返回条数，默认 3"}},
              "required": ["keyword"]}, query_knowledge),
        Tool("draft_resume_bullet", "从项目条目生成可直接粘贴进简历的 STAR 条目（保留量化数据）。",
             {"type": "object", "properties": {
                 "project_id": {"type": "string", "description": "条目号，如 PROJECT-01"},
                 "role": {"type": "string", "description": "目标岗位方向（可选）"}},
              "required": []}, draft_resume_bullet),
        Tool("check_number_consistency", "检查简历版本之间的数字口径冲突，返回统一采用的口径。",
             {"type": "object", "properties": {}}, check_number_consistency),
        Tool("mock_interview", "针对某个项目生成模拟面试题（含追问方向）。",
             {"type": "object", "properties": {
                 "project_id": {"type": "string", "description": "条目号，如 PROJECT-02"},
                 "count": {"type": "integer", "description": "题目数量，默认 5"}},
              "required": []}, mock_interview),
        Tool("summarize_profile", "输出三行式个人概览（学校/方向/代表技能），用于自我介绍开头。",
             {"type": "object", "properties": {}}, summarize_profile),
    ]
    return {tool.name: tool for tool in tools}


def _project_ids(kb: KnowledgeBase) -> str:
    return ", ".join(c.id for c in kb.by_doc("projects"))


def _bullet_rank(bullet: str) -> tuple:
    """简历条目排序：排除非成果行 → 排除元信息行 → 优先带单位量化 → 优先有动作动词 → 信息量大的。"""
    return (
        1 if _NOT_ACHIEVEMENT_RE.search(bullet) else 0,
        1 if _META_LINE_RE.match(bullet) else 0,
        0 if _QUANTIFIED_RE.search(bullet) else (0 if _NUMBER_RE.search(bullet) else 1),
        0 if any(verb in bullet for verb in _ACHIEVE_VERBS) else 1,
        -len(bullet),
    )


def _first_match(text: str, pattern: str) -> str:
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def tool_prompt_block(tools: Dict[str, Tool]) -> str:
    """把工具清单渲染进提示词（供模型决策；Mock 也从这里解析可用工具）。"""
    lines = [f"AVAILABLE_TOOLS: {', '.join(tools)}"]
    for tool in tools.values():
        lines.append(f"- {tool.name}: {tool.description}")
    return "\n".join(lines)


def chunks_preview(chunks: List[Chunk]) -> str:  # 便于测试与调试
    return "\n".join(f"[{c.id}] {c.title}" for c in chunks)
