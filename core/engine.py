"""对话编排：组装提示词 → 发请求 → 解析回复 → 落历史。

这一层跟界面完全无关。界面只管「把结果画出来」，改 UI 不会碰到业务逻辑，
也方便脱离窗口单独测。
"""

from . import llm, parse, store, templates

GLOSSARY_HEAD = ("\n\n---\n\n"
                 "# 附：大白话词典（把用户的口语翻译成技术表达时参考）\n\n")

# 场景 → (中文名, 模板前缀, 模式列表)
SCENES = {
    "coding": {
        "name": "编程",
        "modes": [
            ("task", "任务提示词", "把一句话需求变成可执行的任务描述"),
            ("system", "系统提示词", "改写「你是一个××助手」这类人设"),
            ("iterate", "迭代改进", "已有版本，只改一两个地方"),
        ],
        "glossary": True,
        "placeholder": "说说你想做什么，比如：帮我做个统计每月支出的东西",
    },
    "work": {
        "name": "办公",
        "modes": [
            ("task", "任务提示词", "周报、方案、邮件、纪要、数据分析"),
            ("system", "系统提示词", "改写写作助手、分析师这类角色设定"),
            ("iterate", "迭代改进", "已有材料，只想调整语气或结构"),
        ],
        "glossary": False,
        "placeholder": "说说你要写什么，比如：给领导写个本周项目进度汇报",
    },
    "image": {
        "name": "图像",
        "modes": [
            ("t2i.general", "文生图 · 通用", "适合 Gemini / GPT 这类多模态模型"),
            ("t2i.chinese", "文生图 · 中文美学", "适合即梦、通义万相、可图"),
            ("t2i.json", "文生图 · JSON", "要结构化、方便复用的场景"),
            ("i2i.general", "图生图 · 通用", "改风格、换背景、调光线"),
            ("i2i.text", "图生图 · 换字", "设计稿里的文字替换"),
            ("iterate", "图像迭代", "在上一版基础上微调"),
        ],
        "glossary": False,
        "placeholder": "描述你想要的画面，比如：一只橘猫蹲在窗台上，午后斜光",
    },
}

DETAILS = ["极简", "标准", "详尽"]
MAX_ROUNDS = 3


def template_id(scene: str, mode: str) -> str:
    """场景 + 模式 → 模板文件名（不含 .md）。"""
    if scene == "image":
        if mode == "t2i.general":
            return "image.text2image.general"
        if mode == "t2i.chinese":
            return "image.text2image.chinese"
        if mode == "t2i.json":
            return "image.text2image.json"
        if mode == "i2i.general":
            return "image.image2image.general"
        if mode == "i2i.text":
            return "image.image2image.text-edit"
        return "image.iterate"
    if mode == "system":
        return scene + ".system"
    if mode == "iterate":
        return scene + ".iterate"
    return scene + ".task"


def mode_name(scene: str, mode: str) -> str:
    for key, label, _ in SCENES.get(scene, {}).get("modes", []):
        if key == mode:
            return label
    return mode


def build_system(tid: str, text: str, *, detail: str = "标准", round_: int = 1,
                 max_rounds: int = MAX_ROUNDS, previous: str = "", model: str = "",
                 scene: str = "", glossary: bool = True,
                 output_format: bool = False, explain_changes: bool = True) -> str:
    """按模板渲染出给模型的 system 提示词。"""
    variables = {
        "input": text,
        "detail": detail,
        "round": round_,
        "maxRounds": max_rounds,
        "previous": previous,
        "model": model,
    }
    flags = {"outputFormat": output_format, "explainChanges": explain_changes}
    system = templates.render_template(tid, variables, flags)
    if system is None:
        raise ValueError("模板不存在：%s（检查 prompts 目录）" % tid)

    # 词典只注入编程场景：这是「新手看不懂术语」的主要解法
    if scene == "coding" and glossary:
        g = templates.glossary()
        if g:
            system += GLOSSARY_HEAD + g
    return system


NUDGE = (
    "你上一条回复没有按约定的格式输出。请严格按系统提示词的要求重新回答：\n"
    "- 如果还需要向用户确认信息，输出 <<<ASK>>> 开头、<<<ASK_END>>> 结尾的 JSON 数组\n"
    "- 如果已经可以给结果，输出 <<<PROMPT>>> 开头、<<<PROMPT_END>>> 结尾的提示词\n"
    "只输出这些内容，不要加任何解释、前言或代码围栏。"
)

# 轮次已经用尽却还在提问时用这条。措辞要硬：模型此刻最常见的坏习惯
# 就是「再确认一下」，用户等了三轮还在被问，会直接放弃。
FORCE_RESULT = (
    "提问次数已经用完了。现在不要再问任何问题，立刻按系统提示词里"
    "「出结果」的格式输出最终提示词：\n"
    "只输出 <<<PROMPT>>> 开头、<<<PROMPT_END>>> 结尾的内容，"
    "没确定的信息写进你给出的假设里。不要提问，不要解释。"
)


def send(conn: dict, system: str, messages: list, round_: int = 1,
         max_rounds: int = MAX_ROUNDS, on_delta=None, retry: bool = True):
    """发一次请求，返回 (解析结果, 原始结果)。

    模型偶尔会把格式忘光，回一大段大白话。这种回复既解析不出选项也解析不出
    提示词，界面上就只剩「模型没按格式回答，下面是原文」——用户只能自己打字。
    所以第一次没解析出东西时，自动催它按格式重发一次（不流式，避免界面上的
    字重复一遍）。

    最后一轮还在提问同样要拦：轮次用尽却收不到结果，等于整轮白等。
    """
    msgs = [{"role": m.get("role") or "user", "content": m.get("content") or ""}
            for m in (messages or []) if m.get("content")]
    if not msgs:
        msgs = [{"role": "user", "content": "开始吧。"}]

    last_round = round_ >= max_rounds

    # 出结果那一轮给足 max_tokens，避免提示词被截在半句
    budget = 8192 if round_ < max_rounds else 12000
    result = llm.chat(conn, system, msgs, max_tokens=budget, on_delta=on_delta)
    parsed = parse.parse_reply(result["text"], prefer="prompt" if last_round else None)

    if not retry:
        return parsed, result

    needs_fix = parsed.get("kind") == "text" or (last_round and parsed.get("kind") == "ask")
    if not needs_fix:
        return parsed, result

    nudge = FORCE_RESULT if last_round else NUDGE
    try:
        fix = llm.chat(
            conn, system,
            msgs + [{"role": "assistant", "content": result["text"]},
                    {"role": "user", "content": nudge}],
            max_tokens=budget, on_delta=None)
        again = parse.parse_reply(fix["text"], prefer="prompt")
    except llm.ChatError:
        return parsed, result
    if again.get("kind") == "prompt":
        return again, fix
    if again.get("kind") == "ask" and parsed.get("kind") == "text":
        return again, fix
    return parsed, result


def remember(scene: str, mode: str, tid: str, text: str, parsed: dict) -> None:
    """落一条历史。失败不影响主流程。"""
    try:
        store.append_history({
            "scene": scene,
            "mode": mode,
            "template": tid,
            "input": (text or "")[:2000],
            "kind": parsed.get("kind") or "",
            "prompt": (parsed.get("prompt") or "")[:4000],
        })
    except OSError:
        pass


def active_connection(cfg: dict | None = None) -> dict | None:
    """取当前生效的连接；没有就返回 None（界面据此显示引导，不弹窗）。"""
    cfg = cfg if cfg is not None else store.load_config()
    conn = store.find_connection(cfg, None)
    if not conn:
        return None
    return store.runtime_connection(conn)
