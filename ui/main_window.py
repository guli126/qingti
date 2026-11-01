"""主窗口。

    ┌───────────┬──────────────────────────────────────────────┐
    │ 轻提       │ 任务标题 · 场景 / 模式        ● 模型   新对话  │
    │           ├──────────────────────────────────────────────┤
    │ ▾ 编程  +  │ [任务提示词] [系统提示词] [迭代]   详细 [极简…] │
    │   记账助手 ├──────────────────────────────────────────────┤
    │   周报改写 │                                              │
    │ ▸ 办公  +  │              对话区（可滚动）                  │
    │ ▾ 图像  +  │                                              │
    │           ├──────────────────────────────────────────────┤
    │ 提示词     │ ╭──────────────────────────────────────────╮ │
    │ AI 配置    │ │ 输入…                          Enter 发送 │ │
    │           │ ╰──────────────────────────────────────────╯ │
    └───────────┴──────────────────────────────────────────────┘

三个关键约定：
  1. 回车发送、Ctrl+Enter 换行（Shift+Enter 也换行）
  2. 左侧每个场景下的任务都能新建 / 重命名 / 删除，场景能收起展开
  3. 任务是持久化的：关掉再打开，点回旧任务能原样恢复对话
"""

import queue
import threading
import tkinter as tk

from core import engine, llm, sessions, store

from . import theme as T
from .editor import EditorWindow
from .settings import SettingsWindow
from .sidebar import SceneTree
from .widgets import (Button, RoundCard, ScrollFrame, render_markdown,
                      wrap_to)

SIDE_W = 238
TOP_H = 58


class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        # DPI 缩放和字体必须在建任何控件之前定下来，否则字会糊、尺寸会错
        T.apply_scaling(self)
        T.init_fonts(self)
        T.apply_ttk(self)

        self.title("轻提")
        self.configure(bg=T.BG)
        self.minsize(1120, 720)
        self._fit_screen()

        # ---- 当前状态
        self._scene = "coding"
        self._mode = "task"
        self._detail = "标准"
        self._task = None            # dict | None，None 表示「还没开聊的新对话」
        self._messages = []          # 这一轮（一次优化）的 API 消息链
        self._run_input = ""         # 这一轮最开始那句话
        self._round = 1
        self._last_prompt = ""

        self._busy = False
        self._q = queue.Queue()
        self._stream_label = None
        self._stream_card = None
        self._stream_buffer = ""
        self._settings_win = None
        self._editor_win = None
        self._placeholder_on = False
        self._sidebar_job = None
        self._welcome_job = None
        self._welcome_bind = None
        self._welcome_frame = None
        self._welcome_idle_job = None
        self._poll_job = None
        self._pending_ask = None
        self._failed_request = False
        self._iterating = False
        self._mode_btns = {}
        self._detail_btns = {}
        self._modes_scene = None

        self._build()
        self._refresh_conn_badge()
        self._restore_last()
        self._poll()

    # ============================================================ 布局

    def _fit_screen(self):
        """窗口尽量占满屏幕但留出边距，小屏也不会跑到屏幕外。"""
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = max(1120, min(1800, int(sw * 0.74)))
        h = max(720, min(1240, int(sh * 0.80)))
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 3)
        self.geometry("%dx%d+%d+%d" % (w, h, x, y))

    def _build(self):
        mid = tk.Frame(self, bg=T.BG)
        mid.pack(fill="both", expand=True)
        self._build_sidebar(mid)

        right = tk.Frame(mid, bg=T.BG)
        right.pack(side="left", fill="both", expand=True)
        self._build_topbar(right)
        self._build_modes(right)
        self._build_chat(right)
        self._build_composer(right)

    # ---------------------------------------------------------- 侧栏

    def _build_sidebar(self, parent):
        side = tk.Frame(parent, bg=T.SIDEBAR, width=SIDE_W)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        brand = tk.Frame(side, bg=T.SIDEBAR)
        brand.pack(fill="x", padx=18, pady=(16, 16))
        tk.Label(brand, text="轻提", bg=T.SIDEBAR, fg="#FFFFFF",
                 font=T.font(16, True)).pack(side="left")
        tk.Label(brand, text="提示词优化器", bg=T.SIDEBAR, fg="#5E6878",
                 font=T.font(8)).pack(side="left", padx=(8, 0), pady=(6, 0))

        tk.Label(side, text="场景 · 任务", bg=T.SIDEBAR, fg="#5E6878",
                 font=T.font(8, True), anchor="w").pack(fill="x", padx=20,
                                                        pady=(0, 6))

        # 任务多了要能滚，滚动条也得是深色的
        self._nav = ScrollFrame(side, bg=T.SIDEBAR, right_gap=4,
                                sb_style="Dark.Vertical.TScrollbar")
        self._nav.pack(fill="both", expand=True, padx=(6, 2))

        self._sidebar = SceneTree(
            self._nav.inner,
            on_pick=self._pick_task,
            on_new=self._new_chat,
            on_toggle_group=self._on_group_toggle,
            on_changed=self._on_task_changed,
        )
        self._sidebar.pack(fill="x", pady=(0, 10))

        tk.Frame(side, bg="#2A3342", height=1).pack(fill="x", padx=16,
                                                    pady=(6, 8))
        Button(side, "提示词", command=self._open_editor, kind="nav",
               padx=14, pady=8, width=SIDE_W - 36, align="left",
               parent_bg=T.SIDEBAR).pack(padx=12, pady=1)
        Button(side, "AI 配置", command=self._open_settings, kind="nav",
               padx=14, pady=8, width=SIDE_W - 36, align="left",
               parent_bg=T.SIDEBAR).pack(padx=12, pady=(1, 14))

    def _sync_sidebar(self, defer=False):
        """重建任务树并标出当前任务。

        defer 用于「点任务 / 删任务」这两种情况：触发刷新的按钮自己正在处理
        鼠标事件，立刻把它销毁容易留下悬空的回调，等一拍再刷更稳。
        """
        if defer:
            self.after(10, self._sync_sidebar)
            return
        try:
            self._sidebar.refresh()
            if self._task:
                self._sidebar.expand(self._scene)
                self._sidebar.set_active(self._task.get("id") or "")
        except tk.TclError:
            pass

    def _schedule_sidebar(self):
        """连续落盘时合并成一次刷新，别每个字都重建整棵树。"""
        if self._sidebar_job:
            try:
                self.after_cancel(self._sidebar_job)
            except Exception:
                pass
        self._sidebar_job = self.after(320, self._flush_sidebar)

    def _flush_sidebar(self):
        self._sidebar_job = None
        self._sync_sidebar()

    # ---------------------------------------------------------- 顶栏

    def _build_topbar(self, parent):
        bar = tk.Frame(parent, bg=T.CARD, height=TOP_H)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        left = tk.Frame(bar, bg=T.CARD)
        left.pack(side="left", padx=(24, 0))
        self._title_lab = tk.Label(left, text="新对话", bg=T.CARD, fg=T.TEXT,
                                   font=T.font(12, True), anchor="w")
        self._title_lab.pack(side="left")
        self._sub_lab = tk.Label(left, text="", bg=T.CARD, fg=T.MUTED,
                                 font=T.font(9), anchor="w")
        self._sub_lab.pack(side="left", padx=(10, 0), pady=(3, 0))

        self._conn_btn = Button(bar, "未配置模型", command=self._open_settings,
                                kind="ghost", padx=12, pady=6)
        self._conn_btn.pack(side="right", padx=(0, 18))
        Button(bar, "+ 新对话", command=lambda: self._new_chat(self._scene),
               kind="plain", padx=12, pady=6).pack(side="right", padx=(0, 4))

        tk.Frame(parent, bg=T.BORDER, height=1).pack(fill="x")

    # ---------------------------------------------------------- 模式栏

    def _build_modes(self, parent):
        wrap = tk.Frame(parent, bg=T.BG)
        wrap.pack(fill="x", padx=24, pady=(11, 7))

        self._mode_bar = tk.Frame(wrap, bg=T.BG)
        self._mode_bar.pack(side="left")

        right = tk.Frame(wrap, bg=T.BG)
        right.pack(side="right")
        tk.Label(right, text="详细程度", bg=T.BG, fg=T.MUTED,
                 font=T.font(9)).pack(side="left", padx=(0, 8))
        self._detail_bar = tk.Frame(right, bg=T.BG)
        self._detail_bar.pack(side="left")

        self._render_modes()

    def _render_modes(self, rebuild=False):
        """画模式 / 详细程度两组胶囊。

        以前每次点击都把整排按钮销毁重建。问题在于点击事件还没走完，
        正在被点的那个按钮就已经被 destroy 了，Tk 往往会吞掉后续回调，
        表现出来就是「点了没反应、高亮不跟着走」。
        现在改成：按钮只在换场景时重建一次，切换只改样式。
        """
        if (rebuild or not getattr(self, "_mode_btns", None)
                or self._modes_scene != self._scene):
            for w in self._mode_bar.winfo_children():
                w.destroy()
            for w in self._detail_bar.winfo_children():
                w.destroy()
            self._mode_btns = {}
            self._detail_btns = {}
            self._modes_scene = self._scene

            for key, label, _hint in engine.SCENES[self._scene]["modes"]:
                b = Button(self._mode_bar, label, kind="plain", padx=15, pady=6,
                           radius=14,
                           command=lambda k=key: self._pick_mode(k))
                b.pack(side="left", padx=(0, 5))
                self._mode_btns[key] = b

            self._detail_bar.pack_forget()
            if self._scene != "image":
                self._detail_bar.pack(side="left")
                for d in engine.DETAILS:
                    b = Button(self._detail_bar, d, kind="plain", padx=11,
                               pady=5, radius=13, size=9,
                               command=lambda x=d: self._pick_detail(x))
                    b.pack(side="left", padx=(0, 4))
                    self._detail_btns[d] = b

        for key, b in self._mode_btns.items():
            on = (key == self._mode)
            b.set_kind("soft" if on else "plain")
            b.set_bold(on)
        for d, b in (self._detail_btns or {}).items():
            on = (d == self._detail)
            b.set_kind("soft" if on else "plain")
            b.set_bold(on)

    # ---------------------------------------------------------- 对话区

    def _build_chat(self, parent):
        self._chat = ScrollFrame(parent, bg=T.BG, right_gap=12)
        self._chat.pack(fill="both", expand=True, padx=(24, 16), pady=(2, 0))

    def _build_composer(self, parent):
        box = tk.Frame(parent, bg=T.BG)
        box.pack(fill="x", padx=24, pady=(10, 14))

        card = RoundCard(box, bg=T.CARD, border=T.BORDER_STRONG, radius=14,
                         paddingx=2, paddingy=2, parent_bg=T.BG)
        card.pack(fill="x")
        holder = card.body

        self._input = tk.Text(holder, height=4, relief="flat", bd=0, bg=T.CARD,
                              fg=T.TEXT, insertbackground=T.TEXT,
                              font=T.font(10), wrap="word", padx=12, pady=10,
                              spacing1=1, spacing3=2, highlightthickness=0)
        self._input.pack(fill="x", padx=10, pady=(8, 0))
        self._input.bind("<FocusIn>", self._clear_placeholder)
        self._input.bind("<FocusOut>", self._restore_placeholder)
        self._input.bind("<Key>", self._on_key)
        # 回车发送，Ctrl/Shift + 回车换行。更具体的组合会盖掉这个绑定，
        # 所以顺序不重要，靠 <Control-Return> 自己的 break 拦下来。
        self._input.bind("<Return>", self._on_key_return)
        self._input.bind("<Control-Return>", self._on_key_newline)
        self._input.bind("<Shift-Return>", self._on_key_newline)

        foot = tk.Frame(holder, bg=T.CARD)
        foot.pack(fill="x", padx=14, pady=(2, 10))
        tk.Label(foot, text="Enter 发送 · Ctrl+Enter 换行", bg=T.CARD,
                 fg=T.MUTED, font=T.font(8)).pack(side="left")

        self._btn_send = Button(foot, "发送", command=self._on_send,
                                kind="primary", padx=20, pady=6, radius=13)
        self._btn_send.pack(side="right")
        self._btn_retry = Button(foot, "重试上次请求", command=self._retry_request,
                                 kind="ghost", padx=12, pady=6, radius=13)

        self._hint = tk.Label(box, text="", bg=T.BG, fg=T.MUTED,
                              font=T.font(9), anchor="w")
        self._hint.pack(fill="x", pady=(6, 0))

        self._set_placeholder()

    # ============================================================ 输入框

    def _placeholder_text(self):
        if self._pending_ask:
            return "在这里补充回答，或在上方选择后确认"
        if self._last_prompt:
            return "继续描述修改要求，比如：再简洁一点 / 补充异常处理"
        return engine.SCENES[self._scene].get("placeholder") or "说说你想做什么"

    def _refresh_composer(self):
        if self._busy:
            label = "生成中…"
        elif self._pending_ask:
            label = "发送补充"
        elif self._last_prompt:
            label = "继续改"
        else:
            label = "发送"
        self._btn_send.set_text(label)
        self._btn_send.set_enabled(not self._busy)
        self._btn_retry.pack_forget()
        if self._failed_request and not self._busy:
            self._btn_retry.pack(side="right", padx=(0, 8))
        if self._placeholder_on or not self._current_text():
            self._set_placeholder()

    def _reset_conversation(self):
        self._pending_ask = None
        self._failed_request = False
        self._iterating = False
        self._run_input = ""

    def _retry_request(self):
        if self._busy or not self._failed_request:
            return
        conn = self._ready_conn()
        if conn is not None:
            self._start(self._run_input, conn)

    def _set_placeholder(self):
        self._input.delete("1.0", "end")
        self._input.insert("1.0", self._placeholder_text())
        self._input.configure(fg=T.MUTED)
        self._placeholder_on = True

    def _clear_placeholder(self, _=None):
        if self._placeholder_on:
            self._input.delete("1.0", "end")
            self._input.configure(fg=T.TEXT)
            self._placeholder_on = False

    def _restore_placeholder(self, _=None):
        if not self._input.get("1.0", "end-1c").strip():
            self._set_placeholder()

    def _current_text(self):
        if self._placeholder_on:
            return ""
        return self._input.get("1.0", "end-1c").strip()

    def _on_key(self, _event):
        """一开始打字就把占位提示清掉。

        只在 FocusIn 清是不够的：发完一条消息后输入框还是焦点状态，
        FocusIn 不会再触发，占位文字会赖着不走，用户打字就接在后面。
        """
        if self._placeholder_on:
            self._clear_placeholder()
        return None

    def _on_key_return(self, event):
        """Enter 发送；Shift+Enter 换行。"""
        if event.state & 0x0001:        # Shift
            return self._on_key_newline()
        self._on_send()
        return "break"

    def _on_key_newline(self, _=None):
        self._clear_placeholder()
        self._input.insert("insert", "\n")
        self._input.see("insert")
        return "break"

    # ============================================================ 任务

    def _restore_last(self):
        """启动时回到上次那个任务；没有就显示欢迎页。"""
        data = sessions.load()
        tid = data.get("active") or ""
        task = sessions.get(tid, data) if tid else None
        if task and task.get("timeline"):
            self._apply_task(task)
        else:
            scenes = [t for t in data["tasks"] if t.get("timeline")]
            if scenes:
                self._apply_task(sorted(
                    scenes, key=lambda t: -(t.get("updated") or 0))[0])
            else:
                self._new_chat("coding", remember=False)

    def _apply_task(self, task, render=True):
        self._task = task
        self._scene = task.get("scene") or "coding"
        if self._scene not in engine.SCENES:
            self._scene = "coding"
        modes = [m[0] for m in engine.SCENES[self._scene]["modes"]]
        self._mode = task.get("mode") if task.get("mode") in modes else modes[0]

        self._reset_conversation()
        self._messages = []
        self._round = 1
        self._last_prompt = ""
        for item in task.get("timeline") or []:
            role = item.get("role")
            if role == "user":
                text = item.get("text") or ""
                self._messages.append({"role": "user", "content": text})
                self._run_input = text
                self._round = min(self._round + 1, engine.MAX_ROUNDS)
                self._failed_request = False
            elif role in ("result", "ask", "questions"):
                content = item.get("raw") or item.get("prompt") or ""
                if content:
                    self._messages.append({"role": "assistant", "content": content})
                if role == "result":
                    self._last_prompt = item.get("prompt") or ""
                    self._round = 1
                    self._iterating = False
            elif role == "error":
                self._failed_request = True
        # 新时间线精确记录请求状态；旧会话仍可从消息与最近结果继续。
        for item in reversed(task.get("timeline") or []):
            if item.get("role") == "user":
                self._round = item.get("round") or self._round
                self._run_input = item.get("run_input") or self._run_input
                self._iterating = bool(item.get("iterating", False))
                break
        if (task.get("timeline") or [{}])[-1].get("role") == "result":
            self._iterating = False
            self._failed_request = False
            self._round = 1

        self._render_modes()
        self._set_placeholder()
        self._refresh_composer()
        self._update_title()
        if render:
            if task.get("timeline"):
                self._render_timeline()
            else:
                # 空草稿：进去也应该是欢迎页，不是一片空白
                self._chat.clear()
                self._show_welcome()
        self._sync_sidebar(defer=True)

    def _pick_task(self, tid):
        if self._busy:
            return
        if self._task and self._task.get("id") == tid:
            return
        task = sessions.get(tid)
        if not task:
            return
        sessions.set_active(tid)
        self._apply_task(task)

    def _new_chat(self, scene=None, remember=True):
        """新对话。

        点侧栏的「+」要立刻在对应场景下面长出一行「新对话」，否则用户会觉得
        按钮没反应。草稿任务落盘时只保留一个，说完第一句话就自动改名。
        """
        if self._busy:
            self._hint.configure(text="正在生成，请等完成后再新建对话", fg=T.WARN)
            return
        self._reset_conversation()
        scene = scene if scene in engine.SCENES else self._scene
        self._scene = scene
        self._mode = engine.SCENES[scene]["modes"][0][0]
        if remember:
            self._task = sessions.create(scene, "新对话", self._mode)
            sessions.set_collapsed(scene, False)
        else:
            self._task = None
        self._messages = []
        self._round = 1
        self._run_input = ""
        self._last_prompt = ""
        self._render_modes()
        self._set_placeholder()
        self._refresh_composer()
        self._refresh_hint()
        self._update_title()
        self._show_welcome()
        if remember:
            self._sync_sidebar(defer=True)

    def _update_title(self):
        if self._task:
            self._title_lab.configure(
                text=(self._task.get("title") or "未命名")[:30])
            self._sub_lab.configure(
                text="%s · %s" % (engine.SCENES[self._scene]["name"],
                                  engine.mode_name(self._scene, self._mode)))
        else:
            self._title_lab.configure(text="新对话")
            self._sub_lab.configure(text=engine.SCENES[self._scene]["name"])

    def _log(self, item):
        if not self._task:
            return
        tid = self._task.get("id") or ""
        sessions.append(tid, item)
        # append 会顺手改标题，得把内存里这份换掉，顶栏才跟着变
        got = sessions.get(tid)
        if got:
            self._task = got
        self._schedule_sidebar()

    def _on_group_toggle(self, _scene, _collapsed):
        pass        # 折叠状态在 sessions 里已经存了，界面自己也换过箭头了

    def _on_task_changed(self):
        """侧栏重命名 / 删除之后回调。删的正好是当前任务就退回新对话。"""
        if self._task and not sessions.get(self._task.get("id") or ""):
            self._new_chat(self._scene)
            return
        if self._task:
            got = sessions.get(self._task.get("id") or "")
            if got:
                self._task = got
                self._update_title()

    # ============================================================ 顶栏按钮

    def _open_settings(self):
        if self._settings_win is not None and self._settings_win.winfo_exists():
            self._settings_win.lift()
            self._settings_win.focus_set()
            return
        self._settings_win = SettingsWindow(self, on_change=self._on_config_changed)

    def _open_editor(self):
        if self._editor_win is not None and self._editor_win.winfo_exists():
            self._editor_win.lift()
            self._editor_win.focus_set()
            return
        self._editor_win = EditorWindow(self)

    def _on_config_changed(self):
        self._refresh_conn_badge()

    def _refresh_conn_badge(self):
        cfg = store.load_config()
        conn = store.find_connection(cfg, None)
        if conn:
            self._conn_btn.set_text("● " + (conn.get("name") or "未命名"))
            self._conn_btn.set_kind("soft")
        else:
            self._conn_btn.set_text("未配置模型")
            self._conn_btn.set_kind("ghost")
        self._refresh_hint()

    def _refresh_hint(self):
        cfg = store.load_config()
        conn = store.find_connection(cfg, None)
        if not conn:
            self._hint.configure(text="还没有配置 AI 模型 · 点右上角「AI 配置」加一个",
                                 fg=T.WARN)
        elif not conn.get("base_url"):
            self._hint.configure(text="请在「AI 配置」里补全接口地址", fg=T.WARN)
        elif not conn.get("model"):
            self._hint.configure(text="请在「AI 配置」里填 Key、拉取并选择模型", fg=T.WARN)
        elif not store.runtime_connection(conn).get("api_key"):
            self._hint.configure(text="「%s」的 API Key 未填写或无法解密，请重新填写"
                                      % (conn.get("name") or ""), fg=T.WARN)
        else:
            text = ("在底部输入修改要求，将沿用当前对话；新任务请点「新对话」"
                    if self._last_prompt else "输入需求后按 Enter 发送，AI 会按需提问")
            self._hint.configure(text=text, fg=T.MUTED)

    # ============================================================ 场景 / 模式

    def _pick_mode(self, key):
        if self._busy or key == self._mode:
            return
        if key not in {m[0] for m in engine.SCENES[self._scene]["modes"]}:
            return
        self._mode = key
        if self._task:
            sessions.set_mode(self._task.get("id") or "", key)
        self._render_modes()
        self._update_title()
        self._refresh_composer()
        # 还没开始对话时，切模式连欢迎页一起换，让「切了页面」这件事看得见
        if self._task is None or not (self._task.get("timeline") or []):
            self._schedule_welcome()

    def _pick_detail(self, d):
        if d == self._detail:
            return
        self._detail = d
        self._render_modes()

    # ============================================================ 发送

    def _ready_conn(self):
        cfg = store.load_config()
        raw = store.find_connection(cfg, None)
        if not raw:
            self._hint.configure(text="还没有配置 AI 模型，点右上角「AI 配置」加一个",
                                 fg=T.WARN)
            return None
        if not raw.get("base_url"):
            self._hint.configure(text="请在「AI 配置」里补全接口地址", fg=T.WARN)
            return None
        if not raw.get("model"):
            self._hint.configure(text="请在「AI 配置」里拉取并选择模型", fg=T.WARN)
            return None
        conn = store.runtime_connection(raw)
        if not conn.get("api_key"):
            self._hint.configure(text="API Key 未填写或无法解密，请在「AI 配置」重新填写", fg=T.WARN)
            return None
        return conn

    def _on_send(self):
        if self._busy:
            return
        text = self._current_text()
        if not text:
            self._hint.configure(text="请先输入修改要求" if self._last_prompt
                                 else "先说一句你想做什么", fg=T.WARN)
            return
        conn = self._ready_conn()
        if conn is not None:
            self._submit_text(text, conn)

    def _submit_text(self, text, conn, answer=None):
        if self._task is None:
            self._task = sessions.create(self._scene, text, self._mode)
            self._sync_sidebar(defer=True)
        self._hide_welcome()
        if self._pending_ask:
            self._finish_ask(answer or {"items": [], "skipped": False, "text": text})
            self._round = min(self._round + 1, engine.MAX_ROUNDS)
        elif self._last_prompt and not self._iterating:
            self._mode = "iterate"
            sessions.set_mode(self._task["id"], self._mode)
            self._task["mode"] = self._mode
            self._render_modes()
            self._round = 1
            self._run_input = text
            self._iterating = True
        elif not self._messages:
            self._round = 1
            self._run_input = text
        else:
            self._round = min(self._round + 1, engine.MAX_ROUNDS)
        self._failed_request = False
        self._hint.configure(text="", fg=T.MUTED)
        self._set_placeholder()
        self._bubble_user(text)
        self._log({"role": "user", "text": text, "round": self._round,
                   "run_input": self._run_input, "iterating": self._iterating})
        self._messages.append({"role": "user", "content": text})
        self._update_title()
        self._start(self._run_input, conn)

    def _start(self, text, conn):
        tid = engine.template_id(self._scene, self._mode)
        round_ = self._round
        try:
            system = engine.build_system(
                tid, text, detail=self._detail, round_=round_,
                max_rounds=engine.MAX_ROUNDS,
                previous=self._last_prompt, model=conn.get("model") or "",
                scene=self._scene,
                glossary=engine.SCENES[self._scene].get("glossary", False))
        except Exception as e:
            self._on_error(str(e))
            return

        self._failed_request = False
        messages = [dict(m) for m in self._messages]
        self._set_busy(True)
        self._bubble_stream()

        def worker():
            try:
                parsed, result = engine.send(
                    conn, system, messages, round_=round_,
                    max_rounds=engine.MAX_ROUNDS,
                    on_delta=lambda s: self._q.put(("delta", s)))
                self._q.put(("done", parsed, result))
            except llm.ChatError as e:
                self._q.put(("error", str(e)))
            except Exception as e:
                self._q.put(("error", "出错了：%s" % e))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        """把后台线程塞进队列的结果搬到界面上。

        单条消息处理失败绝不能把整条轮询链弄断——一旦断了，之后所有回复都
        显示不出来，看起来就像「卡在生成中」。所以每条单独兜住，最后无条件
        重新排下一次。
        """
        try:
            while True:
                item = self._q.get_nowait()
                kind = item[0]
                try:
                    if kind == "delta":
                        self._append_delta(item[1])
                    elif kind == "done":
                        self._on_done(item[1], item[2])
                    elif kind == "error":
                        self._on_error(item[1])
                except Exception:
                    import traceback
                    traceback.print_exc()
        except queue.Empty:
            pass
        finally:
            self.after(40, self._poll)

    def _append_delta(self, text):
        if self._stream_label is None:
            return
        try:
            self._stream_buffer = getattr(self, "_stream_buffer", "") + text
            self._stream_label.configure(text=self._stream_buffer)
            self._chat.to_bottom()
        except tk.TclError:
            pass

    def _on_done(self, parsed, result):
        self._set_busy(False)
        self._drop_stream()
        self._stream_buffer = ""

        if parsed.get("kind") == "ask" and parsed.get("ask"):
            self._messages.append({"role": "assistant",
                                   "content": parsed.get("raw") or ""})
            self._log({"role": "questions", "ask": parsed["ask"],
                       "raw": parsed.get("raw") or ""})
            self._ask_card(parsed["ask"], parsed.get("raw") or "")
            self._refresh_composer()
            self._hint.configure(text="可在上方选择后确认，也可直接在底部输入回答", fg=T.MUTED)
            return

        self._last_prompt = parsed.get("prompt") or ""
        truncated = bool(result.get("truncated"))
        self._result_card(parsed, truncated)
        self._log({"role": "result", "prompt": self._last_prompt,
                   "raw": parsed.get("raw") or "", "truncated": truncated})
        engine.remember(self._scene, self._mode,
                        engine.template_id(self._scene, self._mode),
                        self._run_input, parsed)
        self._messages.append({"role": "assistant",
                               "content": parsed.get("raw") or self._last_prompt})
        self._iterating = False
        self._round = 1
        self._refresh_composer()
        self._refresh_hint()

    def _on_error(self, msg):
        self._failed_request = True
        self._set_busy(False)
        self._drop_stream()
        self._stream_buffer = ""
        self._error_card(msg)
        self._log({"role": "error", "text": msg})
        self._hint.configure(text="生成失败，可点「重试上次请求」，也可在底部补充要求", fg=T.WARN)

    def _set_busy(self, on: bool):
        self._busy = on
        self._refresh_composer()
        for b in list(self._mode_btns.values()) + list(self._detail_btns.values()):
            b.set_enabled(not on)

    # ============================================================ 欢迎页

    def _hide_welcome(self):
        for name in ("_welcome_job", "_welcome_idle_job"):
            job = getattr(self, name, None)
            if job:
                self.after_cancel(job)
                setattr(self, name, None)
        self._drop_welcome_bind()
        if self._welcome_frame is not None:
            if self._welcome_frame.winfo_exists():
                self._welcome_frame.destroy()
            self._welcome_frame = None

    def _show_welcome(self):
        if self._busy or (self._task or {}).get("timeline"):
            return
        self._hide_welcome()
        self._chat.clear()
        scene = engine.SCENES[self._scene]

        outer = tk.Frame(self._chat.inner, bg=T.BG)
        self._welcome_frame = outer
        outer.pack(fill="x")
        # 空页面上方留白，让内容大致落在可视区中间（滚动区高度只有布局完才知道）
        pad = tk.Frame(outer, bg=T.BG, height=60)
        pad.pack(fill="x")
        box = tk.Frame(outer, bg=T.BG)
        box.pack(fill="x")

        tk.Label(box, text="说一句你想做什么", bg=T.BG, fg=T.TEXT,
                 font=T.font(20, True)).pack(anchor="center")
        tk.Label(box, text="说不清也没关系，它会先问你几个带选项的问题",
                 bg=T.BG, fg=T.MUTED, font=T.font(10)).pack(anchor="center",
                                                            pady=(10, 0))

        wrap = tk.Frame(box, bg=T.BG)
        wrap.pack(anchor="center", pady=(30, 0))
        for key, label, hint in scene["modes"]:
            self._tip_card(wrap, key, label, hint)

        tk.Label(box, text="左边「+」可以在对应的场景下开一个新任务",
                 bg=T.BG, fg="#B4BAC4", font=T.font(9)).pack(anchor="center",
                                                             pady=(28, 0))

        # 窗口大小变了要重新算留白；重复进欢迎页时先把上一个回调摘掉
        self._drop_welcome_bind()

        def center(_=None):
            try:
                room = self._chat.canvas.winfo_height() - box.winfo_reqheight()
                pad.configure(height=max(48, int(room * 0.45)))
            except tk.TclError:
                pass

        self._welcome_bind = self._chat.canvas.bind("<Configure>", center,
                                                    add="+")
        self._welcome_idle_job = self.after_idle(center)

    def _drop_welcome_bind(self):
        if self._welcome_bind:
            try:
                self._chat.canvas.unbind("<Configure>", self._welcome_bind)
            except Exception:
                pass
            self._welcome_bind = None

    def _tip_card(self, parent, key, label, hint):
        on = (key == self._mode)
        card = RoundCard(parent, bg=T.CARD,
                         border=T.PRIMARY if on else T.BORDER,
                         border_width=2 if on else 1,
                         paddingx=16, paddingy=14, parent_bg=T.BG, width=196)
        card.pack(side="left", padx=7)

        tk.Label(card.body, text=label, bg=T.CARD,
                 fg=T.PRIMARY if on else T.TEXT,
                 font=T.font(10, True), anchor="w").pack(fill="x")
        tk.Label(card.body, text=hint, bg=T.CARD, fg=T.MUTED, font=T.font(9),
                 anchor="w", wraplength=158, justify="left").pack(
            fill="x", pady=(5, 0))

        # 绑定必须放在最后：_walk 只扫「此刻已经存在」的子控件。
        # 以前绑在前面，卡片里的两行字还没建出来，于是点在字上完全没反应，
        # 只有点在卡片边缘的空白处才切得动——这就是「要按好几下」的原因。
        for w in _walk(card):
            w.configure(cursor="hand2")
            w.bind("<Button-1>", lambda e, k=key: self._pick_mode(k))
            if not on:
                w.bind("<Enter>", lambda e, c=card: c.set_border(T.PRIMARY))
                # 从文字挪到内边距也会触发 Leave，所以在真正离开整张卡时才复原
                w.bind("<Leave>", lambda e, c=card: _leave_card(c))

    def _schedule_welcome(self):
        """把欢迎页的重建推迟一帧。

        切换模式时重建整页要 50ms 左右，而点击事件的控件就在这个页面里，
        在自己事件的回调里被 destroy 容易让 Tk 吞掉后续处理。
        先让高亮画出来，下一帧再换页面，手感立刻不一样。
        """
        if self._welcome_job:
            try:
                self.after_cancel(self._welcome_job)
            except Exception:
                pass
        self._welcome_job = self.after(16, self._draw_welcome)

    def _draw_welcome(self):
        self._welcome_job = None
        self._show_welcome()

    # ============================================================ 时间线

    def _render_timeline(self):
        self._hide_welcome()
        self._chat.clear()
        items = (self._task or {}).get("timeline") or []
        for index, item in enumerate(items):
            role = item.get("role")
            if role == "user":
                self._bubble_user(item.get("text") or "")
            elif role == "questions":
                if index == len(items) - 1:
                    self._ask_card(item.get("ask") or [], item.get("raw") or "")
            elif role == "ask":
                self._ask_card_static(item)
            elif role == "result":
                self._result_card(item, item.get("truncated"))
            elif role == "error":
                self._error_card(item.get("text") or "")
        self._refresh_composer()
        self._chat.to_bottom()

    def _bubble_user(self, text):
        self._hide_welcome()
        row = tk.Frame(self._chat.inner, bg=T.BG)
        row.pack(fill="x", pady=(10, 6), padx=(0, 6))
        label = tk.Label(row, text=text, bg=T.BUBBLE_USER, fg="#FFFFFF",
                         font=T.font(10), justify="left", wraplength=640,
                         padx=14, pady=10)
        label.pack(side="right")
        wrap_to(row, label, reserve=200)
        self._chat.to_bottom()

    def _bubble_stream(self):
        card = RoundCard(self._chat.inner, bg=T.CARD, border=T.BORDER,
                         paddingx=16, paddingy=14, parent_bg=T.BG)
        card.pack(fill="x", pady=(0, 10))

        head = tk.Frame(card.body, bg=T.CARD)
        head.pack(fill="x")
        tk.Label(head, text="正在生成", bg=T.CARD, fg=T.PRIMARY,
                 font=T.font(9, True)).pack(side="left")
        dots = tk.Label(head, text="…", bg=T.CARD, fg=T.MUTED,
                        font=T.font(9))
        dots.pack(side="left", padx=(2, 0))

        label = tk.Label(card.body, text="", bg=T.CARD, fg=T.TEXT_SUB,
                         font=T.font(10), justify="left", anchor="w",
                         wraplength=720)
        label.pack(fill="x", pady=(8, 0))
        wrap_to(card, label, reserve=80)
        self._stream_label = label
        self._stream_card = card
        self._stream_buffer = ""
        self._chat.to_bottom()
        return label, card

    def _drop_stream(self):
        card = getattr(self, "_stream_card", None)
        if card is not None:
            try:
                card.destroy()
            except tk.TclError:
                pass
        self._stream_label = None
        self._stream_card = None

    def _error_card(self, msg):
        card = RoundCard(self._chat.inner, bg=T.ERR_SOFT, border="#F3C7C7",
                         paddingx=16, paddingy=12, parent_bg=T.BG)
        card.pack(fill="x", pady=(0, 10))
        lab = tk.Label(card.body, text=msg, bg=T.ERR_SOFT, fg=T.ERR,
                       font=T.font(10), justify="left", anchor="w",
                       wraplength=720)
        lab.pack(fill="x")
        wrap_to(card, lab, reserve=80)
        self._chat.to_bottom()

    def _result_card(self, parsed, truncated, allow_iterate=True):
        prompt = parsed.get("prompt") or ""
        raw = parsed.get("raw") or ""

        card = RoundCard(self._chat.inner, bg=T.CARD, border=T.BORDER,
                         paddingx=18, paddingy=16, parent_bg=T.BG)
        card.pack(fill="x", pady=(0, 12))

        head = tk.Frame(card.body, bg=T.CARD)
        head.pack(fill="x")
        tk.Label(head, text="生成结果", bg=T.CARD, fg=T.TEXT,
                 font=T.font(11, True)).pack(side="left")
        if truncated:
            tk.Label(head, text="可能被截断", bg=T.ERR_SOFT, fg=T.ERR,
                     font=T.font(8), padx=6, pady=1).pack(side="left",
                                                           padx=(8, 0))

        if prompt:
            self._prompt_block(card.body, prompt)
            rest = raw.replace(prompt, "").strip()
            if rest:
                self._fold_text(card.body, "查看完整回复", rest)
        else:
            tk.Label(card.body, text="模型没有按格式回答，下面是原文：",
                     bg=T.CARD, fg=T.WARN, font=T.font(9),
                     anchor="w").pack(fill="x", pady=(8, 4))
            self._fold_text(card.body, "", raw, open_by_default=True)

        # allow_iterate 保留调用兼容性；修改请求统一走底部输入框。
        self._chat.to_bottom()

    def _prompt_block(self, parent, text):
        box = tk.Frame(parent, bg="#F7F8FA", highlightthickness=1,
                       highlightbackground=T.BORDER)
        box.pack(fill="x", pady=(10, 0))

        bar = tk.Frame(box, bg="#F7F8FA")
        bar.pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(bar, text="提示词 · %d 字" % len(text), bg="#F7F8FA",
                 fg=T.TEXT_SUB, font=T.font(9, True)).pack(side="left")

        def copy():
            self.clipboard_clear()
            self.clipboard_append(text)
            btn.set_text("已复制")
            self.after(1400, lambda: btn.set_text("复制"))

        btn = Button(bar, "复制", command=copy, kind="ghost", padx=10, pady=3,
                     size=9, radius=12, parent_bg="#F7F8FA")
        btn.pack(side="right", padx=(0, 10))
        Button(bar, "编辑", command=lambda: self._edit_prompt(text),
               kind="plain", padx=8, pady=3, size=9, radius=12,
               parent_bg="#F7F8FA").pack(side="right", padx=(0, 4))

        body = tk.Text(box, height=min(30, max(4, text.count("\n") + 1)),
                       relief="flat", bd=0, bg="#F7F8FA", fg=T.TEXT,
                       font=T.font(10), wrap="word", padx=12, pady=8,
                       highlightthickness=0)
        body.insert("1.0", text)
        body.configure(state="disabled")
        body.pack(fill="x", padx=2, pady=(4, 8))
        # 内容超出高度时用滚轮翻，别让用户以为被截断了
        body.bind("<MouseWheel>",
                  lambda e: (body.yview_scroll(int(-e.delta / 120), "units"),
                             "break")[1])

    def _edit_prompt(self, text):
        """把提示词塞回输入框，方便直接补一句「再简洁点」。"""
        self._placeholder_on = False
        self._input.delete("1.0", "end")
        self._input.configure(fg=T.TEXT)
        self._input.insert("1.0", text)
        self._input.focus_set()

    def _fold_text(self, parent, title, text, open_by_default=False):
        wrap = tk.Frame(parent, bg=T.CARD)
        wrap.pack(fill="x", pady=(10, 0))

        shown = {"v": open_by_default}
        content = tk.Frame(wrap, bg=T.CARD)

        def render():
            for w in content.winfo_children():
                w.destroy()
            t = tk.Text(content, height=min(22, max(3, text.count("\n") + 1)),
                        relief="flat", bd=0, bg=T.CARD, fg=T.TEXT_SUB,
                        font=T.font(10), wrap="word", padx=0, pady=4,
                        highlightthickness=0)
            render_markdown(t, text)
            t.pack(fill="x")

        if title:
            def toggle():
                shown["v"] = not shown["v"]
                if shown["v"]:
                    render()
                    content.pack(fill="x", pady=(6, 0))
                else:
                    content.pack_forget()

            b = Button(wrap, title, command=toggle, kind="plain", padx=8,
                       pady=4, size=9, radius=12, parent_bg=T.CARD)
            b.pack(anchor="w")
        else:
            shown["v"] = True

        if shown["v"]:
            render()
            content.pack(fill="x", pady=(6, 0))

    def _send_iterate(self, note):
        """兼容旧调用；和底部输入框共享轮次、上下文及忙碌检查。"""
        if self._busy or not note.strip():
            return
        conn = self._ready_conn()
        if conn is not None:
            self._submit_text(note.strip(), conn)

    # ============================================================ 提问卡

    def _ask_card(self, questions, raw):
        card = RoundCard(self._chat.inner, bg=T.CARD, border=T.BORDER,
                         paddingx=18, paddingy=16, parent_bg=T.BG)
        card.pack(fill="x", pady=(0, 12))

        head = tk.Frame(card.body, bg=T.CARD)
        head.pack(fill="x")
        head_lab = tk.Label(head, text="先确认几件事", bg=T.CARD, fg=T.TEXT,
                            font=T.font(11, True))
        head_lab.pack(side="left")
        tk.Label(head, text="第 %d / %d 轮" % (self._round, engine.MAX_ROUNDS),
                 bg=T.CARD, fg=T.MUTED, font=T.font(9)).pack(side="right")

        state = [self._question_block(card.body, q) for q in questions]

        actions = tk.Frame(card.body, bg=T.CARD)
        actions.pack(fill="x", pady=(16, 0))

        pending = {"card": card, "raw": raw, "done": False}
        self._pending_ask = pending

        def submit(skip=False):
            if pending["done"] or self._pending_ask is not pending or self._busy:
                return
            items = []
            if skip:
                answer = "不用再问了，直接给结果。"
            else:
                lines = []
                for st in state:
                    picked = [o["label"] for o, v in zip(st["opts"], st["vals"])
                              if v]
                    if st["custom"].get().strip() and st["vals"][-1]:
                        picked[-1] = st["custom"].get().strip()
                    items.append({"q": st["q"], "picked": picked})
                    if picked:
                        lines.append("- %s → %s" % (st["q"], "、".join(picked)))
                if not lines:
                    self._hint.configure(text="先选一下，或者点「就这些，开始吧」",
                                         fg=T.WARN)
                    return
                answer = "我选了：\n" + "\n".join(lines)

            conn = self._ready_conn()
            if conn is not None:
                self._submit_text(answer, conn,
                                  {"items": items, "skipped": skip})

        btn_skip = Button(actions, "就这些，开始吧", command=lambda: submit(True),
                          kind="ghost", padx=14, pady=7, radius=13)
        btn_skip.pack(side="left")
        btn_ok = Button(actions, "确认选择", command=lambda: submit(False),
                        kind="primary", padx=20, pady=7, radius=13)
        btn_ok.pack(side="right")

        self._chat.to_bottom()

    def _finish_ask(self, answer):
        pending = self._pending_ask
        if not pending:
            return
        pending["done"] = True
        self._pending_ask = None
        item = dict(answer, role="ask")
        self._log(item)
        body = pending["card"].body
        # 避免在被点击按钮自己的事件栈里销毁它。
        def collapse():
            if not body.winfo_exists():
                return
            for w in body.winfo_children():
                w.destroy()
            self._ask_summary(body, item)
        self.after_idle(collapse)

    def _ask_card_static(self, item):
        """恢复历史时，把已经答过的提问画成一张只读小结。"""
        card = RoundCard(self._chat.inner, bg=T.CARD, border=T.BORDER,
                         paddingx=18, paddingy=14, parent_bg=T.BG)
        card.pack(fill="x", pady=(0, 12))
        self._ask_summary(card.body, item)

    def _ask_summary(self, parent, item):
        tk.Label(parent,
                 text="跳过确认" if item.get("skipped") else "确认过的信息",
                 bg=T.CARD, fg=T.MUTED, font=T.font(9, True),
                 anchor="w").pack(fill="x")

        for it in item.get("items") or []:
            box = tk.Frame(parent, bg=T.CARD)
            box.pack(fill="x", pady=(7, 0))
            tk.Label(box, text=it.get("q") or "", bg=T.CARD, fg=T.TEXT,
                     font=T.font(10), anchor="w", justify="left",
                     wraplength=680).pack(fill="x")
            picked = it.get("picked") or []
            if picked:
                tk.Label(box, text="· " + "、".join(picked), bg=T.CARD,
                         fg=T.PRIMARY, font=T.font(9), anchor="w",
                         justify="left", wraplength=680).pack(fill="x",
                                                              pady=(2, 0))

    def _question_block(self, parent, q):
        box = tk.Frame(parent, bg=T.CARD)
        box.pack(fill="x", pady=(16, 0))

        title = tk.Frame(box, bg=T.CARD)
        title.pack(fill="x")
        qlab = tk.Label(title, text=q.get("q") or "", bg=T.CARD, fg=T.TEXT,
                        font=T.font(10, True), anchor="w", wraplength=700,
                        justify="left")
        qlab.pack(side="left")
        wrap_to(box, qlab, reserve=60)
        if q.get("type") == "multi":
            tk.Label(title, text="可多选", bg=T.PRIMARY_SOFT, fg=T.PRIMARY,
                     font=T.font(8), padx=6, pady=1).pack(side="left",
                                                           padx=(8, 0))

        opts = list(q.get("opts") or [])
        if not any("其他" in (o.get("label") or "") for o in opts):
            opts.append({"label": "其他（自己写）", "desc": "", "rec": False})

        vals = [False] * len(opts)
        rows = []
        custom_var = tk.StringVar()

        holder = tk.Frame(box, bg=T.CARD)
        holder.pack(fill="x", pady=(8, 0))

        custom_entry = None

        def repaint():
            for i, r in enumerate(rows):
                r.set_selected(vals[i])

        def choose(idx):
            if q.get("type") == "multi":
                vals[idx] = not vals[idx]
            else:
                for i in range(len(vals)):
                    vals[i] = (i == idx)
            repaint()
            if custom_entry is not None:
                if vals[-1]:
                    custom_entry.pack(fill="x", padx=26, pady=(2, 0))
                    custom_entry.focus_set()
                else:
                    custom_entry.pack_forget()

        for i, o in enumerate(opts):
            row = _OptionRow(holder, o.get("label") or "",
                             o.get("desc") or "", o.get("rec", False),
                             command=lambda i=i: choose(i))
            row.pack(fill="x", pady=1)
            rows.append(row)

        custom_entry = tk.Entry(holder, textvariable=custom_var, relief="flat",
                                bd=0, bg="#F7F8FA", fg=T.TEXT,
                                insertbackground=T.TEXT, font=T.font(10),
                                highlightthickness=1,
                                highlightbackground=T.BORDER_STRONG,
                                highlightcolor=T.PRIMARY)
        custom_entry.pack_forget()

        return {"q": q.get("q") or "", "opts": opts, "vals": vals,
                "custom": custom_var}


# ------------------------------------------------------------------ 选项行


class _OptionRow(tk.Frame):
    """一行选项：圆圈 + 文字 + 推荐标记。整行可点，圆点和文字永远对齐。"""

    def __init__(self, master, label, desc, rec, command=None):
        super().__init__(master, bg=T.CARD, cursor="hand2")
        self._command = command
        self._selected = False
        self._rec = rec

        self._mark = tk.Canvas(self, width=18, height=18, bg=T.CARD,
                               highlightthickness=0, bd=0, cursor="hand2")
        self._mark.pack(side="left", pady=4)

        text_box = tk.Frame(self, bg=T.CARD)
        text_box.pack(side="left", fill="x", expand=True, padx=(6, 0))

        line = tk.Frame(text_box, bg=T.CARD)
        line.pack(anchor="w")

        self._text = tk.Label(line, text=label, bg=T.CARD, fg=T.TEXT,
                              font=T.font(10), anchor="w", justify="left",
                              wraplength=620, cursor="hand2")
        self._text.pack(side="left")
        wrap_to(self, self._text, reserve=130)

        if rec:
            self._badge = tk.Label(line, text="★ 推荐", bg=T.PRIMARY_SOFT,
                                   fg=T.PRIMARY, font=T.font(8),
                                   padx=6, pady=1, cursor="hand2")
            self._badge.pack(side="left", padx=(8, 0), pady=(2, 0))

        if desc:
            self._desc = tk.Label(text_box, text=desc, bg=T.CARD, fg=T.MUTED,
                                  font=T.font(9), anchor="w", justify="left",
                                  wraplength=620, cursor="hand2")
            self._desc.pack(anchor="w")
            wrap_to(self, self._desc, reserve=130)

        for w in _walk(self):
            w.bind("<Button-1>", self._on_click)
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)

        self._paint()

    def _on_click(self, _=None):
        if self._command:
            self._command()

    def _on_enter(self, _=None):
        if not self._selected:
            self._paint_bg("#F7F9FC")

    def _on_leave(self, _=None):
        if not self._selected:
            self._paint_bg(T.CARD)

    def _paint_bg(self, color):
        badge = getattr(self, "_badge", None)
        self.configure(bg=color)
        for w in _walk(self):
            if w is badge:
                continue
            try:
                if isinstance(w, (tk.Frame, tk.Label)):
                    w.configure(bg=color)
            except tk.TclError:
                pass

    def set_selected(self, on: bool):
        self._selected = bool(on)
        self._paint()

    def _paint(self):
        self._mark.delete("all")
        if self._selected:
            self._mark.create_oval(2, 2, 16, 16, fill=T.PRIMARY, outline="")
            self._mark.create_oval(6, 6, 12, 12, fill="#FFFFFF", outline="")
        else:
            self._mark.create_oval(2, 2, 16, 16, outline=T.BORDER_STRONG,
                                   width=1.5)
        self._text.configure(fg=T.TEXT)
        self.configure(bg=T.CARD)


def _walk(widget):
    out = [widget]
    for c in widget.winfo_children():
        out.extend(_walk(c))
    return out


def _leave_card(card, normal=None):
    """鼠标真正离开整张卡时才取消高亮。

    卡片里有多行文字，鼠标从一行挪到另一行会先触发 Leave，
    直接复原边框就会闪一下。按指针位置判断最省事。
    """
    try:
        x, y = card.winfo_pointerxy()
        inside = (card.winfo_rootx() <= x < card.winfo_rootx() + card.winfo_width()
                  and card.winfo_rooty() <= y < card.winfo_rooty() + card.winfo_height())
        if not inside:
            card.set_border(normal or T.BORDER)
    except tk.TclError:
        pass
