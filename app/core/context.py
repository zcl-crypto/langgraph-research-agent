from contextvars import ContextVar
from dataclasses import dataclass

from app.core.exceptions import LLMServiceError


@dataclass
class TokenUsageTracker:
    """记录并限制单个研究任务的模型 Token 用量。"""

    limit: int
    input_tokens: int = 0
    output_tokens: int = 0
    call_count: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def begin_call(self, estimated_input_tokens: int) -> None:
        if self.total_tokens + estimated_input_tokens > self.limit:
            raise LLMServiceError(f"研究任务已达到 {self.limit} Token 限制")
        self.call_count += 1

    def record(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens += max(input_tokens, 0)
        self.output_tokens += max(output_tokens, 0)
        if self.total_tokens > self.limit:
            raise LLMServiceError(f"研究任务已超过 {self.limit} Token 限制")

current_task_id: ContextVar[str] = ContextVar("current_task_id", default="-")
current_token_usage: ContextVar[TokenUsageTracker | None] = ContextVar(
    "current_token_usage",
    default=None,
)


def get_current_task_id() -> str:
    """返回当前异步研究任务 ID，供模型和工具日志使用。"""

    return current_task_id.get()


def get_current_token_usage() -> TokenUsageTracker | None:
    """返回当前任务的 Token 统计器。"""

    return current_token_usage.get()
