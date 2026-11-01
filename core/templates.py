"""模板读取、保存与渲染。

模板 = 一个 .md 文件：--- 之间是元信息，后面是正文。
正文支持两种语法，且**只处理已知的名字**：
  {{变量名}}          —— 名字在 vars 里才替换，否则原样保留
                        （模板正文里会提到 {{变量}} 这种字面量，不能误伤）
  {{#开关}}...{{/开关}}  —— 开关为真才保留这一段
  {{^开关}}...{{/开关}}  —— 开关为假才保留这一段

不引入 YAML 库：元信息只有「键: 值」和「键: a, b」两种，手写解析足够。
"""

import os
import re
import shutil
import threading

from . import paths

# 用户可编辑的模板放在可写目录（exe 旁边），出厂源在只读目录（exe 内部）
PROMPT_DIR = paths.prompt_dir()
DEFAULT_DIR = paths.default_dir()
FACTORY_DIR = paths.factory_prompt_dir()

_lock = threading.Lock()

_FLAG_RE = re.compile(r"\{\{([#^])(\w+)\}\}(.*?)\{\{/\2\}\}", re.S)


def _read_meta(text: str) -> tuple[dict, str]:
    """拆出 front-matter 与正文。没有 front-matter 就整篇当正文。"""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    head = text[3:end]
    body = text[end + 4:]
    meta = {}
    for line in head.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip()
    return meta, body.lstrip("\n")


def list_templates() -> list:
    out = []
    if not os.path.isdir(PROMPT_DIR):
        return out
    for name in sorted(os.listdir(PROMPT_DIR)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(PROMPT_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                meta, _ = _read_meta(f.read())
        except OSError:
            continue
        tid = meta.get("id") or name[:-3]
        scene = meta.get("scene") or ""
        if name.startswith("_"):
            # 下划线开头的是内部文件（词典），单独归一组，仍然可编辑
            scene = "extra"
        out.append({
            "id": tid,
            "file": name,
            "name": meta.get("name") or tid,
            "scene": scene,
            "mode": meta.get("mode") or "",
            "version": meta.get("version") or "",
            "size": os.path.getsize(path),
            "edited": _is_edited(name),
        })
    return out


def _is_edited(name: str) -> bool:
    src = os.path.join(PROMPT_DIR, name)
    ref = os.path.join(DEFAULT_DIR, name)
    try:
        with open(src, "rb") as a, open(ref, "rb") as b:
            return a.read() != b.read()
    except OSError:
        return False


def _find_file(tid: str) -> str | None:
    if not os.path.isdir(PROMPT_DIR):
        return None
    for name in os.listdir(PROMPT_DIR):
        if not name.endswith(".md"):
            continue
        if name[:-3] == tid:
            return os.path.join(PROMPT_DIR, name)
        try:
            with open(os.path.join(PROMPT_DIR, name), "r", encoding="utf-8") as f:
                meta, _ = _read_meta(f.read())
            if meta.get("id") == tid:
                return os.path.join(PROMPT_DIR, name)
        except OSError:
            continue
    return None


def load_template(tid: str) -> tuple[dict, str] | None:
    path = _find_file(tid)
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            meta, body = _read_meta(f.read())
    except OSError:
        return None
    return meta, body


def save_template(tid: str, content: str) -> bool:
    path = _find_file(tid)
    if not path:
        return False
    with _lock:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        os.replace(tmp, path)
    return True


def reset_template(tid: str) -> bool:
    path = _find_file(tid)
    if not path:
        return False
    content = factory_body(tid)
    if content is None:
        return False
    with _lock:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        os.replace(tmp, path)
    return True


def ensure_defaults() -> None:
    """准备「恢复默认」用的出厂副本。

    出厂副本是纯缓存，不属于用户数据，所以放在数据目录而不是 prompts/ 里，
    免得你打开 prompts 文件夹看到一堆重复文件。

    exe 模式下每次启动都从 exe 内部覆盖刷新——这样升级 exe 后
    「恢复默认」拿到的是新版，而不是第一次运行时的旧快照。
    源码模式下源和目标其实是同一份文件，退化成「首次快照」。
    """
    os.makedirs(DEFAULT_DIR, exist_ok=True)
    src_dir = FACTORY_DIR if os.path.isdir(FACTORY_DIR) else PROMPT_DIR
    if not os.path.isdir(src_dir):
        return
    for name in os.listdir(src_dir):
        if not name.endswith(".md"):
            continue
        src = os.path.join(src_dir, name)
        dst = os.path.join(DEFAULT_DIR, name)
        if os.path.abspath(src) == os.path.abspath(dst):
            continue
        if paths.FROZEN or not os.path.exists(dst):
            try:
                shutil.copyfile(src, dst)
            except OSError:
                pass


def factory_body(tid: str) -> str | None:
    """读出厂正文。

    顺序很重要：先读 _defaults 快照。源码模式下 FACTORY_DIR 就是 prompts/ 本身，
    用户改过的内容会被当成「出厂版本」，导致「恢复默认」什么也没恢复。
    """
    for d in (DEFAULT_DIR, FACTORY_DIR):
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if not name.endswith(".md"):
                continue
            if name[:-3] == tid:
                try:
                    with open(os.path.join(d, name), "r", encoding="utf-8") as f:
                        return f.read()
                except OSError:
                    continue
    return None


def render(body: str, variables: dict, flags: dict | None = None) -> str:
    """渲染模板。未知的 {{xxx}} 原样保留——模板正文里常有字面量占位符。"""
    flags = flags or {}

    def _flag(m):
        sigil, name, inner = m.group(1), m.group(2), m.group(3)
        if name not in flags:
            return m.group(0)
        on = bool(flags[name])
        return inner if (on if sigil == "#" else not on) else ""

    text = _FLAG_RE.sub(_flag, body)
    # 允许嵌套：反复两遍即可覆盖常见深度
    text = _FLAG_RE.sub(_flag, text)

    def _var(m):
        name = m.group(1)
        if name in variables:
            return str(variables[name])
        return m.group(0)

    return re.sub(r"\{\{(\w+)\}\}", _var, text)


def render_template(tid: str, variables: dict, flags: dict | None = None) -> str | None:
    got = load_template(tid)
    if not got:
        return None
    _, body = got
    return render(body, variables, flags)


def glossary() -> str:
    """大白话词典的正文（去掉元信息），注入到编程类模板末尾。"""
    path = os.path.join(PROMPT_DIR, "_glossary.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            _, body = _read_meta(f.read())
        return body.strip()
    except OSError:
        return ""
