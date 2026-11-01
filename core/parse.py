"""回复解析：把模型的原始输出拆成「提问」「提示词」「纯文本」三种。

模型一定会写歪——多写一句开场白、JSON 尾逗号、中文引号。
这里做的是逐级降级，任何一步失败都不能白屏：
  剥围栏 → 去尾逗号 → 中文引号 → JSON 解析 → 正则抠片段 → 退化成纯文本
"""

import json
import re

ASK_RE = re.compile(r"<<<\s*ASK\s*>>>(.*?)<<<\s*ASK_END\s*>>>", re.S)
# 兼容模板里可能写成 <<<END>>> 的老写法，用户自己改文件时不会踩坑
PROMPT_RE = re.compile(r"<<<\s*PROMPT\s*>>>(.*?)<<<\s*(?:PROMPT_END|END)\s*>>>", re.S)

_FLUFF = [
    "以下是优化后的提示词：", "以下是优化后的提示词", "优化后的提示词如下：",
    "以下是为您优化后的提示词：", "好的，以下是", "下面是优化后的提示词：",
]


def _strip_fence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*\n?", "", s)
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()


_CURLY_AS_DELIM_LEFT = re.compile(r"(?<=[\{\[,:\s])[\u201c\u201d\u2018\u2019]")
_CURLY_AS_DELIM_RIGHT = re.compile(r"[\u201c\u201d](?=\s*[:,}\]])")


def _fix_quotes(s: str) -> str:
    """只替换「当 JSON 分隔符用」的中文引号。

    以前是全文无脑替换，遇到正文里的引号就出事：
        "q": "你说的“套壳”，是想把什么包进 App 里？"
    会被改成
        "q": "你说的"套壳"，是想把什么包进 App 里？"
    字符串被提前截断，整个 JSON 废掉，最后降级成「模型没按格式回答」，
    用户只能看着一堆文字干瞪眼。真正的分隔符都在 { [ , : 后面、
    : , } ] 前面，按位置判断就能只改该改的。
    """
    s = _CURLY_AS_DELIM_LEFT.sub('"', s)
    s = _CURLY_AS_DELIM_RIGHT.sub('"', s)
    return s


def _fix_json(s: str) -> str:
    s = _strip_fence(s)
    s = _fix_quotes(s)
    s = s.replace("\u2018", "'").replace("\u2019", "'")
    # 去掉 } 或 ] 前面多余的逗号
    s = re.sub(r",(\s*[}\]])", r"\1", s)
    return s.strip()


def _coerce_questions(data) -> list:
    """把模型可能写歪的结构归一成 [{q,type,opts:[{label,desc,rec}]}]。"""
    if isinstance(data, dict):
        data = data.get("questions") or data.get("ask") or data.get("items") or []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        q = (item.get("q") or item.get("question") or item.get("text") or "").strip()
        if not q:
            continue
        raw_opts = item.get("opts") or item.get("options") or item.get("follow_up") or []
        opts = []
        for o in raw_opts:
            if isinstance(o, str):
                opts.append({"label": o.strip(), "desc": "", "rec": False})
            elif isinstance(o, dict):
                label = (o.get("label") or o.get("text") or o.get("title") or "").strip()
                if not label:
                    continue
                opts.append({
                    "label": label,
                    "desc": (o.get("desc") or o.get("description") or o.get("hint") or "").strip(),
                    "rec": bool(o.get("rec") or o.get("recommended") or False),
                })
        if len(opts) < 2:
            continue
        # 只允许一个推荐
        seen = False
        for o in opts:
            if o["rec"] and seen:
                o["rec"] = False
            elif o["rec"]:
                seen = True
        typ = item.get("type") or "single"
        typ = "multi" if str(typ).lower().startswith("multi") else "single"
        out.append({"q": q, "type": typ, "opts": opts[:4]})
        if len(out) >= 3:
            break
    return out


def extract_ask(raw: str) -> list:
    raw = raw or ""
    matches = list(ASK_RE.finditer(raw))
    if matches:
        # 一条回复里可能出现多个 ASK 块（模型在说明里又抄一遍示例），
        # 取能解析出题目最多的那个，而不是盲目取第一个。
        best = []
        for m in matches:
            got = _load_questions(m.group(1))
            if len(got) > len(best):
                best = got
        if best:
            return best
        block = matches[0].group(1)
    else:
        # 模型偶尔会省掉 <<<ASK>>> 标记，直接甩一个 JSON 数组出来。
        # 整段就是一个 [ 或 { 开头的东西时，也当成提问试一次。
        block = _strip_fence(raw).strip()
        if block[:1] not in ("[", "{"):
            return []
    return _load_questions(block)


def _load_questions(block: str) -> list:
    # 先按原样解析：模型通常写的就是合法 JSON，不该一上来就「修」它
    for attempt in (block.strip(), _fix_json(block),
                    _fix_json(block).replace("'", '"')):
        try:
            got = _coerce_questions(json.loads(attempt))
        except ValueError:
            continue
        if got:
            return got

    # 最后兜底：把一段里所有 {...} 片段挨个试
    found = []
    for seg in re.findall(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", block, re.S):
        for attempt in (seg, _fix_json(seg)):
            try:
                found.extend(_coerce_questions(json.loads(attempt)))
                break
            except ValueError:
                continue
    return found[:3]


def extract_prompt(raw: str) -> str | None:
    """取最长的那个提示词块。

    模型很爱在正文说明里再写一对空的 <<<PROMPT>>>/<<<PROMPT_END>>>
    （比如「### ② 优化后的提示词」下面画个空壳），以前取第一个匹配，
    一旦空壳排在前面，整个回复就被判成「没按格式」，用户只看到一堆原文。
    按长度取最长的那个才是真正的正文。
    """
    best = ""
    for m in PROMPT_RE.finditer(raw or ""):
        text = _strip_fence(m.group(1)).strip()
        if len(text) > len(best):
            best = text
    return best or None


def strip_fluff(text: str) -> str:
    t = (text or "").strip()
    for f in _FLUFF:
        if t.startswith(f):
            t = t[len(f):].lstrip(" \n:：")
            break
    return t


def parse_reply(raw: str, prefer: str | None = None) -> dict:
    """prefer="prompt" 时，只要抠出了提示词就用它。

    轮次用尽后模型仍可能顺手带一段提问，这时不能把它当成「还要再问」，
    否则用户永远等不到结果。
    """
    raw = raw or ""
    ask = extract_ask(raw)
    prompt = extract_prompt(raw)
    if prompt and (prefer == "prompt" or not ask):
        kind = "prompt"
    elif ask:
        kind = "ask"
    else:
        kind = "text"
    return {
        "kind": kind,
        "ask": ask,
        "prompt": prompt,
        "raw": raw,
        "clean": strip_fluff(raw),
    }
