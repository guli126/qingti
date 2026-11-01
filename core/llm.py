"""AI 请求层：三个协议一个入口。

request/解析路径里没有任何 `if protocol == ...` 的分支——差异全被收进
ChatProtocol 的 8 个函数字段。新增协议只需要再组合一个对象，不用改读流逻辑。

搬自 AI小说/墨序 的四条经验：
  1. 429/5xx 重试一次；400/401/403/404 不重试，直接给中文错误
  2. 流式已经收到正文后中断，绝不重发（否则正文重复）
  3. 400 且 body 提到 max_tokens / stream_options，摘掉该字段重试
  4. 思考内容两层过滤：结构化字段直接丢，文本层标签跨分片剥离
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import providers

RETRYABLE = {408, 409, 425, 429}


class ChatError(Exception):
    pass


# ---------------------------------------------------------------- 思考过滤

_TAG_PAIRS = [
    ("<thinking>", "</thinking>"),
    ("<thought>", "</thought>"),
    ("<reasoning>", "</reasoning>"),
    ("\u25c1think\u25b7", "\u25c1/think\u25b7"),
]
_OPENERS = [p[0] for p in _TAG_PAIRS]


class ThinkingStripper:
    """跨分片剔除中转站夹带在正文里的思考标签。"""

    def __init__(self):
        self.buf = ""
        self.inside = None  # 当前处于哪个标签内部

    def feed(self, delta: str) -> str:
        self.buf += delta
        out = []
        while True:
            if self.inside is None:
                hit = None
                for op, cl in _TAG_PAIRS:
                    i = self.buf.find(op)
                    if i != -1 and (hit is None or i < hit[0]):
                        hit = (i, op, cl)
                if hit is None:
                    out.append(self._flush_safe())
                    break
                i, op, cl = hit
                out.append(self.buf[:i])
                self.buf = self.buf[i + len(op):]
                self.inside = cl
            else:
                j = self.buf.find(self.inside)
                if j == -1:
                    if len(self.buf) > 4096:  # 防无限增长
                        self.buf = self.buf[-512:]
                    break
                self.buf = self.buf[j + len(self.inside):]
                self.inside = None
        return "".join(out)

    def _flush_safe(self) -> str:
        """末尾可能是半个标签，先扣住不发。"""
        keep = 0
        for op in _OPENERS:
            for n in range(1, len(op)):
                if self.buf.endswith(op[:n]):
                    keep = max(keep, n)
        if keep:
            safe = self.buf[:-keep]
            self.buf = self.buf[-keep:]
        else:
            safe = self.buf
            self.buf = ""
        return safe

    def finish(self) -> str:
        rest, self.buf = self.buf, ""
        self.inside = None
        return rest


# ---------------------------------------------------------------- 协议

class ChatProtocol:
    def __init__(self, name, build, delta_text, is_reasoning, parse, finish_reason, stream_usage):
        self.name = name
        self.build = build
        self.delta_text = delta_text
        self.is_reasoning = is_reasoning
        self.parse = parse
        self.finish_reason = finish_reason
        self.stream_usage = stream_usage


# 中转站大多挂在 Cloudflare 后面。urllib 默认的 User-Agent 是
# "Python-urllib/3.x"，Cloudflare 会当成爬虫直接回 403（body 是
# "error code: 1010"），看起来就像「密钥不对」——其实一次都没发出去。
# 报个浏览器身份就能正常通行，这也是唯一需要「伪装」的地方。
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/131.0.0.0 Safari/537.36")

_BASE_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": USER_AGENT,
}


def _headers(auth_key: str, auth_style: str) -> dict:
    h = dict(_BASE_HEADERS)
    if auth_style == "x-api-key":
        h["x-api-key"] = auth_key
    else:
        h["Authorization"] = "Bearer " + auth_key
    return h


# ---- OpenAI 兼容

def _openai_build(base, model, key, system, messages, max_tokens, stream, disable_thinking, auth_style):
    url = base.rstrip("/") + "/chat/completions"
    headers = _headers(key, auth_style)
    if "openrouter.ai" in url:
        headers["HTTP-Referer"] = "http://localhost"
        headers["X-Title"] = "\u8f7b\u63d0"
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    payload = {"model": model, "messages": msgs, "temperature": 0.7,
               "max_tokens": max_tokens}
    if stream:
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
    if disable_thinking:
        payload.update(_thinking_off(base, model))
    return url, headers, payload


def _thinking_off(base: str, model: str) -> dict:
    b = (base or "").lower()
    if "dashscope" in b or "siliconflow" in b or "qwen" in (model or "").lower():
        return {"enable_thinking": False}
    if "bigmodel" in b or "zhipu" in b:
        return {"thinking": {"type": "disabled"}}
    if "moonshot" in b:
        return {"thinking": {"type": "disabled"}}
    if "deepseek" in b:
        return {"thinking": {"type": "disabled"}}
    return {}


def _openai_delta_text(obj: dict) -> str:
    try:
        return obj["choices"][0]["delta"].get("content") or ""
    except (KeyError, IndexError, TypeError):
        return ""


def _openai_is_reasoning(obj: dict) -> bool:
    try:
        d = obj["choices"][0].get("delta") or {}
        return bool(d.get("reasoning_content"))
    except (KeyError, IndexError, TypeError):
        return False


def _openai_parse(obj: dict) -> str:
    try:
        return obj["choices"][0]["message"].get("content") or ""
    except (KeyError, IndexError, TypeError):
        return ""


def _openai_finish(obj: dict) -> str:
    try:
        return obj["choices"][0].get("finish_reason") or ""
    except (KeyError, IndexError, TypeError):
        return ""


# ---- Anthropic

def _anthropic_build(base, model, key, system, messages, max_tokens, stream, disable_thinking, auth_style):
    url = base.rstrip("/") + "/messages"
    headers = dict(_BASE_HEADERS)
    headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    msgs = [{"role": m["role"], "content": m["content"]} for m in messages
            if m.get("role") in ("user", "assistant") and m.get("content")]
    payload = {"model": model, "max_tokens": max_tokens or 8192,
               "temperature": 0.7, "messages": msgs}
    if system:
        payload["system"] = system
    if stream:
        payload["stream"] = True
    if disable_thinking:
        payload["thinking"] = {"type": "disabled"}
    return url, headers, payload


def _anthropic_delta_text(obj: dict) -> str:
    if obj.get("type") == "content_block_delta":
        d = obj.get("delta") or {}
        if d.get("type") == "text_delta":
            return d.get("text") or ""
    return ""


def _anthropic_is_reasoning(obj: dict) -> bool:
    return obj.get("type") == "content_block_delta" and \
        (obj.get("delta") or {}).get("type") in ("thinking_delta", "signature_delta")


def _anthropic_parse(obj: dict) -> str:
    parts = []
    for blk in obj.get("content") or []:
        if isinstance(blk, dict) and blk.get("type") == "text":
            parts.append(blk.get("text") or "")
    return "".join(parts)


def _anthropic_finish(obj: dict) -> str:
    if obj.get("type") == "message_delta":
        return (obj.get("delta") or {}).get("stop_reason") or ""
    return obj.get("stop_reason") or ""


# ---- Gemini 原生

def _gemini_build(base, model, key, system, messages, max_tokens, stream, disable_thinking, auth_style):
    op = "streamGenerateContent" if stream else "generateContent"
    url = "%s/models/%s:%s?key=%s" % (base.rstrip("/"), model, op, key)
    if stream:
        url += "&alt=sse"
    headers = dict(_BASE_HEADERS)
    contents = []
    for m in messages:
        if not m.get("content"):
            continue
        role = "model" if m.get("role") == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})
    gen = {"temperature": 0.7}
    if max_tokens:
        gen["maxOutputTokens"] = max_tokens
    if disable_thinking:
        gen["thinkingConfig"] = {"thinkingBudget": 0}
    payload = {"contents": contents, "generationConfig": gen}
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    return url, headers, payload


def _gemini_delta_text(obj: dict) -> str:
    try:
        parts = obj["candidates"][0]["content"]["parts"]
        return "".join(p.get("text") or "" for p in parts if not p.get("thought"))
    except (KeyError, IndexError, TypeError):
        return ""


def _gemini_is_reasoning(obj: dict) -> bool:
    try:
        return any(p.get("thought") for p in obj["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError, TypeError):
        return False


def _gemini_parse(obj: dict) -> str:
    try:
        parts = obj["candidates"][0]["content"]["parts"]
        return "".join(p.get("text") or "" for p in parts if not p.get("thought"))
    except (KeyError, IndexError, TypeError):
        return ""


def _gemini_finish(obj: dict) -> str:
    try:
        return obj["candidates"][0].get("finishReason") or ""
    except (KeyError, IndexError, TypeError):
        return ""


OPENAI = ChatProtocol("openai", _openai_build, _openai_delta_text,
                      _openai_is_reasoning, _openai_parse, _openai_finish, True)
ANTHROPIC = ChatProtocol("anthropic", _anthropic_build, _anthropic_delta_text,
                         _anthropic_is_reasoning, _anthropic_parse, _anthropic_finish, False)
GEMINI = ChatProtocol("gemini", _gemini_build, _gemini_delta_text,
                      _gemini_is_reasoning, _gemini_parse, _gemini_finish, False)

_PROTOCOLS = {"openai": OPENAI, "anthropic": ANTHROPIC, "gemini": GEMINI,
              "gemini_openai": OPENAI}


def pick_protocol(conn: dict) -> ChatProtocol:
    proto = (conn.get("protocol") or "openai").lower()
    return _PROTOCOLS.get(proto, OPENAI)


def normalize_base(conn: dict) -> str:
    """补全 Base URL，并处理 Gemini 的 OpenAI 兼容口。

    用户填 https://generativelanguage.googleapis.com/v1beta 且选 openai 协议时，
    真实地址是 .../v1beta/openai；这层不需要用户理解。
    """
    base = (conn.get("base_url") or "").rstrip("/")
    proto = (conn.get("protocol") or "openai").lower()
    if not base:
        return base
    if "generativelanguage.googleapis.com" in base and proto == "openai":
        if not base.endswith("/openai"):
            base += "/openai"
        return base
    if proto == "openai" and not re.search(r"/v\d+(/|$)", base) \
            and not base.endswith("/compatible-mode/v1"):
        base += "/v1"
    return base


# ---------------------------------------------------------------- 请求

def _read_error(e) -> str:
    try:
        body = e.read().decode("utf-8", "replace")
    except Exception:
        return str(e)
    try:
        obj = json.loads(body)
        msg = (obj.get("error") or {}).get("message") if isinstance(obj.get("error"), dict) else None
        msg = msg or obj.get("message") or obj.get("error") or body
        if isinstance(msg, dict):
            msg = msg.get("message") or json.dumps(msg, ensure_ascii=False)
        return str(msg)[:400]
    except ValueError:
        return body[:400]


def _friendly(code: int, msg: str) -> str:
    low = (msg or "").lower()
    # Cloudflare 的「机器人拦截」，跟密钥无关，报「认证失败」会把人带偏
    if "1010" in low or "just a moment" in low or "attention required" in low:
        return ("被中转站前面的 Cloudflare 防火墙挡了（不是密钥问题）。"
                "换一个中转站，或者让站主放行 API 请求")
    if code in (401, 403):
        return "认证失败：请检查 API Key 是否正确、是否过期（%s）" % msg
    if code == 404:
        return "接口不存在：请检查 Base URL 与协议是否匹配（%s）" % msg
    if code == 429:
        return "请求太频繁或额度用尽，稍后再试（%s）" % msg
    if code >= 500:
        return "服务端错误（%d），稍后再试（%s）" % (code, msg)
    return "请求失败（%d）：%s" % (code, msg)


def _clone(req):
    """复制一份请求，用于换连接方式重试（原请求的 body 已被读过一次）。"""
    return urllib.request.Request(
        req.full_url, data=req.data, headers=dict(req.headers),
        method=req.get_method())


def _has_proxy() -> bool:
    try:
        return bool(urllib.request.getproxies())
    except Exception:
        return False


def _open(req, timeout):
    """本地地址必须绕开系统代理，否则开了 VPN 之后连不上自己。

    其余地址沿用系统代理——国内用户开 VPN 就是为了走出去。
    但代理也可能是「关了 VPN 却没清掉系统代理」留下的死配置，
    这种情况直连往往能通，所以失败后再直连试一次。
    """
    url = req if isinstance(req, str) else req.full_url
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    local = host in ("127.0.0.1", "localhost", "::1")
    if local:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    else:
        opener = urllib.request.build_opener()

    try:
        return opener.open(req, timeout=timeout)
    except urllib.error.URLError:
        if local or not _has_proxy():
            raise
        # 走代理不通，直连再试一次
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({})).open(_clone(req), timeout=timeout)


def chat(conn: dict, system: str, messages: list, max_tokens: int = 4096,
         on_delta=None, timeout: int | None = None) -> dict:
    """发一次请求。返回 {text, finish_reason, truncated, usage}。"""
    proto = pick_protocol(conn)
    base = normalize_base(conn)
    key = conn.get("api_key") or ""
    model = conn.get("model") or ""
    if not model:
        raise ChatError("没有填写模型名")
    if not key:
        raise ChatError("没有填写 API Key")
    if not base:
        raise ChatError("没有填写 Base URL")
    stream = bool(conn.get("stream", True))
    disable_thinking = bool(conn.get("disable_thinking", False))
    auth_style = conn.get("auth_style") or "bearer"
    try:
        cfg_timeout = int(conn.get("timeout") or 120)
    except (TypeError, ValueError):
        cfg_timeout = 120
    timeout = timeout or cfg_timeout

    dropped = set()
    attempts = 0
    state = {"text": False}

    def emit(piece: str):
        state["text"] = True
        if on_delta:
            on_delta(piece)

    while True:
        url, headers, payload = proto.build(
            base, model, key, system, messages, max_tokens,
            stream, disable_thinking, auth_style)
        for field in list(dropped):
            payload.pop(field, None)

        try:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            resp = _open(req, timeout)
            return _consume(proto, resp, stream, emit)
        except urllib.error.HTTPError as e:
            code = e.code
            body = _read_error(e)
            low = body.lower()
            if code == 400 and "max_tokens" in low and "max_tokens" not in dropped:
                dropped.add("max_tokens")
                continue
            if code == 400 and "stream_options" in low and "stream_options" not in dropped:
                dropped.add("stream_options")
                continue
            if code == 400 and disable_thinking and any(
                    k in low for k in ("thinking", "enable_thinking", "reasoning")):
                disable_thinking = False
                continue
            if (code in RETRYABLE or code >= 500) and attempts < 1 and not state["text"]:
                attempts += 1
                time.sleep(2)
                continue
            raise ChatError(_friendly(code, body))
        except urllib.error.URLError as e:
            if attempts < 1 and not state["text"]:
                attempts += 1
                time.sleep(2)
                continue
            raise ChatError("连不上服务器：%s（检查网络或 Base URL）" % (e.reason,))
        except TimeoutError:
            raise ChatError("请求超时（%d 秒）。可以在设置里调大超时，或关掉流式" % timeout)


def _consume(proto, resp, stream, emit):
    stripper = ThinkingStripper()
    text_parts = []
    finish = ""
    usage = {}

    if not stream:
        raw = resp.read().decode("utf-8", "replace")
        try:
            obj = json.loads(raw)
        except ValueError:
            raise ChatError("返回内容不是 JSON：%s" % raw[:200])
        body = proto.parse(obj)
        if not body:
            err = obj.get("error") if isinstance(obj, dict) else None
            if err:
                raise ChatError("模型返回错误：%s" % (err if isinstance(err, str) else json.dumps(err, ensure_ascii=False))[:300])
        body = strip_tags(body)
        if body:
            emit(body)
        return {"text": body, "finish_reason": proto.finish_reason(obj),
                "usage": obj.get("usage") or {}, "truncated": False}

    for raw_line in resp:
        line = raw_line.decode("utf-8", "replace").strip()
        if not line or line.startswith(":"):
            continue
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if chunk in ("[DONE]", ""):
            continue
        try:
            obj = json.loads(chunk)
        except ValueError:
            continue
        u = obj.get("usage")
        if isinstance(u, dict) and u:
            usage = u
        fr = proto.finish_reason(obj)
        if fr:
            finish = fr
        if proto.is_reasoning(obj):
            continue
        piece = proto.delta_text(obj)
        if not piece:
            continue
        piece = stripper.feed(piece)
        if not piece:
            continue
        text_parts.append(piece)
        emit(piece)

    tail = stripper.finish()
    if tail:
        text_parts.append(tail)
        emit(tail)

    text = "".join(text_parts)
    truncated = finish in ("length", "max_tokens", "MAX_TOKENS", "max_output_tokens")
    # 只在「没有完整结束标记」时才用半句启发式判断：
    # 有 <<<PROMPT_END>>> 就说明结构完整，末尾没句号只是收尾习惯问题
    if not truncated and text and not _has_marker(text) and _looks_cut(text):
        truncated = True
    return {"text": text, "finish_reason": finish, "usage": usage,
            "truncated": truncated}


def _has_marker(text: str) -> bool:
    return ("<<<PROMPT_END>>>" in text) or ("<<<ASK_END>>>" in text)


def strip_tags(text: str) -> str:
    for op, cl in _TAG_PAIRS:
        text = re.sub(re.escape(op) + r".*?" + re.escape(cl), "", text, flags=re.S)
    return text


def _looks_cut(text: str) -> bool:
    t = text.rstrip()
    if not t:
        return False
    if t.endswith(("<<<PROMPT_END>>>", "<<<ASK_END>>>", "```", ">>>", "}", "]", "\u300d")):
        return False
    return t[-1] not in "。！？.!?）)」』】”\"'`>"


# ---------------------------------------------------------------- 模型列表 / 测试

def list_models(conn: dict) -> list:
    proto = pick_protocol(conn)
    base = normalize_base(conn)
    key = conn.get("api_key") or ""
    headers = _headers(key, conn.get("auth_style") or "bearer")
    if proto is ANTHROPIC:
        headers = dict(_BASE_HEADERS)
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
        url = base + "/models"
    elif proto is GEMINI:
        url = base + "/models?key=" + key
    else:
        url = base + "/models"
    req = urllib.request.Request(url, headers=headers)
    try:
        with _open(req, 30) as resp:
            obj = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raise ChatError(_friendly(e.code, _read_error(e)))
    except urllib.error.URLError as e:
        raise ChatError("连不上服务器：%s" % (e.reason,))
    items = obj.get("data") or obj.get("models") or []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = it.get("id") or it.get("name") or ""
        if name.startswith("models/"):
            name = name[7:]
        if name:
            out.append(name)
    return sorted(set(out))


def endpoint_of(conn: dict) -> str:
    """算出最终会被请求的那个地址，纯粹给界面显示用。

    地址写错的人看到 .../v1/v1/chat/completions 这种一眼就知道错在哪，
    比只给一句「请求失败」有用得多。
    """
    proto = pick_protocol(conn)
    base = normalize_base(conn)
    try:
        url = proto.build(base, conn.get("model") or "", conn.get("api_key") or "",
                          "", [], 16, False, False,
                          conn.get("auth_style") or "bearer")[0]
    except Exception:
        return base
    return url


def test_connection(conn: dict) -> dict:
    t0 = time.time()
    try:
        limit = int(conn.get("timeout") or 30)
    except (TypeError, ValueError):
        limit = 30
    # 探测请求不用等太久，但也别 5 秒就断（中转站偶尔很慢）
    limit = max(8, min(30, limit))
    try:
        # max_tokens 给 32 而不是 16：推理模型光「想」就能把 16 个 token 用光，
        # 正文回空，看着像连上了又像没连上。
        res = chat(conn, "", [{"role": "user", "content": "ping"}],
                   max_tokens=32, on_delta=None, timeout=limit)
        ms = int((time.time() - t0) * 1000)
        return {"ok": True, "ms": ms, "reply": (res.get("text") or "")[:40]}
    except ChatError as e:
        return {"ok": False, "ms": int((time.time() - t0) * 1000), "error": str(e)}
    except Exception as e:
        # 任何没预料到的异常也要变成一句人话，不能让界面卡在「正在连接…」
        return {"ok": False, "ms": int((time.time() - t0) * 1000),
                "error": "%s: %s" % (type(e).__name__, e)}
