"""
GrassFlow WebFetch 工具

获取网页内容并转换为 Markdown，参考 opencode 的 WebFetch 实现。
"""

import logging
import re
from typing import Any, Dict
from .tool import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)

# 最大返回字符数
MAX_CONTENT_LENGTH = 10000


def _simple_html_to_text(html: str) -> str:
    """
    简单的 HTML 转文本降级方案。
    当 html2text 不可用时使用，剥离 HTML 标签并保留基本结构。
    """
    # 移除 script 和 style 标签及其内容
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # 将块级标签转换为换行
    text = re.sub(r"<(br|hr|/p|/div|/li|/tr|/h[1-6])[^>]*>", "\n", text, flags=re.IGNORECASE)
    # 移除所有剩余 HTML 标签
    text = re.sub(r"<[^>]+>", "", text)
    # 解码常见 HTML 实体
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&nbsp;", " ").replace("&#39;", "'")
    # 合并多余空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class WebFetchTool(Tool):
    """
    WebFetch 工具 - 获取网页内容并转换为 Markdown

    使用 httpx 获取 URL 内容，使用 html2text 将 HTML 转换为 Markdown 文本。
    支持可选的 prompt 参数，用于指导提取特定信息。
    """

    @property
    def id(self) -> str:
        return "webfetch"

    @property
    def description(self) -> str:
        return (
            "Fetch a URL and return its content as markdown. "
            "Use this tool to read web pages, documentation, articles, or any "
            "publicly accessible URL. The content is converted to clean markdown "
            "and truncated to a reasonable length."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch. Must be a valid HTTP or HTTPS URL.",
                },
                "prompt": {
                    "type": "string",
                    "description": (
                        "Optional instructions for what to extract from the page. "
                        "If provided, the tool will include this hint in the output "
                        "to guide the LLM on how to interpret the content."
                    ),
                },
            },
            "required": ["url"],
        }

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        """执行网页获取"""
        url = params["url"]
        prompt = params.get("prompt", "")

        # 校验 URL scheme
        if not url.startswith(("http://", "https://")):
            return ToolResult(
                output=f"Error: URL must start with http:// or https://, got: {url}",
                title="webfetch",
                metadata={"error": "invalid_url", "url": url},
            )

        try:
            import httpx
        except ImportError:
            return ToolResult(
                output="Error: httpx is not installed. Run: pip install httpx",
                title="webfetch",
                metadata={"error": "missing_dependency"},
            )

        try:
            import html2text
        except ImportError:
            html2text = None
            logger.warning("html2text not installed, using simple HTML-to-text fallback")

        # 发起 HTTP 请求
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=30.0,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,*/*",
                },
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.TimeoutException:
            return ToolResult(
                output=f"Error: Request to {url} timed out after 30 seconds.",
                title="webfetch",
                metadata={"error": "timeout", "url": url},
            )
        except httpx.HTTPStatusError as e:
            return ToolResult(
                output=f"Error: HTTP {e.response.status_code} when fetching {url}",
                title="webfetch",
                metadata={"error": "http_error", "status_code": e.response.status_code, "url": url},
            )
        except httpx.RequestError as e:
            return ToolResult(
                output=f"Error: Failed to fetch {url}: {str(e)}",
                title="webfetch",
                metadata={"error": "request_failed", "url": url},
            )

        # 获取内容类型
        content_type = response.headers.get("content-type", "")
        raw_text = response.text

        # 如果是纯文本，直接返回
        if "text/plain" in content_type:
            markdown_content = raw_text
        elif html2text is not None:
            # 使用 html2text 将 HTML 转换为 Markdown
            converter = html2text.HTML2Text()
            converter.ignore_links = False
            converter.ignore_images = True
            converter.ignore_emphasis = False
            converter.body_width = 0  # 不自动换行
            converter.ignore_tables = False
            converter.single_line_break = True
            markdown_content = converter.handle(raw_text)
        else:
            # 降级：使用简单的 HTML 标签剥离
            markdown_content = _simple_html_to_text(raw_text)

        # 截断过长内容
        truncated = False
        if len(markdown_content) > MAX_CONTENT_LENGTH:
            markdown_content = markdown_content[:MAX_CONTENT_LENGTH]
            truncated = True

        # 构建输出
        output_parts = []
        output_parts.append(f"<url>{url}</url>")
        if prompt:
            output_parts.append(f"<prompt>{prompt}</prompt>")
        output_parts.append("<content>")
        output_parts.append(markdown_content)
        if truncated:
            output_parts.append(
                f"\n\n[Content truncated at {MAX_CONTENT_LENGTH} characters. "
                "The full page may contain more information.]"
            )
        output_parts.append("</content>")

        return ToolResult(
            output="\n".join(output_parts),
            title=url,
            metadata={
                "url": url,
                "content_type": content_type,
                "status_code": response.status_code,
                "content_length": len(markdown_content),
                "truncated": truncated,
            },
            truncated=truncated,
        )
