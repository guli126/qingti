"""提示词编辑器。

左边选模板，右边直接改，保存即生效。底层就是 prompts/*.md，
用记事本改也一样，这里只是给个不用离开软件的入口。
"""

import os
import tkinter as tk
from tkinter import messagebox

from core import templates

from . import theme as T
from .widgets import Button, ScrollFrame, hline

GROUP_ORDER = [("coding", "编程"), ("work", "办公"), ("image", "图像"),
               ("extra", "通用")]


class EditorWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("提示词 · 轻提")
        self.configure(bg=T.BG)
        self.geometry("1120x760")
        self.minsize(840, 580)
        self.transient(master)

        self._current = None        # 当前模板 id
        self._dirty = False
        self._items = []
        self._btn_map = {}

        self._build()
        self._load(self._items[0]["id"] if self._items else None)
        self._center(master)

    # ------------------------------------------------------------ 布局

    def _build(self):
        # 顶栏
        head = tk.Frame(self, bg=T.BG)
        head.pack(fill="x", padx=20, pady=(16, 0))
        tk.Label(head, text="提示词", bg=T.BG, fg=T.TEXT,
                 font=T.font(15, True)).pack(side="left")
        tk.Label(head, text="改完点保存，下一次对话立刻按新版走",
                 bg=T.BG, fg=T.MUTED, font=T.font(9)).pack(side="left",
                                                            padx=(12, 0),
                                                            pady=(4, 0))
        self._title = tk.Label(head, text="", bg=T.BG, fg=T.PRIMARY,
                               font=T.font(10, True))
        self._title.pack(side="right")
        hline(self, pady=(12, 0))

        body = tk.Frame(self, bg=T.BG)
        body.pack(fill="both", expand=True)

        # 左：模板列表
        left = tk.Frame(body, bg=T.BG, width=210)
        left.pack(side="left", fill="y", padx=(20, 0), pady=(12, 0))
        left.pack_propagate(False)
        self._nav = ScrollFrame(left, bg=T.BG)
        self._nav.pack(fill="both", expand=True)

        # 右：编辑区
        right = tk.Frame(body, bg=T.BG)
        right.pack(side="left", fill="both", expand=True,
                   padx=(16, 20), pady=(12, 0))

        holder = tk.Frame(right, bg=T.CARD, highlightthickness=1,
                          highlightbackground=T.BORDER)
        holder.pack(fill="both", expand=True)
        self._text = tk.Text(holder, relief="flat", bd=0, bg=T.CARD, fg=T.TEXT,
                             insertbackground=T.TEXT, font=T.font(10),
                             wrap="word", padx=16, pady=14,
                             spacing1=2, spacing3=3,
                             highlightthickness=0)
        vsb = tk.Scrollbar(holder, orient="vertical", command=self._text.yview,
                           width=10, relief="flat", bd=0,
                           bg=T.BG, troughcolor=T.BG,
                           activebackground=T.BORDER_STRONG)
        self._text.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._text.pack(side="left", fill="both", expand=True)
        self._text.bind("<<Modified>>", self._on_modified)
        self._text.bind("<Control-s>", lambda e: (self._save(), "break")[1])

        # 底栏
        bar = tk.Frame(self, bg=T.BG)
        bar.pack(fill="x", padx=20, pady=14)
        self._status = tk.Label(bar, text="", bg=T.BG, fg=T.MUTED,
                                font=T.font(9))
        self._status.pack(side="left")
        Button(bar, "保存", command=self._save, kind="primary",
               padx=22, pady=7).pack(side="right")
        Button(bar, "恢复默认", command=self._reset, kind="ghost",
               padx=16, pady=7).pack(side="right", padx=(0, 10))

        self._fill_nav()

    def _fill_nav(self):
        self._items = templates.list_templates()
        for w in self._nav.inner.winfo_children():
            w.destroy()
        self._btn_map = {}

        groups = {}
        for it in self._items:
            groups.setdefault(it.get("scene") or "", []).append(it)

        for key, label in GROUP_ORDER:
            items = groups.get(key) or []
            if not items:
                continue
            tk.Label(self._nav.inner, text=label, bg=T.BG, fg=T.MUTED,
                     font=T.font(9, True), anchor="w").pack(
                fill="x", pady=(10, 4), padx=6)
            for it in items:
                self._nav_item(it)

    def _nav_item(self, it: dict):
        name = it["name"]
        if it.get("edited"):
            name += "  ·"
        b = Button(self._nav.inner, name, kind="plain", padx=10, pady=6,
                   width=178, parent_bg=T.BG, align="left")
        b.pack(fill="x", pady=1)
        b.bind("<Button-1>", lambda e, i=it["id"]: self._load(i), add="+")
        self._btn_map[it["id"]] = b

    # ------------------------------------------------------------ 交互

    def _on_modified(self, _=None):
        if self._text.edit_modified():
            self._dirty = True
            self._text.edit_modified(False)
            self._mark_dirty()

    def _mark_dirty(self):
        self._title.configure(text="未保存的修改", fg=T.WARN)

    def _load(self, tid, force=False):
        if not tid:
            return
        if self._dirty and not force:
            if not messagebox.askyesno(
                    "放弃修改？", "当前模板还没保存，切换会丢掉改动。", parent=self):
                return
        got = templates.load_template(tid)
        if not got:
            self._status.configure(text="读不到这个模板：%s" % tid, fg=T.ERR)
            return
        meta, body = got
        self._current = tid
        self._text.delete("1.0", "end")
        self._text.insert("1.0", body)
        self._text.edit_modified(False)
        self._dirty = False

        self._status.configure(text="%s · %d 字" % (meta.get("name") or tid,
                                                    len(body)), fg=T.MUTED)
        self._title.configure(text="")
        self._highlight(tid)

    def _highlight(self, tid):
        for k, b in self._btn_map.items():
            b.set_kind("soft" if k == tid else "plain")

    def _save(self):
        if not self._current:
            return
        content = self._header_for(self._current) + self._text.get("1.0", "end-1c")
        if not templates.save_template(self._current, content):
            self._status.configure(text="保存失败，检查文件是否被占用", fg=T.ERR)
            return
        self._dirty = False
        self._title.configure(text="已保存", fg=T.OK)
        self._status.configure(text="已保存，下一次对话生效", fg=T.OK)
        self._fill_nav()
        self._highlight(self._current)

    def _header_for(self, tid: str) -> str:
        """取回原文件的 front-matter。

        编辑区只显示正文，元信息（id/name/scene）不让人误改，
        否则模板会从列表里消失。保存时把它们原样拼回去。
        """
        for it in self._items:
            if it["id"] != tid:
                continue
            try:
                with open(os.path.join(templates.PROMPT_DIR, it["file"]),
                          "r", encoding="utf-8") as f:
                    raw = f.read()
            except OSError:
                return ""
            if not raw.startswith("---"):
                return ""
            end = raw.find("\n---", 3)
            if end == -1:
                return ""
            return raw[:end + 4] + "\n"
        return ""

    def _reset(self):
        if not self._current:
            return
        if not messagebox.askyesno(
                "恢复默认",
                "用出厂版本覆盖当前模板？你的改动会丢失。", parent=self):
            return
        if not templates.reset_template(self._current):
            self._status.configure(text="没有找到出厂版本", fg=T.ERR)
            return
        self._dirty = False
        self._load(self._current, force=True)
        self._status.configure(text="已恢复出厂版本", fg=T.OK)
        self._fill_nav()
        self._highlight(self._current)

    def _center(self, master):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = master.winfo_rootx() + (master.winfo_width() - w) // 2
        y = master.winfo_rooty() + (master.winfo_height() - h) // 3
        self.geometry("+%d+%d" % (max(0, x), max(0, y)))
