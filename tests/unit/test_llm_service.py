import pytest

from app.core.exceptions import LLMContentFilterError
from app.models.llm_outputs import FindingOutput
from app.services.llm import LLMService, _is_content_filter_error


class ProviderError(Exception):
    def __init__(self, body: dict[str, object]) -> None:
        super().__init__("provider request failed")
        self.body = body


def test_detects_zhipu_content_filter_error() -> None:
    error = ProviderError(
        {
            "contentFilter": [{"level": 2, "role": "user"}],
            "error": {"code": "1301", "message": "unsafe content"},
        }
    )

    assert _is_content_filter_error(error) is True


def test_does_not_treat_regular_provider_error_as_content_filter() -> None:
    error = ProviderError({"error": {"code": "429", "message": "rate limited"}})

    assert _is_content_filter_error(error) is False


@pytest.mark.asyncio
async def test_structured_content_filter_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    service = object.__new__(LLMService)
    service._structured_attempts = 2
    calls = 0

    async def reject_request(system_prompt: str, user_prompt: str) -> str:
        nonlocal calls
        calls += 1
        raise LLMContentFilterError("code=1301")

    monkeypatch.setattr(service, "ainvoke_text", reject_request)

    with pytest.raises(LLMContentFilterError):
        await service.ainvoke_structured(
            FindingOutput,
            "system",
            "user",
        )

    assert calls == 1
