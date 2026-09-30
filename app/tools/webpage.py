import ipaddress
import logging
from time import perf_counter
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.core.context import get_current_task_id
from app.core.exceptions import WebPageReadError
from app.core.security import sanitize_untrusted_text
from app.models.research import WebPageResult

logger = logging.getLogger(__name__)


def _validate_url(url: str) -> None:
    """拒绝明显危险的协议、本机地址和私有 IP。"""

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise WebPageReadError("只允许读取有效的 HTTP/HTTPS URL")
    hostname = parsed.hostname.lower()
    if hostname == "localhost" or hostname.endswith(".local"):
        raise WebPageReadError("不允许读取本机或局域网地址")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return
    if not address.is_global:
        raise WebPageReadError("不允许读取私有、环回或保留 IP 地址")


async def read_webpage(
    url: str,
    *,
    timeout: float = 15.0,
    max_chars: int = 12_000,
    client: httpx.AsyncClient | None = None,
) -> WebPageResult:
    """下载网页并提取适合模型处理的正文。"""

    owns_client = client is None
    task_id = get_current_task_id()
    started_at = perf_counter()
    hostname = urlparse(url).hostname or "unknown"
    logger.info(
        "[task_id=%s] tool=read_webpage 开始：host=%s",
        task_id,
        hostname,
    )
    http_client = client or httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": "LangGraphResearchAgent/0.1"},
    )
    current_url = url
    try:
        for _ in range(4):
            _validate_url(current_url)
            response = await http_client.get(current_url, follow_redirects=False)
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise WebPageReadError("网页重定向缺少目标地址")
                current_url = urljoin(current_url, location)
                continue
            response.raise_for_status()
            break
        else:
            raise WebPageReadError("网页重定向次数过多")

        content_type = response.headers.get("content-type", "").lower()
        if content_type and "text/" not in content_type and "html" not in content_type:
            raise WebPageReadError(f"不支持的网页内容类型：{content_type}")
        if len(response.content) > max_chars * 8:
            raise WebPageReadError("网页响应过大")

        soup = BeautifulSoup(response.text, "lxml")
        for element in soup(["script", "style", "noscript", "nav", "footer", "svg"]):
            element.decompose()
        body = soup.find("article") or soup.find("main") or soup.body or soup
        extracted_content = " ".join(body.stripped_strings)
        sanitized = sanitize_untrusted_text(extracted_content, max_chars=max_chars)
        content = sanitized.text
        if len(content) < 20:
            raise WebPageReadError("网页正文为空或过短")
        title = soup.title.get_text(" ", strip=True) if soup.title else current_url
        logger.info(
            "[task_id=%s] tool=read_webpage 完成：host=%s duration_ms=%.1f chars=%d",
            task_id,
            hostname,
            (perf_counter() - started_at) * 1000,
            len(content),
        )
        return WebPageResult(title=title, url=current_url, content=content)
    except WebPageReadError:
        logger.warning(
            "[task_id=%s] tool=read_webpage 失败：host=%s duration_ms=%.1f",
            task_id,
            hostname,
            (perf_counter() - started_at) * 1000,
        )
        raise
    except httpx.HTTPError as exc:
        logger.warning(
            "[task_id=%s] tool=read_webpage 失败：host=%s duration_ms=%.1f type=%s",
            task_id,
            hostname,
            (perf_counter() - started_at) * 1000,
            type(exc).__name__,
        )
        raise WebPageReadError(f"网页请求失败：{exc}") from exc
    except Exception as exc:
        logger.warning(
            "[task_id=%s] tool=read_webpage 失败：host=%s duration_ms=%.1f type=%s",
            task_id,
            hostname,
            (perf_counter() - started_at) * 1000,
            type(exc).__name__,
        )
        raise WebPageReadError(f"网页解析失败：{exc}") from exc
    finally:
        if owns_client:
            await http_client.aclose()
