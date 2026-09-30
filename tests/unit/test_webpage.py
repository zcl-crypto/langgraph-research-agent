import httpx
import pytest

from app.core.exceptions import WebPageReadError
from app.tools.webpage import read_webpage


@pytest.mark.asyncio
async def test_read_webpage_extracts_main_text() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=(
                "<html><head><title>测试页面</title><script>bad()</script></head>"
                "<body><nav>菜单</nav><main><h1>研究标题</h1>"
                "<p>这里是需要保留的有效研究正文，长度足够用于测试。</p></main></body></html>"
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        page = await read_webpage("https://example.com/article", client=client)

    assert page.title == "测试页面"
    assert "有效研究正文" in page.content
    assert "菜单" not in page.content
    assert "bad()" not in page.content


@pytest.mark.asyncio
async def test_read_webpage_rejects_private_ip() -> None:
    with pytest.raises(WebPageReadError):
        await read_webpage("http://127.0.0.1/private")


@pytest.mark.asyncio
async def test_read_webpage_limits_extracted_content_length() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=f"<html><body><main>{'valid research content ' * 20}</main></body></html>",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        page = await read_webpage(
            "https://example.com/long-article",
            max_chars=80,
            client=client,
        )

    assert len(page.content) == 80
