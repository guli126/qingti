"""会话（任务）管理。

一个任务 = 一次完整对话：你说了什么、它问了什么、最后给的提示词。
左侧每个场景下面挂若干任务，可以新建、重命名、删除。

存 data_dir/tasks.json。timeline 是为「点回旧任务能原样恢复界面」准备的，
只存必要的结构，不存中间态。
"""

import json
import os
import threading
import time
import uuid

from . import paths

FILE_NAME = "tasks.json"
MAX_TASKS = 300
TITLE_MAX = 24

_lock = threading.Lock()
DEFAULT = {"tasks": [], "collapsed": {}, "active": ""}


def _path() -> str:
    return os.path.join(paths.data_dir(), FILE_NAME)


def load() -> dict:
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {"tasks": [], "collapsed": {}, "active": ""}
    if not isinstance(data, dict):
        return {"tasks": [], "collapsed": {}, "active": ""}
    data.setdefault("tasks", [])
    data.setdefault("collapsed", {})
    data.setdefault("active", "")
    if not isinstance(data["tasks"], list):
        data["tasks"] = []
    return data


def save(data: dict) -> None:
    with _lock:
        tmp = _path() + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, _path())
        except OSError:
            pass


def get(tid: str, data: dict | None = None) -> dict | None:
    data = data if data is not None else load()
    for t in data["tasks"]:
        if t.get("id") == tid:
            return t
    return None


def by_scene(scene: str, data: dict | None = None) -> list:
    data = data if data is not None else load()
    items = [t for t in data["tasks"] if t.get("scene") == scene]
    items.sort(key=lambda t: -(t.get("updated") or 0))
    return items


def create(scene: str, title: str = "新任务", mode: str = "task",
           prune: bool = True) -> dict:
    data = load()
    if prune:
        # 同一场景里还没说过话的草稿只留一个，避免狂点「+」堆一串「新对话」
        data["tasks"] = [t for t in data["tasks"]
                         if t.get("timeline") or t.get("scene") != scene]
    now = int(time.time())
    task = {
        "id": uuid.uuid4().hex[:12],
        "scene": scene,
        "mode": mode,
        "title": (title or "新任务")[:TITLE_MAX],
        "created": now,
        "updated": now,
        "timeline": [],
    }
    data["tasks"].insert(0, task)
    # 只保留最近的若干条，避免文件无限长大
    if len(data["tasks"]) > MAX_TASKS:
        data["tasks"] = data["tasks"][:MAX_TASKS]
    data["active"] = task["id"]
    save(data)
    return task


def rename(tid: str, title: str) -> None:
    data = load()
    t = get(tid, data)
    if not t:
        return
    t["title"] = (title or "").strip()[:TITLE_MAX] or "未命名"
    t["updated"] = int(time.time())
    save(data)


def set_mode(tid: str, mode: str) -> None:
    """记住这个任务上次用的模式，切回来时还原。"""
    data = load()
    t = get(tid, data)
    if not t:
        return
    t["mode"] = mode or t.get("mode") or "task"
    save(data)


def remove(tid: str) -> None:
    data = load()
    data["tasks"] = [t for t in data["tasks"] if t.get("id") != tid]
    if data.get("active") == tid:
        data["active"] = data["tasks"][0]["id"] if data["tasks"] else ""
    save(data)


def append(tid: str, item: dict) -> None:
    """往当前任务的 timeline 末尾加一条，并刷新时间与标题。"""
    data = load()
    t = get(tid, data)
    if not t:
        return
    t.setdefault("timeline", []).append(item)
    t["updated"] = int(time.time())
    # 第一条用户消息顺手当标题，省得让用户自己命名
    if item.get("role") == "user" and t.get("title") in ("", "新任务", "新对话"):
        text = (item.get("text") or "").strip().replace("\n", " ")
        if text:
            t["title"] = text[:TITLE_MAX]
    save(data)


def set_active(tid: str) -> None:
    data = load()
    data["active"] = tid or ""
    save(data)


def set_collapsed(scene: str, value: bool) -> None:
    data = load()
    data.setdefault("collapsed", {})[scene] = bool(value)
    save(data)


def collapsed(scene: str, data: dict | None = None) -> bool:
    data = data if data is not None else load()
    return bool((data.get("collapsed") or {}).get(scene))
