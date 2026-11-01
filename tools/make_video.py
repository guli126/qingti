# -*- coding: utf-8 -*-
"""轻提宣传片生成器（一次性工具，不参与打包、不进仓库）。

流程：文案 → SAPI 配音 → Pillow 逐场画面 → ffmpeg zoompan/xfade/混音 → 成片。
产物都在 video/out/ 下，横版给 B 站，竖版给抖音。

用法：
    python tools/make_video.py            # 两版都做
    python tools/make_video.py v          # 只做竖版
    python tools/make_video.py h          # 只做横版
"""

import io
import os
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VID = os.path.join(ROOT, "video")
SHOTS = os.path.join(VID, "shots")
TTS = os.path.join(VID, "tts")
FRAMES = os.path.join(VID, "frames")
CLIPS = os.path.join(VID, "clips")
TMP = os.path.join(VID, "tmp")
OUT = os.path.join(VID, "out")
FF = ("C:/Users/Administrator/AppData/Local/Programs/Python/Python310/"
      "lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe")
TTS_PS1 = os.path.join(VID, "tts.ps1")

F_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
F_REG = "C:/Windows/Fonts/msyh.ttc"

# ------------------------------------------------------------------ 配色
INK = (10, 14, 24)
INK2 = (20, 27, 44)
ACCENT = (47, 111, 237)
ACCENT_SOFT = (126, 170, 255)
WHITE = (247, 249, 252)
SUB = (162, 175, 194)
CARD = (255, 255, 255)
DARK_CARD = (28, 36, 54)

# ------------------------------------------------------------------ 场景
# 每场：id / 旁白 / 画面小标题 / 画面副标题 / 底部字幕
SCENES = [
    dict(key="hook",
         narration="同一句话，交给两个 AI，能问出十种结果。不是 AI 笨，是你没把话说清楚。",
         caption="痛点：说不清，它就只能猜"),
    dict(key="pain",
         narration="难的不是措辞，是你不知道自己漏了什么：用在哪、给谁用、什么算做完。",
         caption="三个最常被漏掉的缺口"),
    dict(key="intro",
         narration="轻提，装在自己电脑里的提示词优化器。你说一句大白话，它先反问你。",
         caption="你只需要说一句大白话"),
    dict(key="ask",
         narration="问题都是选择题，能点的不用打字，每题都标好了推荐项。懒得答，就点「就这些，开始吧」。",
         caption="点几下，信息就补齐了"),
    dict(key="result",
         narration="几秒钟后，你拿到的是分好节的提示词：目标、场景、约束、验收标准。复制就能用。",
         caption="分节清楚，复制即用"),
    dict(key="modes",
         narration="编程、办公、图像，三个场景，十三套模板。模板就是 Markdown，改完保存立刻生效。",
         caption="编程 / 办公 / 图像 · 13 套模板"),
    dict(key="outro",
         narration="全部在本机跑，密钥用 Windows 账户加密，绿色版双击就用。轻提，开源免费。",
         caption="MIT 开源 · 欢迎 Star"),
]

LEAD = 0.45          # 每场开头留白
TAIL = 0.75          # 每场结尾留白
XF = 0.55            # 转场时长
FPS = 30


# ------------------------------------------------------------------ 基础绘制
def font(size, bold=False):
    return ImageFont.truetype(F_BOLD if bold else F_REG, size)


def txt(draw, xy, s, f, fill, anchor="la"):
    draw.text(xy, s, font=f, fill=fill, anchor=anchor)


def fit(draw, s, maxw, size, bold=True):
    f = font(size, bold)
    while draw.textlength(s, font=f) > maxw and size > 12:
        size -= 2
        f = font(size, bold)
    return f


def bg(w, h):
    """深色渐变底 + 两团柔光。"""
    strip = Image.new("RGB", (1, h))
    pix = strip.load()
    for y in range(h):
        t = y / max(1, h - 1)
        pix[0, y] = (int(INK[0] + (INK2[0] - INK[0]) * t),
                     int(INK[1] + (INK2[1] - INK[1]) * t),
                     int(INK[2] + (INK2[2] - INK[2]) * t))
    base = strip.resize((w, h), Image.BILINEAR)

    glow = Image.new("RGB", (w, h), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    r1 = int(w * 0.42)
    gd.ellipse([w * 0.52 - r1, -r1 * 0.75, w * 0.52 + r1, r1 * 0.95],
               fill=(26, 52, 110))
    r2 = int(w * 0.30)
    gd.ellipse([-r2 * 0.6, h * 0.62 - r2, r2 * 1.4, h * 0.62 + r2],
               fill=(14, 30, 68))
    glow = glow.filter(ImageFilter.GaussianBlur(int(w * 0.055)))
    base = Image.blend(base, glow, 0.55)
    return base


def window_card(canvas, shot_path, box, radius=22):
    """把界面截图放进白色卡片（带投影）。"""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    shot = Image.open(shot_path).convert("RGB")
    ratio = min(w / shot.width, h / shot.height)
    shot = shot.resize((int(shot.width * ratio), int(shot.height * ratio)),
                       Image.LANCZOS)
    layer = Image.new("RGB", (w, h), (255, 255, 255))
    layer.paste(shot, ((w - shot.width) // 2, (h - shot.height) // 2))

    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1],
                                           radius=radius, fill=255)

    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle([x0 + 8, y0 + 16, x1 + 8, y1 + 20], radius=radius,
                         fill=(0, 0, 0, 165))
    shadow = shadow.filter(ImageFilter.GaussianBlur(28))
    canvas.paste(shadow.convert("RGB"), (0, 0), shadow.split()[3])
    canvas.paste(layer, (x0, y0), mask)
    return canvas


def pill(draw, xy, s, size=30, bgc=ACCENT, fgc=WHITE, padx=26, pady=14,
         anchor="lt", bold=True):
    f = font(size, bold)
    tw = draw.textlength(s, font=f)
    x, y = xy
    w, h = int(tw + padx * 2), int(size + pady * 2)
    box = [x, y, x + w, y + h]
    draw.rounded_rectangle(box, radius=h // 2, fill=bgc)
    draw.text((x + w / 2, y + h / 2 - size * 0.06), s, font=f, fill=fgc,
              anchor="mm")
    return box


# ------------------------------------------------------------------ 各场景
AR = 1.596          # 界面截图宽高比
AR_EDITOR = 1.474


def fit_box(x0, x1, ytop, ar=AR):
    """按截图真实比例算出卡片高度，避免白边。"""
    x0, x1, ytop = int(x0), int(x1), int(ytop)
    w = x1 - x0
    return (x0, ytop, x1, ytop + int(w / ar))


def scene_hook(c, L):
    d = ImageDraw.Draw(c)
    W, H = c.size
    cx = W // 2
    f1 = fit(d, "同一句话", W * 0.74, int(H * 0.145))
    txt(d, (cx, H * 0.32), "同一句话", f1, WHITE, "mm")
    f2 = fit(d, "十种结果", W * 0.74, int(H * 0.145))
    txt(d, (cx, H * 0.32 + int(H * 0.155)), "十种结果", f2, ACCENT_SOFT, "mm")
    txt(d, (cx, H * 0.32 + int(H * 0.285)), "不是 AI 笨，是你没把话说清楚",
        font(int(H * 0.034)), SUB, "mm")


def scene_pain(c, L):
    d = ImageDraw.Draw(c)
    W, H = c.size
    vertical = L["vertical"]
    margin = L["margin"]

    title = "你漏掉的，模型不会替你补"
    f_t = fit(d, title, W - margin * 2, int(H * (0.055 if vertical else 0.072)))
    txt(d, (margin, int(H * (0.09 if vertical else 0.13))), title, f_t, WHITE)
    txt(d, (margin, int(H * (0.09 if vertical else 0.13)) + int(H * (0.075 if vertical else 0.095))),
        "措辞不是难点，信息缺口才是", font(int(H * (0.024 if vertical else 0.031))), SUB)

    bub = "帮我做个记账的东西"
    fb = font(int(H * (0.028 if vertical else 0.038)), True)
    bw = int(d.textlength(bub, font=fb)) + 80
    bx, by = margin, int(H * (0.42 if vertical else 0.42))
    bh = int(H * (0.062 if vertical else 0.080))
    d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=int(bh * 0.28), fill=ACCENT)
    txt(d, (bx + bw / 2, by + bh / 2), bub, fb, WHITE, "mm")

    gaps = ["用在哪？", "给谁看？", "什么算做完？"]
    if vertical:
        y = by + bh + int(H * 0.045)
        for g in gaps:
            box = pill(d, (margin, y), g, size=int(H * 0.026), bgc=DARK_CARD,
                       fgc=(255, 214, 102), padx=30, pady=16)
            d.rounded_rectangle(box, radius=box[3] - box[1],
                                outline=(255, 214, 102), width=2)
            y += int(H * 0.058)
        txt(d, (margin, y + int(H * 0.012)), "模型只能猜，猜出来自然不对味",
            font(int(H * 0.022)), SUB)
    else:
        y = by + bh + int(H * 0.06)
        x = margin
        for g in gaps:
            box = pill(d, (x, y), g, size=int(H * 0.040), bgc=DARK_CARD,
                       fgc=(255, 214, 102), padx=34, pady=18)
            d.rounded_rectangle(box, radius=box[3] - box[1],
                                outline=(255, 214, 102), width=2)
            x = box[2] + 34
        txt(d, (margin, y + int(H * 0.115)), "模型只能猜，猜出来的东西自然不对味",
            font(int(H * 0.031)), SUB)


def scene_intro(c, L):
    d = ImageDraw.Draw(c)
    W, H = c.size
    vertical = L["vertical"]
    margin = L["margin"]

    if vertical:
        txt(d, (margin, int(H * 0.065)), "轻提",
            fit(d, "轻提", W - margin * 2, int(H * 0.075)), WHITE)
        txt(d, (margin, int(H * 0.155)), "本地提示词优化器",
            font(int(H * 0.030)), ACCENT_SOFT)
        window_card(c, os.path.join(SHOTS, "welcome.png"),
                    fit_box(margin, W - margin, int(H * 0.245)))
        y = int(H * 0.60)
        for s in ["全本地运行 · 不联网上传", "零第三方依赖 · 绿色版双击即用",
                  "编程 / 办公 / 图像 三场景"]:
            txt(d, (margin, y), "· " + s, font(int(H * 0.023)), SUB)
            y += int(H * 0.040)
    else:
        txt(d, (margin, int(H * 0.22)), "轻提",
            fit(d, "轻提", int(W * 0.36), int(H * 0.135)), WHITE)
        txt(d, (margin, int(H * 0.395)), "本地提示词优化器",
            font(int(H * 0.045)), ACCENT_SOFT)
        y = int(H * 0.53)
        for s in ["全本地运行 · 不联网上传", "零第三方依赖 · 零安装",
                  "编程 / 办公 / 图像 三场景"]:
            txt(d, (margin, y), "· " + s, font(int(H * 0.030)), SUB)
            y += int(H * 0.062)
        window_card(c, os.path.join(SHOTS, "welcome.png"),
                    fit_box(int(W * 0.44), W - int(margin * 0.7), int(H * 0.17)))


def scene_ask(c, L):
    d = ImageDraw.Draw(c)
    W, H = c.size
    vertical = L["vertical"]
    margin = L["margin"]

    if vertical:
        txt(d, (margin, int(H * 0.05)), "它先反问你",
            fit(d, "它先反问你", W - margin * 2, int(H * 0.06)), WHITE)
        txt(d, (margin, int(H * 0.118)), "带选项、标推荐，懒得答也能跳过",
            font(int(H * 0.024)), SUB)
        box = fit_box(margin, W - margin, int(H * 0.20))
        window_card(c, os.path.join(SHOTS, "ask.png"), box)
        y = box[3] + int(H * 0.035)
        pill(d, (margin, y), "★ 每题都标了推荐项", size=int(H * 0.022),
             bgc=(255, 214, 102), fgc=(40, 32, 8))
        pill(d, (margin, y + int(H * 0.048)), "「就这些，开始吧」一键跳过",
             size=int(H * 0.022), bgc=DARK_CARD, fgc=ACCENT_SOFT)
    else:
        txt(d, (margin, int(H * 0.10)), "它先反问你两三句",
            fit(d, "它先反问你两三句", int(W * 0.36), int(H * 0.068)), WHITE)
        txt(d, (margin, int(H * 0.19)), "带选项的问题，点一下就完事",
            font(int(H * 0.031)), SUB)
        y = int(H * 0.31)
        for s2, c2 in [("★ 每题都标了推荐项", (255, 214, 102)),
                       ("「就这些，开始吧」一键跳过", ACCENT_SOFT),
                       ("最多三轮，问完必出结果", SUB)]:
            txt(d, (margin, y), s2, font(int(H * 0.032), True), c2)
            y += int(H * 0.085)
        window_card(c, os.path.join(SHOTS, "ask.png"),
                    fit_box(int(W * 0.42), W - int(margin * 0.55), int(H * 0.13)))


def scene_result(c, L):
    d = ImageDraw.Draw(c)
    W, H = c.size
    vertical = L["vertical"]
    margin = L["margin"]
    sections = ["目标", "使用场景", "必须包含", "技术要求", "验收标准"]

    if vertical:
        txt(d, (margin, int(H * 0.048)), "三十秒后",
            fit(d, "三十秒后", W - margin * 2, int(H * 0.06)), WHITE)
        txt(d, (margin, int(H * 0.112)), "拿到能直接用的提示词",
            font(int(H * 0.026)), ACCENT_SOFT)
        box = fit_box(margin, W - margin, int(H * 0.175))
        window_card(c, os.path.join(SHOTS, "result.png"), box)
        y = box[3] + int(H * 0.028)
        x = margin
        f = font(int(H * 0.019))
        for s2 in sections:
            w = int(d.textlength(s2, font=f)) + 44
            if x + w > W - margin:
                x = margin
                y += int(H * 0.042)
            d.rounded_rectangle([x, y, x + w, y + int(H * 0.036)], radius=11,
                                fill=DARK_CARD, outline=ACCENT, width=2)
            txt(d, (x + w / 2, y + int(H * 0.018)), s2, f, ACCENT_SOFT, "mm")
            x += w + 12
    else:
        txt(d, (margin, int(H * 0.09)), "三十秒后",
            fit(d, "三十秒后", int(W * 0.35), int(H * 0.070)), WHITE)
        txt(d, (margin, int(H * 0.185)), "拿到能直接用的提示词",
            font(int(H * 0.031)), ACCENT_SOFT)
        y = int(H * 0.30)
        f = font(int(H * 0.032), True)
        for s2 in sections:
            w = int(d.textlength(s2, font=f)) + 80
            d.rounded_rectangle([margin, y, margin + w, y + int(H * 0.072)],
                                radius=13, fill=DARK_CARD, outline=ACCENT, width=2)
            txt(d, (margin + w / 2, y + int(H * 0.036)), s2, f, ACCENT_SOFT, "mm")
            y += int(H * 0.095)
        window_card(c, os.path.join(SHOTS, "result.png"),
                    fit_box(int(W * 0.42), W - int(margin * 0.55), int(H * 0.135)))


def scene_modes(c, L):
    d = ImageDraw.Draw(c)
    W, H = c.size
    margin = L["margin"]
    vertical = L["vertical"]
    items = [("编程", "任务 / 系统 / 迭代"),
             ("办公", "周报 · 方案 · 邮件"),
             ("图像", "文生图 / 图生图")]

    if vertical:
        txt(d, (margin, int(H * 0.055)), "三个场景，十三套模板",
            fit(d, "三个场景，十三套模板", W - margin * 2, int(H * 0.055)), WHITE)
        txt(d, (margin, int(H * 0.115)), "模板就是 Markdown，改完保存即生效",
            font(int(H * 0.022)), SUB)
        y = int(H * 0.175)
        for name, desc in items:
            d.rounded_rectangle([margin, y, W - margin, y + int(H * 0.085)],
                                radius=16, fill=DARK_CARD)
            txt(d, (margin + 36, y + int(H * 0.0425)), name,
                font(int(H * 0.030), True), WHITE, "lm")
            txt(d, (margin + 36 + int(W * 0.16), y + int(H * 0.0425)), desc,
                font(int(H * 0.021)), SUB, "lm")
            y += int(H * 0.098)
        window_card(c, os.path.join(SHOTS, "editor.png"),
                    fit_box(margin, W - margin, int(H * 0.50), AR_EDITOR))
    else:
        txt(d, (margin, int(H * 0.09)), "三个场景，十三套模板",
            fit(d, "三个场景，十三套模板", int(W * 0.42), int(H * 0.066)), WHITE)
        txt(d, (margin, int(H * 0.185)), "模板就是 Markdown，改完即生效",
            font(int(H * 0.030)), SUB)
        y = int(H * 0.30)
        for name, desc in items:
            d.rounded_rectangle([margin, y, int(W * 0.40), y + int(H * 0.135)],
                                radius=16, fill=DARK_CARD)
            d.rectangle([margin, y + 26, margin + 7, y + int(H * 0.135) - 26],
                        fill=ACCENT)
            txt(d, (margin + 44, y + int(H * 0.042)), name,
                font(int(H * 0.042), True), WHITE)
            txt(d, (margin + 44, y + int(H * 0.093)), desc,
                font(int(H * 0.025)), SUB)
            y += int(H * 0.165)
        window_card(c, os.path.join(SHOTS, "editor.png"),
                    fit_box(int(W * 0.44), W - int(margin * 0.7), int(H * 0.19),
                            AR_EDITOR))


def scene_outro(c, L):
    d = ImageDraw.Draw(c)
    W, H = c.size
    cx = W // 2
    vertical = L["vertical"]

    base_y = 0.26 if vertical else 0.24
    txt(d, (cx, H * base_y), "轻提",
        fit(d, "轻提", W * 0.6, int(H * (0.115 if vertical else 0.145))), WHITE, "mm")
    txt(d, (cx, H * base_y + int(H * (0.105 if vertical else 0.115))),
        "让 AI 听懂你的大白话",
        fit(d, "让 AI 听懂你的大白话", W * 0.86,
            int(H * (0.045 if vertical else 0.050))), ACCENT_SOFT, "mm")

    y = int(H * (0.55 if vertical else 0.56))
    for s2 in ["全本地运行 · 密钥 DPAPI 加密", "MIT 开源 · 绿色版免安装"]:
        txt(d, (cx, y), s2, font(int(H * (0.024 if vertical else 0.029))), SUB, "mm")
        y += int(H * 0.055)

    gitee = "gitee.com/linhaonan126/qingti"
    f3 = font(int(H * (0.028 if vertical else 0.033)), True)
    tw = d.textlength(gitee, font=f3)
    bh = int(H * 0.082)
    box = [cx - tw / 2 - 46, H * 0.73, cx + tw / 2 + 46, H * 0.73 + bh]
    d.rounded_rectangle(box, radius=bh // 2, fill=ACCENT)
    txt(d, (cx, H * 0.73 + bh / 2), gitee, f3, WHITE, "mm")


RENDER = dict(hook=scene_hook, pain=scene_pain, intro=scene_intro,
              ask=scene_ask, result=scene_result, modes=scene_modes,
              outro=scene_outro)


def caption_bar(c, L, text):
    d = ImageDraw.Draw(c)
    W, H = c.size
    f = font(int(H * (0.026 if L["vertical"] else 0.028)), True)
    tw = d.textlength(text, font=f)
    # 竖版字幕上移到安全区：抖音底部 UI 会压住最下面 15%
    y = int(H * 0.895) if not L["vertical"] else int(H * 0.848)
    pad = 26
    box = [W / 2 - tw / 2 - pad, y, W / 2 + tw / 2 + pad, y + int(H * 0.062)]
    d.rounded_rectangle(box, radius=int(H * 0.031), fill=(0, 0, 0))
    txt(d, (W / 2, y + int(H * 0.031)), text, f, (255, 255, 255), "mm")


def build_frame(scene, L, path):
    W, H = L["size"]
    c = bg(W, H)
    RENDER[scene["key"]](c, L)
    caption_bar(c, L, scene["caption"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    c.save(path, optimize=True)
    return path


# ------------------------------------------------------------------ 配音
def say(text, out_wav, rate=3):
    os.makedirs(TTS, exist_ok=True)
    txt_path = out_wav + ".txt"
    io.open(txt_path, "w", encoding="utf-8").write(text)
    if not os.path.exists(out_wav) or os.path.getmtime(out_wav) < os.path.getmtime(txt_path):
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", TTS_PS1, "-TextFile", txt_path, "-Out", out_wav,
                        "-Rate", str(rate)], check=True, capture_output=True)
    return out_wav


def duration(path):
    out = subprocess.run([FF, "-hide_banner", "-i", path], capture_output=True,
                         text=True, errors="ignore").stderr
    for line in out.splitlines():
        if "Duration:" in line:
            hms = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = hms.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    raise RuntimeError("probe failed: " + path)


def run(args):
    p = subprocess.run(args, capture_output=True, text=True, errors="ignore")
    if p.returncode != 0:
        sys.stderr.write(" ".join(args) + "\n" + p.stderr[-3000:])
        raise SystemExit(1)
    return p


# ------------------------------------------------------------------ 合成
def make(orientation):
    vertical = orientation == "v"
    L = dict(vertical=vertical,
             size=(1080, 1920) if vertical else (1920, 1080),
             margin=90 if vertical else 132)
    W, H = L["size"]
    tag = "v" if vertical else "h"

    print("[%s] 1/5 配音…" % tag)
    durs = []
    for i, sc in enumerate(SCENES, 1):
        wav = say(sc["narration"], os.path.join(TTS, "s%d.wav" % i))
        durs.append(duration(wav))
    print("    旁白时长：", ["%.1f" % d for d in durs])

    scene_len = [LEAD + d + TAIL for d in durs]

    print("[%s] 2/5 画面…" % tag)
    frames = []
    for i, sc in enumerate(SCENES, 1):
        frames.append(build_frame(sc, L, os.path.join(FRAMES, tag, "s%d.png" % i)))

    print("[%s] 3/5 单场片段…" % tag)
    clips = []
    os.makedirs(os.path.join(CLIPS, tag), exist_ok=True)
    for i, (fr, dur) in enumerate(zip(frames, scene_len), 1):
        out = os.path.join(CLIPS, tag, "s%d.mp4" % i)
        frames_n = int(round(dur * FPS))
        zoom = "min(1+0.09*on/%d,1.09)" % max(1, frames_n)
        run([FF, "-y", "-hide_banner", "-loglevel", "error",
             "-i", fr,
             "-vf", ("zoompan=z='%s':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                     ":d=%d:s=%dx%d:fps=%d" % (zoom, frames_n, W, H, FPS)),
             "-c:v", "libx264", "-preset", "medium", "-crf", "18",
             "-pix_fmt", "yuv420p", out])
        clips.append(out)

    print("[%s] 4/5 转场拼接…" % tag)
    inputs = []
    for c in clips:
        inputs += ["-i", c]
    n = len(clips)
    parts = []
    offset = 0.0
    prev = "[0:v]"
    for i in range(1, n):
        offset += scene_len[i - 1] - XF
        outlbl = "[v%d]" % i
        parts.append("%s[%d:v]xfade=transition=fade:duration=%.2f:offset=%.2f%s"
                     % (prev, i, XF, offset, outlbl))
        prev = outlbl
    total = sum(scene_len) - XF * (n - 1)
    parts.append("%sfade=t=in:st=0:d=0.6,fade=t=out:st=%.2f:d=0.8[vout]"
                 % (prev, total - 0.8))
    silent = os.path.join(TMP, "%s_video.mp4" % tag)
    os.makedirs(TMP, exist_ok=True)
    run([FF, "-y", "-hide_banner", "-loglevel", "error", *inputs,
         "-filter_complex", ";".join(parts), "-map", "[vout]",
         "-c:v", "libx264", "-preset", "slow", "-crf", "19",
         "-pix_fmt", "yuv420p", "-r", str(FPS), silent])

    print("[%s] 5/5 混音…" % tag)
    audio_inputs = []
    for i in range(1, n + 1):
        audio_inputs += ["-i", os.path.join(TTS, "s%d.wav" % i)]
    afilter = []
    starts = []
    t = 0.0
    for i in range(n):
        if i:
            t += scene_len[i - 1] - XF
        starts.append(t + LEAD)
    for i, st in enumerate(starts):
        afilter.append("[%d:a]aresample=44100,adelay=%d|%d,apad=whole_dur=%.2f[a%d]"
                       % (i, int(st * 1000), int(st * 1000), total, i))
    mix = "".join("[a%d]" % i for i in range(n))
    afilter.append("%samix=inputs=%d:normalize=0:duration=longest,"
                   "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100,alimiter=limit=0.97[aout]"
                   % (mix, n))
    wav = os.path.join(TMP, "%s_audio.m4a" % tag)
    run([FF, "-y", "-hide_banner", "-loglevel", "error", *audio_inputs,
         "-filter_complex", ";".join(afilter), "-map", "[aout]",
         "-c:a", "aac", "-b:a", "192k", "-t", "%.2f" % total, wav])

    os.makedirs(OUT, exist_ok=True)
    name = ("轻提-宣传片-竖版1080x1920.mp4" if vertical
            else "轻提-宣传片-横版1920x1080.mp4")
    final = os.path.join(OUT, name)
    run([FF, "-y", "-hide_banner", "-loglevel", "error",
         "-i", silent, "-i", wav, "-map", "0:v", "-map", "1:a",
         "-c:v", "copy", "-c:a", "copy", "-shortest",
         "-movflags", "+faststart", final])
    print("    成片：%s  (%.1fs)" % (final, total))
    return final, total


def cover():
    """两张封面：B 站 16:9、抖音 3:4。"""
    os.makedirs(OUT, exist_ok=True)
    made = []
    for (W, H), name in [((1920, 1080), "封面-横版1920x1080.png"),
                         ((1080, 1440), "封面-竖版1080x1440.png")]:
        c = bg(W, H)
        d = ImageDraw.Draw(c)
        tag = "开源 · MIT 协议 · 绿色版免安装"
        ft = font(int(H * 0.026))
        tw = d.textlength(tag, font=ft)
        d.rounded_rectangle([W / 2 - tw / 2 - 30, int(H * 0.075),
                             W / 2 + tw / 2 + 30, int(H * 0.075) + int(H * 0.055)],
                            radius=int(H * 0.0275), fill=DARK_CARD)
        txt(d, (W / 2, int(H * 0.075) + int(H * 0.0275)), tag, ft, ACCENT_SOFT, "mm")

        txt(d, (W / 2, int(H * 0.27)), "轻提",
            fit(d, "轻提", W * 0.62, int(H * 0.13)), WHITE, "mm")
        txt(d, (W / 2, int(H * 0.375)), "让 AI 听懂你的大白话",
            fit(d, "让 AI 听懂你的大白话", W * 0.84, int(H * 0.052)), ACCENT_SOFT, "mm")
        txt(d, (W / 2, int(H * 0.455)), "本地提示词优化器 · 先反问再动笔",
            fit(d, "本地提示词优化器 · 先反问再动笔", W * 0.8, int(H * 0.032)), SUB, "mm")

        top = int(H * 0.545)
        avail_h = H - top - int(H * 0.06)
        cw = min(int(avail_h * AR), int(W * 0.80))
        box = fit_box(W / 2 - cw / 2, W / 2 + cw / 2, top)
        window_card(c, os.path.join(SHOTS, "ask.png"), box)
        p2 = os.path.join(OUT, name)
        c.save(p2, optimize=True)
        made.append(p2)
    return made


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    for d in (FRAMES, CLIPS, TMP, OUT):
        os.makedirs(d, exist_ok=True)
    done = []
    if which in ("h", "both"):
        done.append(make("h"))
    if which in ("v", "both"):
        done.append(make("v"))
    if which == "cover":
        done = [(p, 0) for p in cover()]
    for p, t in done:
        print("OK", p, "%.1fs" % t)


if __name__ == "__main__":
    main()
