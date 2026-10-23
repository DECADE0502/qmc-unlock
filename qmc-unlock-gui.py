#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qmc-unlock GUI —— QQ 音乐加密音频（mflac/mgg/qmc*）离线解锁工具

• 拖拽 / 选择文件，列表一眼看清格式、大小、song_mid、key 状态
• 一键抓 key（从本机 QQ 音乐客户端内存）→ 全离线解密
• 解完可无损重封装，得到全片 0 错误的干净 FLAC

双击 qmc-unlock-GUI.bat / qmc-unlock.exe 启动。
"""

import os
import sys
import json
import time
import queue
import threading
import traceback
from pathlib import Path

# ── 高分屏适配 ──────────────────────────────────────────────
try:
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, font as tkfont

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


# ── 冻结(exe) 时的资源目录 ─────────────────────────────────
def res_dir():
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", APP_DIR))
    return APP_DIR


try:
    import qmc_unlock as core
except Exception as e:
    r = tk.Tk()
    r.withdraw()
    messagebox.showerror("启动失败", f"缺少 qmc_unlock.py（需与本程序同目录）\n\n{e}")
    raise SystemExit(1)

FAMILY = "Microsoft YaHei UI"
F_XXL = (FAMILY, 16, "bold")
F_XL = (FAMILY, 11, "bold")
F_L = (FAMILY, 10)
F_M = (FAMILY, 9)
F_S = (FAMILY, 9)
F_MONO = ("Consolas", 9)

# ── 配色 ───────────────────────────────────────────────────
C = {
    "bg": "#f3f4f9",
    "card": "#ffffff",
    "border": "#e5e7f0",
    "border_hot": "#5b5bd6",
    "text": "#1e2233",
    "sub": "#6b7280",
    "faint": "#9aa0b0",
    "primary": "#5b5bd6",
    "primary_h": "#4b4bc9",
    "primary_p": "#3f3fb5",
    "primary_soft": "#eef0ff",
    "ghost_h": "#eceefa",
    "ok": "#0f7b55",
    "ok_bg": "#e7f7f0",
    "err": "#c62828",
    "err_bg": "#fdecec",
    "warn": "#a86400",
    "warn_bg": "#fff5e5",
    "row_alt": "#fafbfe",
    "row_sel": "#e9ebff",
    "log_bg": "#14161b",
    "log_fg": "#d5d8e0",
    "log_dim": "#7b8191",
    "log_ok": "#5ddc9a",
    "log_err": "#ff8b84",
    "log_warn": "#ffd479",
}

SUPPORTED = sorted(core.SUPPORTED_EXTS)

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _DND = True
except Exception:
    _DND = False

CFG_PATH = core.CACHE_DIR / "gui.json"


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return (f"{n:.0f} B" if u == "B" else f"{n:.1f} {u}")
        n /= 1024.0


def round_rect(cv, x1, y1, x2, y2, r, **kw):
    r = max(1, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return cv.create_polygon(pts, smooth=True, splinesteps=14, **kw)


def load_cfg():
    try:
        return json.loads(CFG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cfg(d):
    try:
        CFG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CFG_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════
#  自绘控件
# ══════════════════════════════════════════════════════════
class Card(tk.Frame):
    """卡片容器（细边框 + 内边距），内容放进 .body"""

    def __init__(self, master, radius=14, pad=14, bg=None, border=None, parent_bg=None):
        self._bg = bg or C["card"]
        self._bd = border or C["border"]
        self._pad = pad
        super().__init__(master, bg=self._bg, bd=0,
                         highlightthickness=1, highlightbackground=self._bd,
                         highlightcolor=self._bd)
        self.body = tk.Frame(self, bg=self._bg)
        self.body.pack(fill="both", expand=True, padx=pad, pady=pad)

    def set_border(self, color):
        self._bd = color
        try:
            self.configure(highlightbackground=color, highlightcolor=color)
        except Exception:
            pass


class Pill(tk.Canvas):
    """圆角按钮：kind = primary | secondary | ghost | danger"""

    STYLES = {
        "primary": (C["primary"], "#ffffff", C["primary_h"], C["primary_p"]),
        "secondary": ("#ffffff", C["text"], C["ghost_h"], C["primary_soft"]),
        "ghost": (C["bg"], C["sub"], C["ghost_h"], C["primary_soft"]),
        "danger": ("#ffffff", C["err"], C["err_bg"], "#fbdcdc"),
    }

    def __init__(self, master, text, command=None, kind="secondary", h=34, padx=18,
                 icon="", parent_bg=None, min_w=0):
        self._pb = parent_bg or C["bg"]
        self.kind = kind
        self.text = text
        self.icon = icon
        self.command = command
        self._ch = h
        self._padx = padx
        self._enabled = True
        self._hover = False
        f = tkfont.Font(font=F_M)
        label = (icon + " " if icon else "") + text
        w = max(min_w, f.measure(label) + padx * 2)
        super().__init__(master, width=w, height=h, bg=self._pb,
                         highlightthickness=0, bd=0, takefocus=0)
        self._cw = w
        self._label = label
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<Button-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Configure>", lambda e: self._draw())
        self._draw()

    # 兼容 ttk 的 state 调用
    def state(self, spec=None):
        if spec:
            s = spec[0] if isinstance(spec, (list, tuple)) else spec
            self._enabled = not s.startswith("disabled")
        else:
            return [] if self._enabled else ["disabled"]
        self._draw()

    def _draw(self):
        self.delete("all")
        fill, fg, hover, active = self.STYLES[self.kind]
        bg = hover if self._hover and self._enabled else fill
        if not self._enabled:
            bg, fg = C["border"], C["faint"]
        round_rect(self, 1, 1, self._cw - 1, self._ch - 1, self._ch / 2,
                   fill=bg, outline=bg)
        self.create_text(self._cw / 2, self._ch / 2, text=self._label,
                         fill=fg, font=F_M)

    def _enter(self, _=None):
        self._hover = True
        if self._enabled:
            self.configure(cursor="hand2")
        self._draw()

    def _leave(self, _=None):
        self._hover = False
        self.configure(cursor="")
        self._draw()

    def _press(self, _=None):
        if self._enabled:
            self._draw()

    def _release(self, _=None):
        if self._enabled and self.command:
            self.command()


class SmoothBar(tk.Canvas):
    """圆角进度条，数值平滑过渡"""

    def __init__(self, master, width=300, height=8, parent_bg=None):
        self._pb = parent_bg or C["bg"]
        super().__init__(master, width=width, height=height, bg=self._pb,
                         highlightthickness=0, bd=0, takefocus=0)
        self._cw, self._ch = width, height
        self._cur = 0.0
        self._target = 0.0
        self._animating = False
        self.bind("<Configure>", self._on_conf)
        self._draw()

    def _on_conf(self, e):
        self._cw, self._ch = e.width, e.height
        self._draw()

    def set(self, cur, total):
        self._target = 0.0 if not total else max(0.0, min(1.0, cur / total))
        if not self._animating:
            self._animating = True
            self.after(12, self._tick)

    def reset(self):
        self._cur = self._target = 0.0
        self._draw()

    def _tick(self):
        d = self._target - self._cur
        if abs(d) < 0.004:
            self._cur = self._target
            self._draw()
            self._animating = False
            return
        self._cur += d * 0.28
        self._draw()
        self.after(12, self._tick)

    def _draw(self):
        self.delete("all")
        h = max(4, self._ch)
        r = h / 2
        round_rect(self, 0, 0, self._cw, h, r, fill="#e3e6f0", outline="#e3e6f0")
        if self._cur > 0.001:
            fw = max(h, self._cw * self._cur)
            round_rect(self, 0, 0, fw, h, r, fill=C["primary"], outline=C["primary"])


class Badge(tk.Canvas):
    """状态胶囊"""

    def __init__(self, master, text, fg=C["sub"], bg=C["bg"], parent_bg=None, h=22):
        self._pb = parent_bg or C["bg"]
        f = tkfont.Font(font=F_S)
        w = f.measure(text) + 20
        super().__init__(master, width=w, height=h, bg=self._pb, highlightthickness=0, bd=0)
        self._cw, self._ch = w, h
        round_rect(self, 0, 0, w, h, h / 2, fill=bg, outline=bg)
        self.create_text(w / 2, h / 2, text=text, fill=fg, font=F_S)


# ══════════════════════════════════════════════════════════
#  主程序
# ══════════════════════════════════════════════════════════
class App:
    def __init__(self, root):
        self.root = root
        self.items = {}
        self.q = queue.Queue()
        self.busy = False
        self.stop_flag = False
        self.filter_text = ""
        self.filter_status = "全部"
        self.cfg = load_cfg()
        self._last_geom = None

        self._style()
        self._build()
        self._bind_keys()
        self.root.after(60, self._drain)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.log(f"qmc-unlock  v{core.VERSION}   ·   {len(SUPPORTED)} 种加密格式")
        self.log("提示：把文件或文件夹拖进窗口即可添加" if _DND else
                 "提示：用「添加文件 / 添加文件夹」，装 tkinterdnd2 后可拖拽")
        self._refresh_qqmusic_badge()

    # ── 样式 ──────────────────────────────────────────────
    def _style(self):
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure(".", background=C["bg"], font=F_M)
        st.configure("M.Card.TFrame", background=C["card"])
        st.configure("M.TFrame", background=C["bg"])
        st.configure("M.TLabel", background=C["card"], foreground=C["text"], font=F_M)
        st.configure("MSub.TLabel", background=C["card"], foreground=C["sub"], font=F_S)
        st.configure("MHead.TLabel", background=C["card"], foreground=C["faint"], font=F_S)

        # 列表
        st.configure("M.Treeview",
                     background=C["card"], fieldbackground=C["card"],
                     foreground=C["text"], font=F_M, rowheight=32, borderwidth=0)
        st.map("M.Treeview",
               background=[("selected", C["row_sel"])],
               foreground=[("selected", C["text"])])
        st.configure("M.Treeview.Heading",
                     background=C["card"], foreground=C["sub"], font=F_S,
                     relief="flat", borderwidth=0, padding=(8, 8))
        st.map("M.Treeview.Heading", background=[("active", C["card"])])

        # 输入框
        st.configure("M.TEntry",
                     fieldbackground="#f7f8fc", background="#f7f8fc",
                     foreground=C["text"], borderwidth=0, relief="flat",
                     insertcolor=C["text"], padding=(10, 7))
        st.map("M.TEntry", fieldbackground=[("focus", "#ffffff")])

        # 细滚动条
        st.configure("M.Vertical.TScrollbar",
                     background="#dfe2ec", troughcolor=C["card"],
                     borderwidth=0, arrowsize=0, width=10)
        st.map("M.Vertical.TScrollbar", background=[("active", "#c9cdda")])

        st.configure("M.TCheckbutton", background=C["card"], foreground=C["text"], font=F_M)
        st.map("M.TCheckbutton", background=[("active", C["card"])])

    # ── 布局 ──────────────────────────────────────────────
    def _build(self):
        r = self.root
        r.title(f"qmc-unlock  ·  QQ 音乐加密音频解锁  v{core.VERSION}")
        geo = self.cfg.get("geometry", "1180x830")
        r.geometry(geo)
        r.minsize(1000, 680)
        r.configure(bg=C["bg"])

        root_frame = tk.Frame(r, bg=C["bg"])
        root_frame.pack(fill="both", expand=True, padx=18, pady=(14, 14))
        root_frame.columnconfigure(0, weight=1)
        root_frame.rowconfigure(3, weight=3)
        root_frame.rowconfigure(6, weight=2)

        # ① 头部
        head = tk.Frame(root_frame, bg=C["bg"])
        head.grid(row=0, column=0, sticky="ew", pady=(0, 12))

        brand = tk.Frame(head, bg=C["bg"])
        brand.pack(side="left")
        logo = tk.Canvas(brand, width=38, height=38, bg=C["bg"], highlightthickness=0)
        logo.pack(side="left", padx=(0, 10))
        round_rect(logo, 2, 2, 36, 36, 11, fill=C["primary"], outline=C["primary"])
        logo.create_text(19, 20, text="♪", fill="#ffffff", font=(FAMILY, 17, "bold"))

        tt = tk.Frame(brand, bg=C["bg"])
        tt.pack(side="left")
        tk.Label(tt, text="QQ 音乐加密音频解锁", bg=C["bg"], fg=C["text"], font=F_XXL).pack(anchor="w")
        tk.Label(tt, text="mflac · mgg · qmc*   →   flac / ogg / mp3",
                 bg=C["bg"], fg=C["sub"], font=F_S).pack(anchor="w")

        tools = tk.Frame(head, bg=C["bg"])
        tools.pack(side="right")
        Pill(tools, "添加文件", self.add_files, "primary", icon="＋",
             parent_bg=C["bg"]).pack(side="left", padx=4)
        Pill(tools, "添加文件夹", self.add_folder, "secondary", parent_bg=C["bg"]).pack(side="left", padx=4)
        Pill(tools, "移除", self.remove_sel, "ghost", parent_bg=C["bg"]).pack(side="left", padx=4)
        Pill(tools, "清空", self.clear_all, "ghost", parent_bg=C["bg"]).pack(side="left", padx=4)

        # ② 工具条（搜索 + 状态筛选 + 计数）
        bar = tk.Frame(root_frame, bg=C["bg"])
        bar.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        search_wrap = tk.Frame(bar, bg=C["card"], highlightthickness=1,
                               highlightbackground=C["border"], highlightcolor=C["primary"])
        search_wrap.pack(side="left")
        tk.Label(search_wrap, text="搜索", bg=C["card"], fg=C["faint"],
                 font=F_S).pack(side="left", padx=(10, 0), pady=4)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._apply_filter())
        ent = tk.Entry(search_wrap, textvariable=self.search_var, font=F_M, bd=0,
                       bg=C["card"], fg=C["text"], insertbackground=C["text"], width=26)
        ent.pack(side="left", padx=(6, 10), pady=6)
        ent.bind("<FocusIn>", lambda e: search_wrap.configure(highlightbackground=C["primary"]))
        ent.bind("<FocusOut>", lambda e: search_wrap.configure(highlightbackground=C["border"]))

        self.filter_pills = {}
        chips = tk.Frame(bar, bg=C["bg"])
        chips.pack(side="left", padx=(14, 0))
        for name in ("全部", "缺 key", "已完成"):
            p = Pill(chips, name, lambda n=name: self._set_filter(n), "ghost",
                     h=28, padx=12, parent_bg=C["bg"])
            p.pack(side="left", padx=3)
            self.filter_pills[name] = p
        self._paint_filter()

        self.count_lbl = tk.Label(bar, text="", bg=C["bg"], fg=C["sub"], font=F_S)
        self.count_lbl.pack(side="right", padx=(0, 2))

        # ③ 列表卡片
        list_card = Card(root_frame, radius=14, pad=12)
        list_card.grid(row=3, column=0, sticky="nsew", pady=(0, 10))
        self.list_card = list_card

        lc = tk.Frame(list_card.body, bg=C["card"])
        lc.pack(fill="both", expand=True)

        cols = ("sel", "name", "fmt", "size", "mid", "key", "status")
        heads = {"sel": "", "name": "文件名", "fmt": "格式", "size": "大小",
                 "mid": "song_mid", "key": "key", "status": "状态"}
        widths = {"sel": 44, "name": 430, "fmt": 92, "size": 96, "mid": 158, "key": 96, "status": 132}
        self.tree = ttk.Treeview(lc, columns=cols, show="headings",
                                 style="M.Treeview", selectmode="extended")
        for c in cols:
            self.tree.heading(c, text=heads[c], anchor="w" if c in ("name", "mid") else "center",
                              command=lambda c=c: self.sort_by(c))
            self.tree.column(c, width=widths[c], minwidth=widths[c] if c != "name" else 140,
                             anchor="w" if c in ("name", "mid") else "center",
                             stretch=(c == "name"))
        vsb = ttk.Scrollbar(lc, orient="vertical", command=self.tree.yview,
                            style="M.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y", padx=(6, 0))

        self.tree.tag_configure("odd", background=C["row_alt"])
        self.tree.tag_configure("done", foreground=C["ok"])
        self.tree.tag_configure("fail", foreground=C["err"])
        self.tree.tag_configure("miss", foreground=C["warn"])
        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<Double-1>", self._on_double)
        self.tree.bind("<Button-3>", self._on_right)
        self.tree.bind("<space>", lambda e: self.toggle_sel())
        self.tree.bind("<Delete>", lambda e: self.remove_sel())

        self.empty_lbl = tk.Label(lc, text="把 .mflac / .mgg 文件拖到这里　·　或点右上角「添加文件」",
                                  bg=C["card"], fg=C["faint"], font=F_L)
        self.empty_lbl.place(relx=0.5, rely=0.45, anchor="center")

        self.menu = tk.Menu(self.root, tearoff=0, font=F_M,
                            bg=C["card"], fg=C["text"], activebackground=C["row_sel"],
                            activeforeground=C["text"], bd=0)
        self.menu.add_command(label="打开文件所在位置", command=self.open_sel_dir)
        self.menu.add_command(label="复制文件路径", command=self.copy_sel_path)
        self.menu.add_separator()
        self.menu.add_command(label="仅解密选中的这些", command=self.start)
        self.menu.add_command(label="从列表中移除", command=self.remove_sel)

        # ④ 设置卡片
        set_card = Card(root_frame, radius=14, pad=12)
        set_card.grid(row=4, column=0, sticky="ew", pady=(0, 10))
        s = set_card.body

        row_out = tk.Frame(s, bg=C["card"])
        row_out.pack(fill="x")
        tk.Label(row_out, text="输出目录", bg=C["card"], fg=C["sub"], font=F_S,
                 width=8, anchor="w").pack(side="left")
        self.out_var = tk.StringVar(value=self.cfg.get("out_dir", ""))
        out_entry_wrap = tk.Frame(row_out, bg="#f7f8fc", highlightthickness=1,
                                  highlightbackground=C["border"], highlightcolor=C["primary"])
        out_entry_wrap.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ent2 = tk.Entry(out_entry_wrap, textvariable=self.out_var, font=F_M, bd=0,
                        bg="#f7f8fc", fg=C["text"], insertbackground=C["text"])
        ent2.pack(fill="x", padx=10, pady=6)
        ent2.bind("<FocusIn>", lambda e: out_entry_wrap.configure(highlightbackground=C["primary"]))
        ent2.bind("<FocusOut>", lambda e: out_entry_wrap.configure(highlightbackground=C["border"]))
        Pill(row_out, "浏览", self.pick_out, "secondary", h=30, padx=14, parent_bg=C["card"]).pack(side="left", padx=3)
        Pill(row_out, "打开", self.open_out, "ghost", h=30, padx=14, parent_bg=C["card"]).pack(side="left", padx=3)

        row_opt = tk.Frame(s, bg=C["card"])
        row_opt.pack(fill="x", pady=(10, 0))
        self.auto_client = tk.BooleanVar(value=self.cfg.get("auto_client", True))
        self.trim = tk.BooleanVar(value=self.cfg.get("trim", True))
        self.overwrite = tk.BooleanVar(value=self.cfg.get("overwrite", False))
        for text, var in (
            ("缺 key 时自动从 QQ 音乐抓取", self.auto_client),
            ("解密后修尾（无损，全片 0 错误）", self.trim),
            ("覆盖已有文件", self.overwrite),
        ):
            tk.Checkbutton(row_opt, text=text, variable=var,
                           bg=C["card"], fg=C["text"], font=F_M,
                           activebackground=C["card"], activeforeground=C["text"],
                           selectcolor=C["card"], bd=0, highlightthickness=0,
                           offrelief="flat", cursor="hand2"
                           ).pack(side="left", padx=(0, 24))

        # ⑤ 动作条
        act = tk.Frame(root_frame, bg=C["bg"])
        act.grid(row=5, column=0, sticky="ew", pady=(0, 10))

        left = tk.Frame(act, bg=C["bg"])
        left.pack(side="left")
        Pill(left, "全选", lambda: self.set_all(True), "ghost", h=32, padx=14,
             parent_bg=C["bg"]).pack(side="left", padx=3)
        Pill(left, "全不选", lambda: self.set_all(False), "ghost", h=32, padx=14,
             parent_bg=C["bg"]).pack(side="left", padx=3)
        Pill(left, "反选", self.invert_sel, "ghost", h=32, padx=14,
             parent_bg=C["bg"]).pack(side="left", padx=3)
        Pill(left, "刷新 key", self.refresh_keys, "ghost", h=32, padx=14,
             parent_bg=C["bg"]).pack(side="left", padx=3)

        right = tk.Frame(act, bg=C["bg"])
        right.pack(side="right")
        self.btn_go = Pill(right, "开始解密", self.start, "primary", h=42, padx=30, icon="▶",
                           parent_bg=C["bg"])
        self.btn_go.pack(side="right", padx=(8, 0))
        self.btn_stop = Pill(right, "停止", self.stop, "danger", h=42, padx=18,
                             parent_bg=C["bg"])
        self.btn_stop.pack(side="right")
        self.btn_stop.state(["disabled"])
        self.btn_grab = Pill(right, "抓取缺失 key", self.grab_keys, "secondary", h=42, padx=20,
                             parent_bg=C["bg"])
        self.btn_grab.pack(side="right", padx=8)

        # ⑥ 进度 + 日志卡片
        log_card = Card(root_frame, radius=14, pad=12)
        log_card.grid(row=6, column=0, sticky="nsew")
        lw = log_card.body

        prow = tk.Frame(lw, bg=C["card"])
        prow.pack(fill="x", pady=(0, 8))
        tk.Label(prow, text="进度", bg=C["card"], fg=C["sub"], font=F_S).pack(side="left")
        self.prog_lbl = tk.Label(prow, text="就绪", bg=C["card"], fg=C["sub"], font=F_S)
        self.prog_lbl.pack(side="right")
        self.bar = SmoothBar(prow, width=420, height=10, parent_bg=C["card"])
        self.bar.pack(side="left", fill="x", expand=True, padx=12, pady=(1, 0))

        logbox_wrap = tk.Frame(lw, bg=C["log_bg"], highlightthickness=0)
        logbox_wrap.pack(fill="both", expand=True)
        self.logbox = tk.Text(logbox_wrap, height=7, font=F_MONO, wrap="none",
                              bg=C["log_bg"], fg=C["log_fg"], insertbackground=C["log_fg"],
                              bd=0, relief="flat", padx=12, pady=8, spacing1=1, spacing3=1)
        lsb = ttk.Scrollbar(logbox_wrap, orient="vertical", command=self.logbox.yview,
                            style="M.Vertical.TScrollbar")
        self.logbox.configure(yscrollcommand=lsb.set)
        self.logbox.pack(side="left", fill="both", expand=True)
        lsb.pack(side="left", fill="y", padx=(4, 0))
        self.logbox.tag_configure("dim", foreground=C["log_dim"])
        self.logbox.tag_configure("ok", foreground=C["log_ok"])
        self.logbox.tag_configure("err", foreground=C["log_err"])
        self.logbox.tag_configure("warn", foreground=C["log_warn"])
        self.logbox.configure(state="disabled")

        # ⑦ 底部状态条
        foot = tk.Frame(root_frame, bg=C["bg"])
        foot.grid(row=7, column=0, sticky="ew", pady=(8, 0))
        self.qq_badge = tk.Label(foot, text="", bg=C["bg"], fg=C["sub"], font=F_S)
        self.qq_badge.pack(side="left")
        n_key = 0
        if core.EKEY_DIR.exists():
            n_key = len(list(core.EKEY_DIR.glob("*.txt"))) + len(list(core.EKEY_DIR.glob("*.key")))
        tk.Label(foot, text=f"已缓存 key：{n_key} 条    ·    缓存目录 {core.EKEY_DIR}",
                 bg=C["bg"], fg=C["faint"], font=F_S).pack(side="right")

        if _DND:
            for w in (self.tree, self.list_card, root_frame, self.root):
                try:
                    w.drop_target_register(DND_FILES)
                    w.dnd_bind("<<Drop>>", self._on_drop)
                except Exception:
                    pass
            try:
                self.list_card.dnd_bind("<<DropEnter>>", lambda e: self.list_card.set_border(C["border_hot"]))
                self.list_card.dnd_bind("<<DropLeave>>", lambda e: self.list_card.set_border(C["border"]))
            except Exception:
                pass

        self._update_count()

    def _bind_keys(self):
        r = self.root
        r.bind("<Control-o>", lambda e: self.add_files())
        r.bind("<Control-O>", lambda e: self.add_folder())
        r.bind("<Control-Return>", lambda e: self.start())
        r.bind("<Control-a>", lambda e: self.set_all(True))
        r.bind("<F5>", lambda e: self.refresh_keys())

    # ── 日志 / 进度 / 状态 ────────────────────────────────
    def log(self, msg, tag=None):
        ts = time.strftime("%H:%M:%S")
        self.logbox.configure(state="normal")
        self.logbox.insert("end", f"{ts}  ", ("dim",))
        self.logbox.insert("end", str(msg) + "\n", (tag,) if tag else ())
        # 限长，避免内存膨胀
        if int(self.logbox.index("end-1c").split(".")[0]) > 900:
            self.logbox.delete("1.0", "200.0")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def _progress(self, done, total):
        self.bar.set(done, total)
        if total:
            self.prog_lbl.configure(text=f"{done} / {total}")
        else:
            self.prog_lbl.configure(text="就绪")

    def _drain(self):
        try:
            while True:
                try:
                    msg = self.q.get_nowait()
                except queue.Empty:
                    break
                kind = msg[0]
                rest = msg[1:]
                if kind == "log":
                    text = rest[0] if rest else ""
                    tag = rest[1] if len(rest) > 1 else None
                    if tag is None:
                        if any(k in text for k in ("[✓]", "[+]", "成功", "完成", "0 错误")):
                            tag = "ok"
                        elif any(k in text for k in ("[x]", "失败", "错误", "异常")):
                            tag = "err"
                        elif any(k in text for k in ("[!]", "缺 key", "跳过")):
                            tag = "warn"
                    self.log(text, tag)
                elif kind == "status":
                    path = rest[0]
                    text = rest[1] if len(rest) > 1 else ""
                    tag = rest[2] if len(rest) > 2 else None
                    self._set_status(path, text, tag)
                elif kind == "progress":
                    self._progress(rest[0], rest[1])
                elif kind == "busy":
                    self._set_busy(rest[0])
                elif kind == "count":
                    self._update_count()
        except Exception:
            try:
                self.log("界面刷新异常：" + traceback.format_exc(limit=2), "err")
            except Exception:
                pass
        finally:
            try:
                self.root.after(60, self._drain)
            except Exception:
                pass

    def _set_busy(self, busy):
        self.busy = busy
        state = ["disabled"] if busy else ["!disabled"]
        self.btn_go.state(state)
        self.btn_grab.state(state)
        self.btn_stop.state(["!disabled"] if busy else ["disabled"])

    def _set_status(self, path, text, tag=None):
        iid = str(path)
        if not self.tree.exists(iid):
            return
        self.tree.set(iid, "status", text)
        it = self.items.get(iid) or {}
        if tag == "ok":
            self.tree.item(iid, tags=["done"])
        elif tag == "fail":
            self.tree.item(iid, tags=["fail"])
        elif it.get("check") == "miss":
            self.tree.item(iid, tags=["miss"])
        else:
            tags = ["odd"] if self.tree.index(iid) % 2 else []
            self.tree.item(iid, tags=tags)
        self._update_count()

    def _update_count(self):
        n = len(self.items)
        ready = sum(1 for it in self.items.values() if it.get("key"))
        done = sum(1 for it in self.items.values() if it.get("status") == "✓ 完成")
        checked = sum(1 for it in self.items.values() if it.get("checked"))
        self.count_lbl.configure(
            text=f"{n} 个文件 · 有 key {ready} · 勾选 {checked} · 完成 {done}")
        self.empty_lbl.place(relx=0.5, rely=0.45, anchor="center") if n == 0 else self.empty_lbl.place_forget()

    def _refresh_qqmusic_badge(self):
        try:
            pids = core.find_qqmusic_pids()
            if pids:
                self.qq_badge.configure(text=f"● QQ 音乐运行中 (PID {pids[0]})", fg=C["ok"])
            else:
                self.qq_badge.configure(text="● QQ 音乐未运行（抓 key 时会自动启动）", fg=C["faint"])
        except Exception:
            pass
        self.root.after(4000, self._refresh_qqmusic_badge)

    # ── 过滤 / 排序 ───────────────────────────────────────
    def _set_filter(self, name):
        self.filter_status = name
        self._paint_filter()
        self._apply_filter()

    def _paint_filter(self):
        for n, p in self.filter_pills.items():
            p.kind = "primary" if n == self.filter_status else "ghost"
            p._draw()

    def _apply_filter(self):
        self.filter_text = self.search_var.get().strip().lower()
        for sp, it in self.items.items():
            show = True
            if self.filter_status == "缺 key":
                show = (not it.get("key")) and it["meta"]["format"] != "qmc1"
            elif self.filter_status == "已完成":
                show = it.get("status") == "✓ 完成"
            if show and self.filter_text:
                hay = (it["path"].name + " " + (it["meta"].get("song_mid") or "")).lower()
                show = self.filter_text in hay
            if self.tree.exists(sp):
                if show:
                    self.tree.reattach(sp, "", "end")
                else:
                    self.tree.detach(sp)
        self._update_count()

    def sort_by(self, col):
        if col == "sel":
            return
        rows = [(self.tree.set(i, col), i) for i in self.tree.get_children()]

        def keyf(t):
            v = t[0]
            if col == "size":
                try:
                    num, unit = v.split()
                    return float(num) * (1024 ** ("KMGT".find(unit[0]) + 1))
                except Exception:
                    return 0
            return v

        rows.sort(key=keyf)
        for idx, (_, i) in enumerate(rows):
            self.tree.move(i, "", idx)
        for idx, i in enumerate(self.tree.get_children()):
            it = self.items.get(i) or {}
            if it.get("status") == "✓ 完成":
                continue
            tags = ["odd"] if idx % 2 else []
            if not it.get("key") and it["meta"]["format"] != "qmc1":
                tags = ["miss"]
            self.tree.item(i, tags=tags)

    # ── 文件操作 ──────────────────────────────────────────
    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="选择 QQ 音乐加密文件",
            filetypes=[("QQ 音乐加密文件", " ".join("*" + e for e in SUPPORTED)),
                       ("全部文件", "*.*")])
        if paths:
            self.add_paths(paths)

    def add_folder(self):
        d = filedialog.askdirectory(title="选择包含加密文件的文件夹")
        if d:
            self.add_paths([d])

    def _on_drop(self, event):
        try:
            paths = self.root.tk.splitlist(event.data)
        except Exception:
            paths = [event.data]
        try:
            self.list_card.set_border(C["border"])
        except Exception:
            pass
        self.add_paths(paths)

    def add_paths(self, paths):
        files = core.collect_files(paths)
        if not files:
            self.log("没找到 .mflac / .mgg / .qmc* 文件", "warn")
            return
        added = 0
        for f in files:
            sp = str(f)
            if sp in self.items:
                continue
            try:
                meta = core.parse_file(f)
            except Exception as e:
                self.log(f"解析失败 {f.name}: {e}", "err")
                continue
            key, src = self._resolve_key(meta)
            self.items[sp] = {
                "path": f, "meta": meta, "key": key, "key_src": src,
                "checked": True,
                "status": "待解密" if (key or meta["format"] == "qmc1") else "缺 key",
                "check": "" if (key or meta["format"] == "qmc1") else "miss",
            }
            self._insert_row(sp)
            added += 1
        if added:
            self.log(f"添加 {added} 个文件（共 {len(self.items)} 个）")
        if not self.out_var.get().strip() and self.items:
            self.out_var.set(str(Path(list(self.items)[0]).parent / "decoded"))
        self._apply_filter()
        self._update_count()

    def _resolve_key(self, meta):
        if meta.get("ekey"):
            k = core.ekey_to_key(meta["ekey"])
            if k:
                return k, "内嵌"
        ek = core.load_cached_ekey(meta)
        if ek:
            k = core.ekey_to_key(ek)
            if k:
                return k, "缓存"
        rk = core.load_cached_rawkey(meta)
        if rk:
            return rk, "缓存"
        return None, ""

    def _insert_row(self, sp):
        it = self.items[sp]
        m = it["meta"]
        key_stat = ("✓ " + it["key_src"]) if it["key"] else ("—" if m["format"] == "qmc1" else "缺")
        idx = len(self.tree.get_children())
        self.tree.insert("", "end", iid=sp, values=(
            "☑", it["path"].name, m["format"], human(m["size"]),
            m.get("song_mid") or "-", key_stat, it["status"]),
            tags=["odd"] if idx % 2 else ([] if (it["key"] or m["format"] == "qmc1") else ["miss"]))

    def _refresh_row(self, sp):
        it = self.items.get(sp)
        if not it or not self.tree.exists(sp):
            return
        m = it["meta"]
        key_stat = ("✓ " + it["key_src"]) if it["key"] else ("—" if m["format"] == "qmc1" else "缺")
        vals = list(self.tree.item(sp, "values"))
        vals[0] = "☑" if it["checked"] else "☐"
        vals[5] = key_stat
        vals[6] = it["status"]
        self.tree.item(sp, values=vals)

    def _on_click(self, event):
        if self.tree.identify("region", event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) == "#1":
            row = self.tree.identify_row(event.y)
            if row:
                self.toggle_one(row)
            return "break"

    def _on_double(self, event):
        row = self.tree.identify_row(event.y)
        if row:
            self.toggle_one(row)

    def _on_right(self, event):
        row = self.tree.identify_row(event.y)
        if row:
            if row not in self.tree.selection():
                self.tree.selection_set(row)
            self.menu.tk_popup(event.x_root, event.y_root)

    def toggle_one(self, iid):
        it = self.items.get(iid)
        if not it:
            return
        it["checked"] = not it["checked"]
        self._refresh_row(iid)
        self._update_count()

    def toggle_sel(self):
        for iid in self.tree.selection():
            self.toggle_one(iid)

    def set_all(self, v):
        for sp, it in self.items.items():
            it["checked"] = v
            self._refresh_row(sp)
        self._update_count()

    def invert_sel(self):
        for sp, it in self.items.items():
            it["checked"] = not it["checked"]
            self._refresh_row(sp)
        self._update_count()

    def remove_sel(self):
        for iid in list(self.tree.selection()):
            self.items.pop(iid, None)
            if self.tree.exists(iid):
                self.tree.delete(iid)
        self._update_count()

    def clear_all(self):
        self.items.clear()
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._update_count()
        self.log("已清空列表")

    def open_sel_dir(self):
        sel = self.tree.selection()
        if sel:
            os.startfile(str(Path(sel[0]).parent))

    def copy_sel_path(self):
        sel = self.tree.selection()
        if sel:
            self.root.clipboard_clear()
            self.root.clipboard_append("\n".join(sel))
            self.log(f"已复制 {len(sel)} 条路径")

    def refresh_keys(self):
        for sp, it in self.items.items():
            k, src = self._resolve_key(it["meta"])
            if k:
                it["key"], it["key_src"] = k, src
                it["check"] = ""
                if it["status"] == "缺 key":
                    it["status"] = "待解密"
            self._refresh_row(sp)
            tags = ["done"] if it["status"] == "✓ 完成" else (
                ["fail"] if it["status"] == "✗ 失败" else
                ([] if it.get("key") or it["meta"]["format"] == "qmc1" else ["miss"]))
            if self.tree.exists(sp):
                self.tree.item(sp, tags=tags)
        self._update_count()
        self.log("已刷新 key 状态")

    def pick_out(self):
        d = filedialog.askdirectory(title="选择输出目录")
        if d:
            self.out_var.set(d)

    def open_out(self):
        d = self.out_var.get().strip()
        if d and os.path.isdir(d):
            os.startfile(d)
        else:
            self.log("输出目录还不存在（解密后会自动创建）", "warn")

    # ── 任务 ──────────────────────────────────────────────
    def _checked(self):
        return [it for it in self.items.values() if it["checked"]]

    def grab_keys(self):
        if self.busy:
            return
        items = [it for it in self._checked() if not it["key"] and it["meta"]["format"] != "qmc1"]
        if not items:
            self.log("勾选的文件都已有 key（或不需要 key）")
            return
        self._set_busy(True)
        threading.Thread(target=self._job_grab, args=(items,), daemon=True).start()

    def _job_grab(self, items):
        old_err = sys.stderr
        sys.stderr = _QW(self.q)
        try:
            self.q.put(("log", f"开始抓 key：{len(items)} 个文件（会调用 QQ 音乐逐个解密）"))
            files = [it["path"] for it in items]
            metas = {it["path"]: it["meta"] for it in items}
            self.q.put(("progress", 0, len(items)))
            got = core.grab_keys_from_client(files, metas)
            for i, it in enumerate(items, 1):
                k = got.get(it["path"].name.lower())
                if k and core.key_fits_file(it["path"], it["meta"], k):
                    core.save_cached_rawkey(it["meta"], k)
                    it["key"], it["key_src"] = k, "客户端"
                    it["status"] = "待解密"
                    it["check"] = ""
                    self.q.put(("status", str(it["path"]), "待解密", None))
                    self.q.put(("log", f"[+] {it['path'].name} 抓到 key {len(k)}B"))
                else:
                    it["status"] = "缺 key"
                    it["check"] = "miss"
                    self.q.put(("status", str(it["path"]), "缺 key", "fail"))
                    self.q.put(("log", f"[!] {it['path'].name} 未抓到可用 key"))
                self.q.put(("progress", i, len(items)))
            self.q.put(("log", "抓 key 结束"))
        except Exception:
            self.q.put(("log", "抓 key 出错：" + traceback.format_exc(limit=2), "err"))
        finally:
            sys.stderr = old_err
            self.q.put(("busy", False,))
            self.q.put(("progress", 0, 0))

    def stop(self):
        self.stop_flag = True
        self.log("已请求停止（当前文件完成后停止）", "warn")

    def start(self):
        if self.busy:
            return
        items = self._checked()
        if not items:
            messagebox.showinfo("提示", "先勾选要解密的文件", parent=self.root)
            return
        out_dir = self.out_var.get().strip()
        if not out_dir:
            out_dir = str(items[0]["path"].parent / "decoded")
            self.out_var.set(out_dir)
        self.stop_flag = False
        self._set_busy(True)
        threading.Thread(target=self._job_decrypt, args=(items, Path(out_dir)), daemon=True).start()

    def _job_decrypt(self, items, out_dir):
        old_err, old_out = sys.stderr, sys.stdout
        sys.stderr = _QW(self.q)
        sys.stdout = _QW(self.q)
        ok = fail = 0
        try:
            missing = [it for it in items if not it["key"] and it["meta"]["format"] != "qmc1"]
            if missing and self.auto_client.get():
                self.q.put(("log", f"{len(missing)} 个文件缺 key，开始从 QQ 音乐抓取…"))
                got = core.grab_keys_from_client(
                    [it["path"] for it in missing],
                    {it["path"]: it["meta"] for it in missing})
                for it in missing:
                    k = got.get(it["path"].name.lower())
                    if k and core.key_fits_file(it["path"], it["meta"], k):
                        core.save_cached_rawkey(it["meta"], k)
                        it["key"], it["key_src"] = k, "客户端"
                        it["check"] = ""
                        self.q.put(("status", str(it["path"]), "待解密", None))
                        self.q.put(("log", f"[+] {it['path'].name} 抓到 key"))
                    else:
                        self.q.put(("status", str(it["path"]), "缺 key", "fail"))
                        self.q.put(("log", f"[!] {it['path'].name} 缺 key，跳过"))

            todo = [it for it in items if it["key"] or it["meta"]["format"] == "qmc1"]
            self.q.put(("log", f"开始解密 {len(todo)} 个文件 → {out_dir}"))
            self.q.put(("progress", 0, len(todo)))
            for i, it in enumerate(todo, 1):
                if self.stop_flag:
                    self.q.put(("log", "已停止"))
                    break
                path, meta = it["path"], it["meta"]
                self.q.put(("status", str(path), "解密中…", None))
                t0 = time.time()
                try:
                    if meta["format"] == "qmc1":
                        out = self._decrypt_v1(path, meta, out_dir)
                        r = {"ok": True, "output": str(out), "ext": out.suffix}
                    else:
                        r = core.decrypt_file(path, meta, it["key"], out_dir,
                                              overwrite=self.overwrite.get())
                    if r.get("ok"):
                        if self.trim.get() and str(r.get("ext")) == ".flac":
                            self.q.put(("log", f"    修尾中（无损重封装）… {path.name}"))
                            if core.trim_with_ffmpeg(Path(r["output"])):
                                r["trimmed"] = True
                        ok += 1
                        it["status"] = "✓ 完成"
                        cost = time.time() - t0
                        size = Path(r["output"]).stat().st_size
                        extra = " +修尾" if r.get("trimmed") else ""
                        self.q.put(("log", f"[✓] {path.name} → {Path(r['output']).name}"
                                           f"  ({human(size)}, {cost:.1f}s{extra})"))
                        self.q.put(("status", str(path), "✓ 完成", "ok"))
                    else:
                        fail += 1
                        it["status"] = "✗ 失败"
                        self.q.put(("log", f"[x] {path.name} → {r.get('error')}", "err"))
                        self.q.put(("status", str(path), "✗ 失败", "fail"))
                except Exception as e:
                    fail += 1
                    it["status"] = "✗ 失败"
                    self.q.put(("log", f"[x] {path.name} → {e}", "err"))
                    self.q.put(("status", str(path), "✗ 失败", "fail"))
                self.q.put(("progress", i, len(todo)))

            self.q.put(("log", f"全部结束：成功 {ok}，失败 {fail}　输出 {out_dir}",
                        "ok" if fail == 0 else "err"))
            if ok:
                try:
                    os.startfile(str(out_dir))
                except Exception:
                    pass
        except Exception:
            self.q.put(("log", "解密出错：" + traceback.format_exc(limit=2), "err"))
        finally:
            sys.stderr, sys.stdout = old_err, old_out
            self.q.put(("busy", False,))

    def _decrypt_v1(self, path, meta, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(path, "rb") as fh:
            probe = bytearray(fh.read(min(64, meta["audio_size"])))
        core.StaticCipher().decrypt(probe, 0)
        ext = core.sniff_ext(bytes(probe[:16])) or ".mp3"
        out = out_dir / (core._stem(path) + ext)
        n = 1
        while out.exists() and not self.overwrite.get():
            out = out_dir / f"{core._stem(path)} ({n}){ext}"
            n += 1
        sc = core.StaticCipher()
        with open(path, "rb") as fin, open(out, "wb") as fout:
            off = 0
            while off < meta["audio_size"]:
                k = min(core.DEC_CHUNK, meta["audio_size"] - off)
                buf = bytearray(fin.read(k))
                if len(buf) != k:
                    break
                sc.decrypt(buf, off)
                fout.write(buf)
                off += k
        return out

    # ── 退出 ──────────────────────────────────────────────
    def _on_close(self):
        try:
            save_cfg({
                "geometry": self.root.geometry(),
                "out_dir": self.out_var.get(),
                "auto_client": bool(self.auto_client.get()),
                "trim": bool(self.trim.get()),
                "overwrite": bool(self.overwrite.get()),
            })
        except Exception:
            pass
        if self.busy:
            if not messagebox.askyesno("退出", "还有任务在跑，确定退出？", parent=self.root):
                return
            self.stop_flag = True
        self.root.destroy()


class _QW:
    """stdout/stderr → 日志队列"""

    def __init__(self, q):
        self.q = q

    def write(self, s):
        if s and s.strip():
            self.q.put(("log", s.rstrip()))

    def flush(self):
        pass


def main():
    root = TkinterDnD.Tk() if _DND else tk.Tk()
    app = App(root)

    argv = sys.argv[1:]
    paths, out, auto = [], None, False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--auto":
            auto = True
        elif a == "--out" and i + 1 < len(argv):
            out = argv[i + 1]
            i += 1
        elif not a.startswith("-"):
            paths.append(a)
        i += 1

    if out:
        app.out_var.set(out)
    if paths:
        root.after(200, lambda: app.add_paths(paths))
    if auto:
        def _go():
            if out:
                app.out_var.set(out)
            app.start()
        root.after(1600, _go)

    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        try:
            import tkinter.messagebox as mb
            mb.showerror("程序异常", traceback.format_exc())
        except Exception:
            print(traceback.format_exc())
