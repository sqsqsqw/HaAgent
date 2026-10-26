"""联网工具：网页搜索 + 网页正文抓取。

设计原则：不依赖任何付费 API、不需要 API key，纯 HTTP 请求 + 自己解析。
搜索走多源降级：
  1) Bing RSS（国内可直连，返回规范 XML，首选）
  2) DuckDuckGo HTML（海外网络可用）
  3) 360 搜索 HTML（最后兜底）
抓取网页则自己写了个 HTMLParser，把标签剥掉留正文，不引入 bs4/readability 之类依赖。
"""

from __future__ import annotations

import gzip
import html
import re
import urllib.error
import urllib.parse
import urllib.request
import zlib
from html.parser import HTMLParser

from langchain.tools import tool

from haagent.utils.timer_utils import timer

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 15
MAX_PAGE_CHARS = 8000

# 抓正文时整块丢弃的标签
_DROP_TAGS = {"script", "style", "noscript", "svg", "iframe", "head", "template"}
# 在这些标签结束时补一个换行，避免所有文字黏成一段
_BLOCK_TAGS = {"p", "br", "div", "section", "article", "li", "tr", "h1", "h2", "h3",
               "h4", "h5", "h6", "ul", "ol", "table", "pre", "blockquote", "dd", "dt"}


# ---------------------------------------------------------------- HTML 处理

class _TextExtractor(HTMLParser):
    """把 HTML 变成纯文本：丢掉脚本样式、块级标签处换行、标题单独记下来。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._drop_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in _DROP_TAGS:
            self._drop_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _DROP_TAGS:
            self._drop_depth = max(0, self._drop_depth - 1)
        elif tag == "title":
            self._in_title = False
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._drop_depth:
            return
        if self._in_title:
            self.title += data.strip()
        self.parts.append(data)

    def text(self) -> str:
        raw = html.unescape("".join(self.parts))
        lines = [re.sub(r"[ \t\u00a0]+", " ", ln).strip() for ln in raw.splitlines()]
        out: list[str] = []
        for line in lines:
            if not line:
                if out and out[-1] == "":
                    continue          # 折叠连续空行
            out.append(line)
        return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def html_to_text(markup: str) -> tuple[str, str]:
    """返回 (标题, 正文)。"""
    parser = _TextExtractor()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:
        # 解析器碰到畸形 HTML 可能抛错，退化成暴力去标签
        plain = re.sub(r"<[^>]+>", " ", markup)
        return "", re.sub(r"\s+", " ", html.unescape(plain)).strip()
    return parser.title.strip(), parser.text()


def strip_tags(markup: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", markup))).strip()


# ---------------------------------------------------------------- HTTP 封装

def _http_get(url: str, timeout: int = DEFAULT_TIMEOUT, referer: str | None = None) -> tuple[bytes, str]:
    """发起 GET 请求，返回 (原始字节, Content-Type)。自动处理 gzip/deflate。"""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
    }
    if referer:
        headers["Referer"] = referer
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read()
        encoding = (response.headers.get("Content-Encoding") or "").lower()
        content_type = response.headers.get("Content-Type") or ""
    if "gzip" in encoding:
        try:
            data = gzip.decompress(data)
        except OSError:
            pass
    elif "deflate" in encoding:
        try:
            data = zlib.decompress(data)
        except zlib.error:
            try:
                data = zlib.decompress(data, -zlib.MAX_WBITS)
            except zlib.error:
                pass
    return data, content_type


def _decode_body(data: bytes, content_type: str) -> str:
    """按响应头里的 charset 解码，没有就依次试 utf-8 / gbk。"""
    match = re.search(r"charset=([\w-]+)", content_type, re.IGNORECASE)
    candidates = []
    if match:
        candidates.append(match.group(1).lower())
    candidates += ["utf-8", "gbk", "latin-1"]
    for enc in candidates:
        if enc in ("gb2312", "gbk"):
            enc = "gb18030"
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _format_results(query: str, source: str, items: list[dict]) -> str:
    if not items:
        return f"[{source}] 没有搜索到「{query}」的结果"
    lines = [f"# 「{query}」搜索结果（来源 {source}，共 {len(items)} 条）"]
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. {item['title']}")
        if item.get("url"):
            lines.append(f"   链接: {item['url']}")
        if item.get("snippet"):
            lines.append(f"   摘要: {item['snippet'][:300]}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 各搜索源

def _search_bing(query: str, limit: int) -> list[dict]:
    """Bing RSS：免费、无需 key，返回规范的 XML，国内可直连。"""
    import xml.etree.ElementTree as ET

    quoted = urllib.parse.quote_plus(query)
    last_error: Exception | None = None
    for host in ("cn.bing.com", "www.bing.com"):
        url = f"https://{host}/search?q={quoted}&format=RSS&count={limit}"
        try:
            data, content_type = _http_get(url)
            root = ET.fromstring(data)
        except (urllib.error.URLError, ET.ParseError, OSError) as e:
            last_error = e
            continue
        items = []
        for node in root.findall("./channel/item")[:limit]:
            items.append({
                "title": (node.findtext("title") or "").strip(),
                "url": (node.findtext("link") or "").strip(),
                "snippet": strip_tags(node.findtext("description") or ""),
            })
        if items:
            return items
    if last_error:
        raise last_error
    return []


def _search_duckduckgo(query: str, limit: int) -> list[dict]:
    """DuckDuckGo 的无 JS 页面（国内一般被墙，作为海外环境备选）。"""
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(query)
    data, content_type = _http_get(url)
    page = _decode_body(data, content_type)
    pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        re.DOTALL,
    )
    items = []
    for href, title, snippet in pattern.findall(page)[:limit]:
        href = html.unescape(href)
        # DDG 会把真实地址藏在 uddg 参数里
        match = re.search(r"uddg=([^&]+)", href)
        if match:
            href = urllib.parse.unquote(match.group(1))
        items.append({"title": strip_tags(title), "url": href, "snippet": strip_tags(snippet)})
    return items


def _search_360(query: str, limit: int) -> list[dict]:
    """360 搜索兜底：只取标题和链接，摘要结构太乱就不解析了。"""
    url = "https://www.so.com/s?q=" + urllib.parse.quote_plus(query)
    data, content_type = _http_get(url)
    page = _decode_body(data, content_type)
    items, seen = [], set()
    for href, title_html in re.findall(r'<h3[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.DOTALL):
        href = html.unescape(href)
        title = strip_tags(title_html)
        if not title or href.startswith("javascript") or href in seen:
            continue
        seen.add(href)
        items.append({"title": title, "url": href, "snippet": ""})
        if len(items) >= limit:
            break
    return items


_SEARCH_SOURCES = (
    ("Bing", _search_bing),
    ("DuckDuckGo", _search_duckduckgo),
    ("360", _search_360),
)


# -------------------------------------------------------------------- 工具实现

@tool
@timer
def web_search(query: str, max_results: int = 5) -> str:
    """联网搜索，返回标题、链接和摘要。无需 API key，多源自动降级。

    参数：
    - query：搜索关键词，可以是一句话
    - max_results：返回条数，默认 5，最大 10
    """
    print(f"🌐  开始联网搜索: {query}", end="")
    query = str(query).strip()
    if not query:
        return "搜索失败：关键词为空"
    limit = max(1, min(int(max_results), 10))

    errors = []
    for name, func in _SEARCH_SOURCES:
        try:
            items = func(query, limit)
        except Exception as e:                      # 单个源失败就换下一个
            errors.append(f"{name}: {type(e).__name__} {e}")
            continue
        if items:
            return _format_results(query, name, items)
        errors.append(f"{name}: 无结果")

    return "搜索失败，所有搜索源都没取到结果：\n" + "\n".join(f"- {e}" for e in errors)


@tool
@timer
def fetch_web_page(url: str, max_chars: int = MAX_PAGE_CHARS) -> str:
    """抓取网页并提取正文文本（自动去脚本、样式、标签），返回标题和正文。

    参数：
    - url：网页地址，必须以 http:// 或 https:// 开头
    - max_chars：正文最大字符数，默认 8000
    """
    print(f"📥  开始抓取网页: {url}", end="")
    url = str(url).strip()
    if not url.lower().startswith(("http://", "https://")):
        if re.match(r"^[\w.-]+\.[a-z]{2,}", url, re.IGNORECASE):
            url = "https://" + url
        else:
            return "抓取失败：url 需要以 http:// 或 https:// 开头"

    limit = max(500, min(int(max_chars), 30000))
    try:
        data, content_type = _http_get(url)
    except urllib.error.HTTPError as e:
        return f"抓取失败：HTTP {e.code} {e.reason}"
    except urllib.error.URLError as e:
        return f"抓取失败：网络错误 {e.reason}"
    except Exception as e:
        return f"抓取失败：{type(e).__name__} {e}"

    body = _decode_body(data, content_type)
    if "html" not in content_type.lower() and not body.lstrip().startswith("<"):
        return f"# {url}\n（非 HTML 内容，{len(body)} 字符）\n" + body[:limit]

    title, text = html_to_text(body)
    if not text:
        return f"抓取成功但没解析出正文：{url}（页面可能是纯 JS 渲染）"
    if len(text) > limit:
        text = text[:limit] + f"\n...（正文已截断，原文共 {len(text)} 字符）"
    return f"# {title or url}\n来源: {url}\n\n{text}"


@tool
@timer
def web_search_and_read(query: str, max_results: int = 3, max_chars: int = 3000) -> str:
    """先搜索，再依次抓取前几条结果的正文，一次性给出带出处的资料。

    适合需要看具体内容而不是只看摘要的场景。

    参数：
    - query：搜索关键词
    - max_results：抓取几条结果，默认 3，最大 5
    - max_chars：每条正文最多保留多少字符
    """
    print(f"🔎  开始搜索并阅读: {query}", end="")
    query = str(query).strip()
    limit = max(1, min(int(max_results), 5))
    per_page = max(500, min(int(max_chars), 8000))

    errors = []
    for name, func in _SEARCH_SOURCES:
        try:
            items = func(query, limit)
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__} {e}")
            continue
        if not items:
            errors.append(f"{name}: 无结果")
            continue

        blocks = [f"# 关于「{query}」的搜索结果与正文（来源 {name}）"]
        for i, item in enumerate(items, 1):
            blocks.append(f"\n## {i}. {item['title']}\n链接: {item['url']}")
            if item.get("snippet"):
                blocks.append(f"摘要: {item['snippet'][:200]}")
            if not item.get("url", "").lower().startswith(("http://", "https://")):
                continue
            try:
                data, content_type = _http_get(item["url"], timeout=12)
                _, text = html_to_text(_decode_body(data, content_type))
                if text:
                    blocks.append("正文:\n" + (text[:per_page] + "..." if len(text) > per_page else text))
                else:
                    blocks.append("正文: （页面无可解析文本）")
            except Exception as e:
                blocks.append(f"正文抓取失败: {type(e).__name__} {e}")
        return "\n".join(blocks)

    return "搜索失败：\n" + "\n".join(f"- {e}" for e in errors)


web_tools = [web_search, fetch_web_page, web_search_and_read]
