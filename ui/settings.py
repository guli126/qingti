"""AI 配置窗口。

分两层：
  列表页  —— 只看已经加了哪些模型，底部是「新增 / 编辑 / 删除 / 设为当前」
  详情页  —— 点新增或编辑才进来，填完保存回列表

以前的写法把新增表单直接铺在最外层，加第二个模型时整个界面就废了。
"""

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from core import llm, providers, store

from . import theme as T
from .widgets import Button, RoundCard, ScrollFrame, Toggle, make_entry, hline


class SettingsWindow(tk.Toplevel):
    def __init__(self, master, on_change=None):
        super().__init__(master)
        self.title("AI 配置 · 轻提")
        self.configure(bg=T.BG)
        self.geometry("740x720")
        self.minsize(660, 600)
        self.transient(master)

        self._on_change = on_change
        self._results = queue.Queue()
        self._generation = 0
        self._async_busy = False
        self._async_poll_job = None
        self._model_win = None
        self._selected = None      # 列表里选中的连接 id
        self._view = tk.Frame(self, bg=T.BG)
        self._view.pack(fill="both", expand=True)

        self._show_list()
        self._center(master)
        self.bind("<Escape>", lambda e: self._escape())
        self._poll_results()

    # ------------------------------------------------------------ 通用

    def _center(self, master):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = master.winfo_rootx() + (master.winfo_width() - w) // 2
        y = master.winfo_rooty() + (master.winfo_height() - h) // 3
        self.geometry("+%d+%d" % (max(0, x), max(0, y)))

    def _escape(self):
        if getattr(self, "_detail", False):
            self._show_list()
        else:
            self.destroy()

    def _clear(self):
        for w in self._view.winfo_children():
            w.destroy()
        self._detail = False

    def _notify(self):
        if self._on_change:
            try:
                self._on_change()
            except Exception:
                pass

    # ------------------------------------------------------------ 列表页

    def _show_list(self):
        self._clear()
        self._selected = None
        cfg = store.load_config()
        conns = cfg.get("connections") or []
        active = cfg.get("active") or ""

        head = tk.Frame(self._view, bg=T.BG)
        head.pack(fill="x", padx=24, pady=(20, 4))
        tk.Label(head, text="AI 模型", bg=T.BG, fg=T.TEXT,
                 font=T.font(15, True)).pack(side="left")
        tk.Label(head, text="共 %d 个" % len(conns), bg=T.BG, fg=T.MUTED,
                 font=T.font(9)).pack(side="left", padx=(10, 0), pady=(4, 0))
        tk.Label(self._view, text="选一个用于生成提示词。可以加多个，随时切换。",
                 bg=T.BG, fg=T.TEXT_SUB, font=T.font(9),
                 anchor="w").pack(fill="x", padx=24, pady=(0, 10))

        self._list_area = ScrollFrame(self._view, bg=T.BG)
        self._list_area.pack(fill="both", expand=True, padx=(24, 16), pady=(0, 8))
        self._list_area.inner.configure(bg=T.BG)

        if not conns:
            empty = tk.Frame(self._list_area.inner, bg=T.BG)
            empty.pack(fill="both", expand=True, pady=60)
            tk.Label(empty, text="还没有任何 AI 配置", bg=T.BG, fg=T.MUTED,
                     font=T.font(11)).pack()
            tk.Label(empty, text="点下面的「+ 新增 AI 配置」开始，\n"
                                "拿不准服务商就选 DeepSeek 或你买的中转站。",
                     bg=T.BG, fg=T.MUTED, font=T.font(9),
                     justify="center").pack(pady=(8, 0))
        else:
            for i, c in enumerate(conns):
                self._row(i, c, c.get("id") == active)

        bar = tk.Frame(self._view, bg=T.BG)
        bar.pack(fill="x", padx=24, pady=(4, 20))

        Button(bar, "+  新增 AI 配置", command=self._new_conn,
               kind="primary", padx=18, pady=8).pack(side="left")

        self._btn_del = Button(bar, "删除", command=self._delete_selected,
                               kind="danger", padx=14, pady=8)
        self._btn_del.pack(side="right")
        self._btn_del.set_enabled(False)

        self._btn_active = Button(bar, "设为当前", command=self._set_active,
                                  kind="ghost", padx=14, pady=8)
        self._btn_active.pack(side="right", padx=(0, 8))
        self._btn_active.set_enabled(False)

        self._btn_edit = Button(bar, "编辑", command=self._edit_selected,
                                kind="ghost", padx=14, pady=8)
        self._btn_edit.pack(side="right", padx=(0, 8))
        self._btn_edit.set_enabled(False)

    def _row(self, index: int, conn: dict, is_active: bool):
        card = RoundCard(self._list_area.inner, bg=T.CARD,
                         border=T.PRIMARY if is_active else T.BORDER,
                         paddingx=16, paddingy=12, parent_bg=T.BG)
        card.pack(fill="x", pady=(0, 8), padx=(0, 8))

        top = tk.Frame(card.body, bg=T.CARD)
        top.pack(fill="x")

        dot = tk.Canvas(top, width=10, height=10, bg=T.CARD,
                        highlightthickness=0, bd=0)
        dot.create_oval(1, 1, 9, 9,
                        fill=T.PRIMARY if is_active else T.BORDER_STRONG,
                        outline="")
        dot.pack(side="left", pady=(5, 0))

        tk.Label(top, text=conn.get("name") or "未命名", bg=T.CARD, fg=T.TEXT,
                 font=T.font(11, True), anchor="w").pack(side="left", padx=(8, 0))

        if is_active:
            tag = tk.Label(top, text="当前使用", bg=T.PRIMARY_SOFT, fg=T.PRIMARY,
                           font=T.font(8), padx=6, pady=1)
            tag.pack(side="left", padx=(8, 0), pady=(2, 0))

        tk.Label(top, text=conn.get("model") or "未填模型", bg=T.CARD, fg=T.MUTED,
                 font=T.font(9, mono=True), anchor="e").pack(side="right")

        sub = "%s · %s" % (conn.get("provider") or "自定义",
                           "密钥已保存" if conn.get("api_key_encrypted") else "未填密钥")
        tk.Label(card.body, text=sub, bg=T.CARD, fg=T.TEXT_SUB, font=T.font(9),
                 anchor="w").pack(fill="x", padx=(18, 0), pady=(2, 0))

        cid = conn.get("id")
        for w in _walk(card):
            w.bind("<Button-1>", lambda e, i=cid, cd=card: self._select(i, cd))
            w.bind("<Double-Button-1>", lambda e, c2=conn: self._show_detail(c2))

    def _select(self, cid: str, card=None):
        self._selected = cid
        for b in (self._btn_edit, self._btn_del, self._btn_active):
            b.set_enabled(True)
        # 只高亮当前选中的卡片，给一个明确的视觉反馈
        prev = getattr(self, "_selected_card", None)
        if prev is not None and prev is not card:
            try:
                prev.set_border(T.BORDER)
            except Exception:
                pass
        if card is not None:
            try:
                card.set_border(T.PRIMARY)
            except Exception:
                pass
        self._selected_card = card

    def _new_conn(self):
        self._show_detail(None)

    def _edit_selected(self):
        conn = self._find(self._selected)
        if conn:
            self._show_detail(conn)

    def _find(self, cid):
        if not cid:
            return None
        for c in store.load_config().get("connections") or []:
            if c.get("id") == cid:
                return c
        return None

    def _delete_selected(self):
        conn = self._find(self._selected)
        if not conn:
            return
        if not messagebox.askyesno(
                "删除配置",
                "确定要删除「%s」吗？\n密钥会一起删掉，无法恢复。"
                % (conn.get("name") or "未命名"), parent=self):
            return
        cfg = store.load_config()
        cfg["connections"] = [c for c in cfg["connections"]
                              if c.get("id") != conn.get("id")]
        if cfg.get("active") == conn.get("id"):
            cfg["active"] = cfg["connections"][0]["id"] if cfg["connections"] else ""
        store.save_config(cfg)
        self._notify()
        self._show_list()

    def _set_active(self):
        if not self._selected:
            return
        cfg = store.load_config()
        cfg["active"] = self._selected
        store.save_config(cfg)
        self._notify()
        self._show_list()

    # ------------------------------------------------------------ 详情页

    def _show_detail(self, conn):
        self._clear()
        self._detail = True
        editing = conn is not None
        data = dict(conn or {})
        if not editing:
            preset = providers.PROVIDERS["DeepSeek"]
            data.update(name="DeepSeek", provider="DeepSeek",
                        base_url=preset["base_url"],
                        protocol=preset.get("protocol") or "openai")
        # 不套用预设模型：等用户拉取选择，也不改动已有配置。

        # 顶部：返回 + 标题
        top = tk.Frame(self._view, bg=T.BG)
        top.pack(fill="x", padx=24, pady=(18, 6))
        Button(top, "‹  返回列表", command=self._show_list, kind="plain",
               padx=8, pady=4).pack(side="left")
        tk.Label(top, text="编辑配置" if editing else "新增 AI 配置",
                 bg=T.BG, fg=T.TEXT, font=T.font(13, True)).pack(side="right")
        hline(self._view, pady=(6, 0))

        area = ScrollFrame(self._view, bg=T.BG)
        area.pack(fill="both", expand=True, padx=(24, 16), pady=(12, 0))
        body = area.inner

        vars_ = {
            "name": tk.StringVar(value=data.get("name") or ""),
            "provider": tk.StringVar(value=data.get("provider") or "DeepSeek"),
            "base_url": tk.StringVar(value=data.get("base_url") or ""),
            "model": tk.StringVar(value=data.get("model") or ""),
            # 已保存的密钥解密后回填：不然「退出再进」看到一片空白，
            # 用户会以为没保存成功，其实是压根没显示。默认仍然打码。
            "key": tk.StringVar(value=store.unprotect(
                data.get("api_key_encrypted") or "")),
            "timeout": tk.StringVar(value=str(data.get("timeout") or 120)),
            "protocol": tk.StringVar(value=data.get("protocol") or "openai"),
        }

        # 名称
        _field(body, "名称", "随便起，只要你自己认得出，比如「DeepSeek 主号」")
        e_name = make_entry(body, vars_["name"], width=52)
        e_name.pack(fill="x", pady=(0, 10))

        # 服务商
        _field(body, "服务商", "选了会自动填好地址和常用模型，不用查文档")
        names = list(providers.PROVIDERS.keys())
        cb = ttk.Combobox(body, textvariable=vars_["provider"], values=names,
                          state="readonly", font=T.font(10))
        cb.pack(fill="x", pady=(0, 10))

        # Base URL
        _field(body, "接口地址（Base URL）", "填到 /v1 这一级，末尾不带斜杠")
        make_entry(body, vars_["base_url"], width=52).pack(fill="x", pady=(0, 10))

        # 模型 + 拉取
        _field(body, "模型名", "不确定就点「拉取」，会把这家所有模型列出来")
        row = tk.Frame(body, bg=T.BG)
        row.pack(fill="x", pady=(0, 10))
        make_entry(row, vars_["model"], width=34).pack(side="left", fill="x", expand=True)
        self._btn_models = Button(row, "拉取", command=lambda: self._fetch_models(
            vars_, area), kind="ghost", padx=12, pady=6)
        self._btn_models.pack(side="left", padx=(8, 0))

        # Key
        _field(body, "API Key",
               "只存在这台电脑上，用 Windows 账户加密，别人拷走文件也解不开")
        krow = tk.Frame(body, bg=T.BG)
        krow.pack(fill="x", pady=(0, 10))
        e_key = make_entry(krow, vars_["key"], width=34, show="•")
        e_key.pack(side="left", fill="x", expand=True)
        if editing and data.get("api_key_encrypted"):
            e_key.configure(highlightbackground=T.OK)
            tk.Label(krow, text="已保存 · 点「显示」核对", bg=T.BG, fg=T.MUTED,
                     font=T.font(9)).pack(side="left", padx=(8, 0))
        Button(krow, "显示", command=lambda: _toggle_show(e_key), kind="ghost",
               padx=10, pady=6).pack(side="left", padx=(8, 0))

        hline(body, pady=(4, 14))

        # 开关：流式 / 关闭思考
        _field(body, "输出方式", None)
        sw = tk.Frame(body, bg=T.BG)
        sw.pack(fill="x", pady=(0, 10))
        v_stream = tk.BooleanVar(value=bool(data.get("stream", True)))
        v_nothink = tk.BooleanVar(value=bool(data.get("disable_thinking", False)))
        Toggle(sw, "流式输出（字一个个冒出来）", value=v_stream.get(),
               bg=T.BG, command=lambda v: v_stream.set(v)).pack(side="left")
        Toggle(sw, "关闭思考过程", value=v_nothink.get(),
               bg=T.BG, command=lambda v: v_nothink.set(v)).pack(side="left",
                                                                 padx=(24, 0))

        # 超时
        tk.Label(body, text="超时（秒）", bg=T.BG, fg=T.TEXT,
                 font=T.font(10, True), anchor="w").pack(fill="x")
        tk.Label(body, text="网络慢就调大，默认 120 够用", bg=T.BG, fg=T.MUTED,
                 font=T.font(9), anchor="w").pack(fill="x", pady=(1, 4))
        make_entry(body, vars_["timeout"], width=12).pack(anchor="w",
                                                          pady=(0, 10))

        # 只在用户实际切换服务商时应用地址；打开已有配置不触发。
        selected_provider = [vars_["provider"].get()]
        def on_provider(_=None):
            provider = vars_["provider"].get()
            if provider == selected_provider[0]:
                return
            selected_provider[0] = provider
            p = providers.PROVIDERS.get(provider) or {}
            vars_["base_url"].set(p.get("base_url") or "")
            vars_["model"].set("")
            vars_["protocol"].set(p.get("protocol") or "openai")
            if not vars_["name"].get().strip() or vars_["name"].get() in providers.PROVIDERS:
                vars_["name"].set(provider)
            self._status.configure(text="请填写 Key，再拉取并选择模型", fg=T.MUTED)
        cb.bind("<<ComboboxSelected>>", on_provider)

        # 底部按钮
        bottom = tk.Frame(self._view, bg=T.BG)
        bottom.pack(fill="x", padx=24, pady=(2, 14))

        # 状态单独占一行：报错信息往往很长，挤在按钮旁边会被裁掉大半
        self._status = tk.Label(bottom, text="", bg=T.BG, fg=T.MUTED,
                                font=T.font(9), anchor="w", justify="left",
                                wraplength=660)
        self._status.pack(fill="x", pady=(0, 8))

        row = tk.Frame(bottom, bg=T.BG)
        row.pack(fill="x")

        Button(row, "保存", command=lambda: self._save(
            editing, data, vars_, v_stream, v_nothink),
            kind="primary", padx=22, pady=8).pack(side="right")
        Button(row, "取消", command=self._show_list, kind="ghost",
               padx=18, pady=8).pack(side="right", padx=(0, 10))
        self._btn_test = Button(row, "测试连接", kind="ghost", padx=14, pady=8,
                                command=lambda: self._test(vars_))
        self._btn_test.pack(side="right", padx=(0, 10))

        # 给测试留一份表单入口，省得它去扒控件树
        self._form = {"vars": vars_, "stream": v_stream, "nothink": v_nothink,
                      "editing": editing, "data": data, "key_entry": e_key}

        e_name.focus_set()

    # ------------------------------------------------------------ 动作

    def _collect(self, vars_, v_stream, v_nothink) -> dict:
        # 超时按数字收，用户写了「2分钟」这种也退回默认值，别让 int() 抛出去
        try:
            timeout = int(str(vars_["timeout"].get()).strip() or 120)
        except (TypeError, ValueError):
            timeout = 120
        raw = {
            "name": vars_["name"].get().strip(),
            "provider": vars_["provider"].get(),
            "base_url": store.fix_base_url(vars_["base_url"].get()),
            "model": vars_["model"].get().strip(),
            "timeout": timeout,
            "stream": v_stream.get(),
            "disable_thinking": v_nothink.get(),
            "protocol": vars_["protocol"].get(),
            # 密钥总是回传：编辑时它是解密回填的原值，改动才算改
            "api_key": vars_["key"].get().strip(),
        }
        return raw

    def _save(self, editing, data, vars_, v_stream, v_nothink):
        raw = self._collect(vars_, v_stream, v_nothink)
        if not raw["base_url"]:
            return _warn(self._status, "请填接口地址")
        if not raw["model"]:
            return _warn(self._status, "请填模型名")
        if not raw["name"]:
            raw["name"] = raw["provider"]

        cfg = store.load_config()
        conns = cfg.get("connections") or []
        if editing:
            raw["id"] = data.get("id")
            prev = next((c for c in conns if c.get("id") == raw["id"]), None)
            new = store.clean_connection(raw, prev)
            conns = [new if c.get("id") == new["id"] else c for c in conns]
        else:
            if not raw.get("api_key"):
                return _warn(self._status, "新配置需要填 API Key")
            new = store.clean_connection(raw)
            conns.append(new)
            if not cfg.get("active"):
                cfg["active"] = new["id"]
        cfg["connections"] = conns
        store.save_config(cfg)
        self._notify()
        self._show_list()

    @staticmethod
    def _form_signature(vars_):
        return tuple(vars_[key].get() for key in sorted(vars_))

    def _run_async(self, vars_, work, show):
        if self._async_busy:
            return
        generation = self._generation
        signature = self._form_signature(vars_)
        self._async_busy = True
        self._btn_test.set_enabled(False)
        self._btn_models.set_enabled(False)

        def worker():
            try:
                value, error = work(), ""
            except Exception as exc:
                value, error = None, str(exc) or type(exc).__name__
            self._results.put((generation, vars_, signature, show, value, error))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_results(self):
        try:
            while True:
                generation, vars_, signature, show, value, error = self._results.get_nowait()
                if generation != self._generation or not self._detail:
                    continue
                self._async_busy = False
                self._btn_test.set_enabled(True)
                self._btn_models.set_enabled(True)
                if signature != self._form_signature(vars_):
                    self._status.configure(text="表单已修改，请重新拉取或测试连接", fg=T.WARN)
                elif error:
                    _warn(self._status, "请求失败：%s；请检查地址和 Key 后重试" % error)
                else:
                    show(value)
        except queue.Empty:
            pass
        finally:
            self._async_poll_job = self.after(40, self._poll_results)

    def destroy(self):
        self._generation += 1
        if self._async_poll_job:
            self.after_cancel(self._async_poll_job)
            self._async_poll_job = None
        super().destroy()

    def _test(self, vars_):
        if self._async_busy:
            return
        form = self._form
        raw = self._collect(vars_, form["stream"], form["nothink"])
        if not raw["api_key"]:
            return _warn(self._status, "测试前先填 API Key；已保存密钥无法解密时请重填")
        if not raw["base_url"]:
            return _warn(self._status, "先填接口地址")
        if not raw["model"]:
            return _warn(self._status, "请先拉取并选择模型，也可手动填写模型名")
        url = llm.endpoint_of(raw)
        self._status.configure(text="正在连接 %s …" % url, fg=T.MUTED)

        def show(res):
            if res.get("ok"):
                msg = "连通正常 · %d ms · 模型回了：%s\n实际请求：%s" % (
                    res.get("ms") or 0,
                    (res.get("reply") or "").replace("\n", " ")[:24] or "（空）", url)
                self._status.configure(text=msg, fg=T.OK)
            else:
                _warn(self._status, "%s\n实际请求：%s" % (res.get("error") or "连接失败", url))
        self._run_async(vars_, lambda: llm.test_connection(raw), show)

    def _fetch_models(self, vars_, area=None):
        if self._async_busy:
            return
        base = store.fix_base_url(vars_["base_url"].get())
        key = vars_["key"].get().strip()
        if not base:
            return _warn(self._status, "先填接口地址")
        if not key:
            return _warn(self._status, "拉取模型需要填 API Key")
        self._status.configure(text="正在拉取模型列表…", fg=T.MUTED)
        conn = {"base_url": base, "api_key": key,
                "protocol": vars_["protocol"].get(), "timeout": 30}
        self._run_async(vars_, lambda: llm.list_models(conn),
                        lambda items: self._pick_model(items, vars_))

    def _pick_model(self, items, vars_):
        if not items:
            return _warn(self._status, "这家没有返回模型列表，手动填吧")
        current = (vars_["model"].get() or "").strip()
        self._status.configure(text="共 %d 个模型，点一个填进去" % len(items),
                               fg=T.OK)

        win = tk.Toplevel(self)
        win.title("选择模型")
        win.configure(bg=T.BG)
        win.geometry("520x480")
        win.transient(self)

        tk.Label(win, text="点一个填进配置", bg=T.BG, fg=T.TEXT,
                 font=T.font(10, True)).pack(anchor="w", padx=18, pady=(14, 8))

        sf = ScrollFrame(win, bg=T.BG)
        sf.pack(fill="both", expand=True, padx=(18, 12), pady=(0, 12))
        for name in items:
            on = (name == current)
            # 宽度写死成可视宽度：Canvas 不会跟着 pack(fill) 拉长
            b = Button(sf.inner, name + ("　· 当前" if on else ""),
                       kind="soft" if on else "plain", padx=12, pady=6,
                       parent_bg=T.BG, align="left", width=452)
            b.pack(fill="x", pady=1)
            b.set_command(lambda n=name: (vars_["model"].set(n), win.destroy()))
        sf.inner.update_idletasks()


# ------------------------------------------------------------------ 小工具


def _field(parent, label, hint):
    box = tk.Frame(parent, bg=T.BG)
    box.pack(fill="x", pady=(0, 4))
    tk.Label(box, text=label, bg=T.BG, fg=T.TEXT, font=T.font(10, True),
             anchor="w").pack(side="left")
    if hint:
        tk.Label(box, text=hint, bg=T.BG, fg=T.MUTED, font=T.font(9),
                 anchor="w").pack(side="left", padx=(10, 0), pady=(2, 0))
    return box


def _toggle_show(entry):
    entry.configure(show="" if entry.cget("show") else "•")


def _warn(label, text):
    if label is not None:
        try:
            label.configure(text=text, fg=T.ERR)
        except Exception:
            pass


def _walk(widget):
    """递归遍历所有子控件，用于给整张卡片绑定点击。"""
    out = [widget]
    for c in widget.winfo_children():
        out.extend(_walk(c))
    return out
