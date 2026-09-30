import json

import httpx
import respx

from app.tools.search.tavily import TavilySearchProvider


@respx.mock
async def test_tavily_provider_sends_quality_options_and_parses_metadata() -> None:
    route = respx.post("https://api.tavily.com/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "LangGraph 文档",
                        "url": "https://docs.example.com/langgraph",
                        "content": "搜索摘要",
                        "raw_content": "完整网页正文",
                        "score": 0.92,
                    }
                ]
            },
        )
    )
    provider = TavilySearchProvider(
        api_key="test-key",
        api_url="https://api.tavily.com/search",
        include_domains=["docs.example.com"],
        exclude_domains=["noise.example.com"],
    )

    results = await provider.search("LangGraph", limit=3)
    request_payload = json.loads(route.calls.last.request.content)

    assert request_payload["include_raw_content"] is True
    assert request_payload["include_domains"] == ["docs.example.com"]
    assert request_payload["exclude_domains"] == ["noise.example.com"]
    assert results[0].content == "完整网页正文"
    assert results[0].score == 0.92
