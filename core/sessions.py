"""会话（任务）管理。

一个任务 = 一次完整对话：你说了什么、它问了什么、最后给的提示词。
左侧每个场景下面挂若干任务，可以新建、重命名、删除。

存「文档\轻提\tasks.json」（见 paths.history_dir），刻意不放在安装目录、
也不放在 %LOCALAPPDATA%\轻提：重装或升级版本时历史不会跟着被清掉。

老版本把记录写在 %LOCALAPPDATA%\轻提\tasks.json，首次启动会自动迁移过来，
原文件改名成 tasks.json.migrated 留个底。
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
    return os.path.join(paths.history_dir(), FILE_NAME)


def legacy_path() -> str:
    """上一版存记录的地方。"""
    return os.path.join(paths.data_dir(), FILE_NAME)


def migrate_legacy() -> bool:
    """把老位置的历史搬到新位置，返回是否发生了迁移。

    只在「新位置还没有文件、老位置有文件」时动手，绝不覆盖已有记录。
    """
    try:
        new, old = _path(), legacy_path()
        if os.path.abspath(new) == os.path.abspath(old):
            return False
        if os.path.isfile(new) or not os.path.isfile(old):
            return False
        with open(old, "rb") as f:
            blob = f.read()
        tmp = new + ".tmp"
        with open(tmp, "wb") as f:
            f.write(blob)
        os.replace(tmp, new)
        try:
            os.replace(old, old + ".migrated")
        except OSError:
            pass
        return True
    except OSError:
        return False


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
