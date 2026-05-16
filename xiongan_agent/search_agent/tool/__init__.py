# search_agent/tool/__init__.py

from .duckduckgo_search_tool import make_search_tool
from .fetch_webcontent_bymcp import langgraph_fetch_web_content
from .pdf_fallback import fetch_url_via_pdf
from .baidu_search_appbuilder import baidu_search_fallback
from .baidu_mcp_search import baidu_mcp_search_sync

__all__ = [
    "make_search_tool",
    "langgraph_fetch_web_content",
    "fetch_url_via_pdf",
    "baidu_search_fallback",
    "baidu_mcp_search_sync",
]
