import re
import unicodedata
from dataclasses import dataclass

_INVISIBLE_CHARACTERS = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SUSPICIOUS_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions?", re.IGNORECASE),
    re.compile(r"reveal\s+(the\s+)?(system\s+)?prompt", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(in\s+)?developer\s+mode", re.IGNORECASE),
    re.compile(r"忽略.{0,12}(之前|以上).{0,8}(指令|提示)", re.IGNORECASE),
    re.compile(r"(泄露|输出|显示).{0,8}(系统提示|提示词|api.?key)", re.IGNORECASE),
)
_REDACTION_MARKER = "[疑似外部指令，已屏蔽]"
_DEFENSIVE_RESEARCH_REPLACEMENTS = (
    (re.compile(r"indirect\s+prompt[ -]?injection", re.IGNORECASE), "外部内容指令污染"),
    (re.compile(r"prompt[ -]?injection", re.IGNORECASE), "外部内容指令污染"),
    (re.compile(r"提示词?注入", re.IGNORECASE), "外部内容指令污染"),
    (re.compile(r"jailbreak", re.IGNORECASE), "模型安全边界风险"),
    (re.compile(r"越狱", re.IGNORECASE), "模型安全边界风险"),
    (re.compile(r"攻击", re.IGNORECASE), "安全风险"),
    (re.compile(r"恶意", re.IGNORECASE), "高风险"),
)


@dataclass(frozen=True)
class SanitizedContent:
    """规范化后的外部文本及其风险标记。"""

    text: str
    suspicious: bool


def sanitize_untrusted_text(text: str, *, max_chars: int) -> SanitizedContent:
    """清理外部文本，并屏蔽其中疑似要求模型执行的指令。"""

    normalized = unicodedata.normalize("NFKC", text)
    normalized = _INVISIBLE_CHARACTERS.sub("", normalized)
    normalized = _CONTROL_CHARACTERS.sub(" ", normalized)
    suspicious = any(pattern.search(normalized) for pattern in _SUSPICIOUS_PATTERNS)
    if suspicious:
        for pattern in _SUSPICIOUS_PATTERNS:
            normalized = pattern.sub(_REDACTION_MARKER, normalized)
    normalized = " ".join(normalized.split())[:max_chars]
    return SanitizedContent(text=normalized, suspicious=suspicious)


def neutralize_security_research_text(text: str) -> str:
    """把安全研究主题改写成不含操作性高风险词的防御表述。"""

    sanitized = sanitize_untrusted_text(text, max_chars=max(len(text) * 2, 1))
    neutralized = sanitized.text
    for pattern, replacement in _DEFENSIVE_RESEARCH_REPLACEMENTS:
        neutralized = pattern.sub(replacement, neutralized)
    return neutralized
