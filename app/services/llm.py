import json
import logging
from time import perf_counter
from typing import Protocol, TypeVar

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.context import get_current_task_id, get_current_token_usage
from app.core.exceptions import (
    ConfigurationError,
    LLMContentFilterError,
    LLMServiceError,
)

ModelT = TypeVar("ModelT", bound=BaseModel)
logger = logging.getLogger(__name__)


def _is_content_filter_error(error: Exception) -> bool:
    """识别 OpenAI 兼容供应商返回的内容安全拒绝。"""

    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        body = getattr(current, "body", None)
        if isinstance(body, dict):
            provider_error = body.get("error")
            if isinstance(provider_error, dict) and str(provider_error.get("code")) == "1301":
                return True
            if body.get("contentFilter"):
                return True
        message = str(current).lower()
        if "1301" in message and (
            "contentfilter" in message or "不安全或敏感内容" in message
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


class LLMClient(Protocol):
    """节点依赖的最小模型接口，便于测试时替换。"""

    async def ainvoke_text(self, system_prompt: str, user_prompt: str) -> str:
        """返回普通文本。"""

    async def ainvoke_structured(
        self,
        schema: type[ModelT],
        system_prompt: str,
        user_prompt: str,
    ) -> ModelT:
        """返回经过 Pydantic 校验的结构化结果。"""


class LLMService:
    """统一封装所有 OpenAI 兼容模型调用。"""

    def __init__(self, settings: Settings) -> None:
        api_key = settings.api_key.get_secret_value()
        if not api_key:
            raise ConfigurationError(
                "缺少 LLM_API_KEY，请在 .env 中配置 OpenAI 兼容模型密钥"
            )
        if not settings.base_url.strip() or not settings.model_name.strip():
            raise ConfigurationError("LLM_BASE_URL 和 LLM_MODEL 不能为空")

        self._model = ChatOpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            model=settings.model_name,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            max_completion_tokens=settings.llm_max_output_tokens,
        )
        self._model_name = settings.model_name
        self._structured_attempts = 2

    async def ainvoke_text(self, system_prompt: str, user_prompt: str) -> str:
        """调用模型并将不同厂商的消息内容统一为字符串。"""

        task_id = get_current_task_id()
        usage_tracker = get_current_token_usage()
        estimated_input_tokens = max((len(system_prompt) + len(user_prompt)) // 4, 1)
        if usage_tracker:
            usage_tracker.begin_call(estimated_input_tokens)
        started_at = perf_counter()
        logger.info(
            "[task_id=%s] LLM 调用开始：model=%s",
            task_id,
            self._model_name,
        )
        try:
            response = await self._model.ainvoke(
                [("system", system_prompt), ("human", user_prompt)]
            )
        except Exception as exc:
            logger.error(
                "[task_id=%s] LLM 调用失败：model=%s duration_ms=%.1f type=%s",
                task_id,
                self._model_name,
                (perf_counter() - started_at) * 1000,
                type(exc).__name__,
            )
            if _is_content_filter_error(exc):
                raise LLMContentFilterError(
                    "模型供应商内容安全策略拒绝本次请求（code=1301）"
                ) from exc
            raise LLMServiceError(f"LLM 调用失败：{exc}") from exc

        content = response.content
        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            text = "".join(
                str(block.get("text", "")) if isinstance(block, dict) else str(block)
                for block in content
            ).strip()
        else:
            text = str(content).strip()
        if not text:
            raise LLMServiceError("LLM 返回了空内容")
        usage = getattr(response, "usage_metadata", None) or {}
        input_tokens = int(usage.get("input_tokens") or estimated_input_tokens)
        output_tokens = int(usage.get("output_tokens") or max(len(text) // 4, 1))
        if usage_tracker:
            usage_tracker.record(input_tokens, output_tokens)
        total_tokens = (
            usage_tracker.total_tokens
            if usage_tracker
            else int(usage.get("total_tokens") or input_tokens + output_tokens)
        )
        logger.info(
            (
                "[task_id=%s] LLM 调用完成：model=%s duration_ms=%.1f "
                "input_tokens=%s output_tokens=%s total_tokens=%s"
            ),
            task_id,
            self._model_name,
            (perf_counter() - started_at) * 1000,
            input_tokens,
            output_tokens,
            total_tokens,
        )
        return text

    async def ainvoke_structured(
        self,
        schema: type[ModelT],
        system_prompt: str,
        user_prompt: str,
    ) -> ModelT:
        """通过 JSON 提示与 Pydantic 校验兼容不同模型厂商。"""

        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        validation_hint = ""
        last_error: Exception | None = None
        for attempt in range(1, self._structured_attempts + 1):
            prompt = (
                f"{user_prompt}\n\n"
                "只返回一个填入实际内容的 JSON 数据实例，不要复制 JSON Schema 本身。"
                "不要使用 Markdown 代码块，也不要附加解释。\n"
                f"JSON Schema：{schema_json}{validation_hint}"
            )
            try:
                raw_text = await self.ainvoke_text(system_prompt, prompt)
                payload = self._parse_json_object(raw_text)
                return schema.model_validate(payload)
            except LLMContentFilterError:
                raise
            except (json.JSONDecodeError, ValidationError, LLMServiceError) as exc:
                last_error = exc
                logger.warning(
                    "[task_id=%s] LLM 结构化输出校验失败：attempt=%d/%d type=%s",
                    get_current_task_id(),
                    attempt,
                    self._structured_attempts,
                    type(exc).__name__,
                )
                validation_hint = (
                    "\n上一次回复不是符合约束的数据实例。"
                    "请填写实际字段值，不要返回 properties、$defs、type 等 Schema 定义。"
                )
        raise LLMServiceError(f"LLM 结构化输出校验失败：{last_error}") from last_error

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, object]:
        """从可能带少量包装文本的回复中提取 JSON 对象。"""

        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            cleaned = "\n".join(lines[1:-1]).strip()
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start < 0 or end <= start:
                raise
            payload = json.loads(cleaned[start : end + 1])
        if not isinstance(payload, dict):
            raise json.JSONDecodeError("模型输出不是 JSON 对象", cleaned, 0)
        return payload
