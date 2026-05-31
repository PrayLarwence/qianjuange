"""程序化 AI 腔检测。

在 Author 输出写入 DB 前跑一遍正则扫描，返回违规列表。
不依赖 LLM 自律——纯 regex + 统计。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class LintViolation:
    rule: str
    detail: str
    severity: int = 1  # 1=minor, 2=major


@dataclass
class LintResult:
    violations: list[LintViolation] = field(default_factory=list)
    score: int = 0  # 总扣分

    @property
    def passed(self) -> bool:
        return self.score < FAIL_THRESHOLD


FAIL_THRESHOLD = 4  # 总分 >=4 判定不通过


# ── 检测规则 ──────────────────────────────────────────────

_DASH_RE = re.compile(r"——")
_AI_PHRASES = [
    (re.compile(r"那一瞬间"), "「那一瞬间」"),
    (re.compile(r"隐隐"), "「隐隐」"),
    (re.compile(r"不是.{1,8}。是.{1,8}。"), "「不是X。是Y。」句式"),
    (re.compile(r"像有什么东西"), "「像有什么东西」"),
    (re.compile(r"某种.{0,4}的.{0,6}在"), "「某种…的…在」"),
    (re.compile(r"说不清"), "「说不清」"),
    (re.compile(r"仿佛.{0,10}一般"), "「仿佛…一般」"),
    (re.compile(r"第一次.{0,6}意识到"), "「第一次意识到」"),
    (re.compile(r"心底.{0,4}(涌|升|浮)"), "「心底涌/升/浮」"),
]
_CONCESSION_RE = re.compile(r"虽然.{2,30}但.{2,20}(至少|起码|好歹|总算)")
_TRAILING_PHILOSOPHY_RE = re.compile(
    r"[。！？」][\s]*$"  # 段尾
)
_PHILOSOPHY_ENDINGS = re.compile(
    r"(也许.{2,15}才是.{2,15}[。]"
    r"|或许.{2,15}从来.{2,15}[。]"
    r"|这.{0,6}就是.{2,10}的意义[。]"
    r"|人.{0,6}总是.{2,15}[。]"
    r"|世界.{0,6}(从来|本来|终究).{2,15}[。])"
)
_ACTION_DECOMPOSE_RE = re.compile(
    r"(伸出|抬起|放下|收回|握住|松开|转过|低下|抬头|侧过).{0,6}"
    r"(伸出|抬起|放下|收回|握住|松开|转过|低下|抬头|侧过)"
)


def lint_text(text: str) -> LintResult:
    """对一段文本跑全部规则，返回 LintResult。"""
    violations: list[LintViolation] = []

    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]

    # 1. 破折号密度
    for i, para in enumerate(paragraphs):
        count = len(_DASH_RE.findall(para))
        if count > 1:
            violations.append(LintViolation(
                rule="dash_density",
                detail=f"第{i+1}段有{count}个破折号",
                severity=2,
            ))

    # 2. AI 高频短语
    phrase_hits = 0
    for pattern, label in _AI_PHRASES:
        matches = pattern.findall(text)
        if matches:
            phrase_hits += len(matches)
            if len(matches) >= 2:
                violations.append(LintViolation(
                    rule="ai_phrase",
                    detail=f"{label}出现{len(matches)}次",
                    severity=2,
                ))
            else:
                violations.append(LintViolation(
                    rule="ai_phrase",
                    detail=f"{label}出现1次",
                    severity=1,
                ))

    # 3. 让步转折堆叠
    concession_count = len(_CONCESSION_RE.findall(text))
    if concession_count >= 2:
        violations.append(LintViolation(
            rule="concession_stack",
            detail=f"让步转折句式出现{concession_count}次",
            severity=2,
        ))

    # 4. 段尾哲理收束
    philosophy_count = len(_PHILOSOPHY_ENDINGS.findall(text))
    if philosophy_count >= 2:
        violations.append(LintViolation(
            rule="trailing_philosophy",
            detail=f"段尾哲理句出现{philosophy_count}次",
            severity=2,
        ))
    elif philosophy_count == 1:
        violations.append(LintViolation(
            rule="trailing_philosophy",
            detail="段尾哲理句出现1次",
            severity=1,
        ))

    # 5. 动作分解癖
    decompose_count = len(_ACTION_DECOMPOSE_RE.findall(text))
    if decompose_count >= 2:
        violations.append(LintViolation(
            rule="action_decompose",
            detail=f"连续微动作分解出现{decompose_count}处",
            severity=2,
        ))

    # 6. 修辞密度均匀性（段落长度方差过低 = 每段都差不多长 = AI 特征）
    if len(paragraphs) >= 4:
        lengths = [len(p) for p in paragraphs]
        mean_len = sum(lengths) / len(lengths)
        if mean_len > 0:
            cv = (sum((l - mean_len) ** 2 for l in lengths) / len(lengths)) ** 0.5 / mean_len
            if cv < 0.15:
                violations.append(LintViolation(
                    rule="uniform_length",
                    detail=f"段落长度变异系数={cv:.2f}，过于均匀",
                    severity=1,
                ))

    score = sum(v.severity for v in violations)
    return LintResult(violations=violations, score=score)


def format_lint_feedback(result: LintResult) -> str:
    """把 lint 结果格式化为可以喂给 LLM 的反馈文本。"""
    lines = ["# 程序化风格检测未通过（以下问题必须修正）"]
    for v in result.violations:
        prefix = "⚠️" if v.severity == 1 else "❌"
        lines.append(f"{prefix} [{v.rule}] {v.detail}")
    lines.append("\n修改要求：消除上述问题，保持原文内容和长度不变。")
    return "\n".join(lines)
