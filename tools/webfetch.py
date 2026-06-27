"""
GrassFlow WebFetch 工具

获取网页内容并转换为 Markdown，参考 opencode 的 WebFetch 实现。
"""

import logging
from typing import Any, Dict
from .tool import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)

# 最大返回字符数
MAX_CONTENT_LENGTH = 10000


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
            return ToolResult(
                output="Error: html2text is not installed. Run: pip install html2text",
                title="webfetch",
                metadata={"error": "missing_dependency"},
            )

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
        else:
            # 将 HTML 转换为 Markdown
            converter = html2text.HTML2Text()
            converter.ignore_links = False
            converter.ignore_images = True
            converter.ignore_emphasis = False
            converter.body_width = 0  # 不自动换行
            converter.ignore_tables = False
            converter.single_line_break = True
            markdown_content = converter.handle(raw_text)

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
