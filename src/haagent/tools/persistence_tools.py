"""持久化工具：给 Agent 一份跨会话不丢的「长期记忆」。

存成一个 JSON 文件（默认 ~/.haagent/memory.json，可用环境变量 HAAGENT_MEMORY_FILE 覆盖），
结构简单到肉眼可读、可以直接手改。写入用「临时文件 + 原子替换」，避免写一半断电把文件弄坏。
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path

from langchain.tools import tool

from haagent.utils.timer_utils import timer

_LOCK = threading.Lock()
MAX_LIST_ITEMS = 100


# ---------------------------------------------------------------- 存储层

def _store_path() -> Path:
    custom = os.environ.get("HAAGENT_MEMORY_FILE")
    if custom:
        return Path(custom).expanduser().resolve()
    return Path.home() / ".haagent" / "memory.json"


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _load() -> dict:
    path = _store_path()
    if not path.exists():
        return {"version": 1, "items": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # 文件损坏就备份一份，再从空表开始，避免越写越乱
        try:
            path.rename(path.with_suffix(f".broken-{int(time.time())}.json"))
        except OSError:
            pass
        return {"version": 1, "items": {}}
    if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
        return {"version": 1, "items": {}}
    data.setdefault("version", 1)
    return data


def _save(data: dict) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)      # 原子替换
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _normalize_key(key: str) -> str:
    return str(key).strip()


# ---------------------------------------------------------------- 工具实现

@tool
@timer
def remember(key: str, value: str, tags: str = "") -> str:
    """记住一条信息，跨会话保留（同名 key 会覆盖旧值并刷新更新时间）。

    参数：
    - key：短标签，便于之后按名取回，例如 "用户的编辑器偏好"
    - value：要记住的内容
    - tags：可选标签，逗号分隔，便于分类检索，例如 "偏好,工具"
    """
    print(f"🧠  开始记忆: {key}", end="")
    key = _normalize_key(key)
    if not key:
        return "记忆失败：key 不能为空"

    tag_list = [t.strip() for t in str(tags).replace("，", ",").split(",") if t.strip()]
    with _LOCK:
        data = _load()
        items = data["items"]
        old = items.get(key)
        created = old.get("created_at") if isinstance(old, dict) else None
        items[key] = {
            "value": str(value),
            "tags": tag_list,
            "created_at": created or _now(),
            "updated_at": _now(),
        }
        _save(data)
        total = len(items)

    action = "已更新" if old else "已记住"
    return f"{action}「{key}」（当前共 {total} 条记忆，存储于 {_store_path()}）"


@tool
@timer
def recall(key: str) -> str:
    """按 key 取回之前记住的信息。"""
    print(f"🧠  开始回忆: {key}", end="")
    key = _normalize_key(key)
    with _LOCK:
        data = _load()
    item = data["items"].get(key)
    if not item:
        # 没完全命中就给个近似提示，模型可以自己纠正 key
        candidates = [k for k in data["items"] if key and (key in k or k in key)]
        hint = f"\n相近的 key: {', '.join(candidates[:5])}" if candidates else ""
        return f"没有找到 key「{key}」{hint}"
    tags = f"  标签: {', '.join(item.get('tags', []))}" if item.get("tags") else ""
    return (f"{item.get('value', '')}\n"
            f"（key={key}，更新于 {item.get('updated_at', '未知')}{tags}）")


def _collect(keyword: str, limit: int) -> tuple[list[tuple[str, str, list, str]], int]:
    """按关键字收集记忆，返回 (命中的条目, 总条数)。"""
    with _LOCK:
        items = _load()["items"]
    hits = []
    for key, item in items.items():
        value = str(item.get("value", ""))
        tags = item.get("tags", [])
        haystack = f"{key} {value} {' '.join(tags)}".lower()
        if keyword and keyword not in haystack:
            continue
        hits.append((key, value, tags, item.get("updated_at", "")))
    hits.sort(key=lambda x: x[3], reverse=True)
    return hits[:limit], len(items)


@tool
@timer
def search_memory(keyword: str, max_results: int = 20) -> str:
    """在已保存的记忆里按关键字搜索（key、内容、标签都会匹配）。

    参数：
    - keyword：关键字，留空则列出全部
    - max_results：最多返回多少条
    """
    print(f"🧠  开始搜索记忆: {keyword}", end="")
    keyword = str(keyword).strip().lower()
    limit = max(1, min(int(max_results), MAX_LIST_ITEMS))
    hits, total = _collect(keyword, limit)

    if not hits:
        return f"没有匹配「{keyword}」的记忆（共 {total} 条）"
    lines = [f"# 命中 {len(hits)} 条记忆（共 {total} 条）"]
    for key, value, tags, updated in hits:
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        lines.append(f"- {key}{tag_str}（{updated}）: {value[:200]}")
    return "\n".join(lines)


@tool
@timer
def list_memories(max_results: int = 50) -> str:
    """列出所有已保存的记忆（按更新时间倒序）。"""
    print("🧠  开始列出记忆", end="")
    limit = max(1, min(int(max_results), MAX_LIST_ITEMS))
    hits, total = _collect("", limit)
    if not hits:
        return f"目前没有任何记忆（{_store_path()}）"
    lines = [f"# 共 {total} 条记忆（显示 {len(hits)} 条）"]
    for key, value, tags, updated in hits:
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        lines.append(f"- {key}{tag_str}（{updated}）: {value[:200]}")
    return "\n".join(lines)


@tool
@timer
def forget(key: str) -> str:
    """删除一条记忆。"""
    print(f"🧠  开始遗忘: {key}", end="")
    key = _normalize_key(key)
    with _LOCK:
        data = _load()
        if key not in data["items"]:
            return f"没有 key 为「{key}」的记忆，无需删除"
        data["items"].pop(key)
        _save(data)
        total = len(data["items"])
    return f"已删除记忆「{key}」（剩余 {total} 条）"


persistence_tools = [remember, recall, search_memory, list_memories, forget]
