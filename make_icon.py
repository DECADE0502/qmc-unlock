"""生成应用图标 app.ico（渐变圆角 + 音符 + 解锁小锁）"""
from PIL import Image, ImageDraw, ImageFont

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

top = (0x82, 0x6d, 0xff)
bot = (0x45, 0x38, 0xc9)
grad = Image.new("RGBA", (S, S))
gd = ImageDraw.Draw(grad)
for y in range(S):
    t = (y / (S - 1)) ** 0.85
    c = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
    gd.line([(0, y), (S, y)], fill=c + (255,))

mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.235), fill=255)
img.paste(grad, (0, 0), mask)

d = ImageDraw.Draw(img)

# 上部柔光
hl = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(hl).ellipse([-S * 0.30, -S * 0.85, S * 1.10, S * 0.30],
                           fill=(255, 255, 255, 30))
img.alpha_composite(hl)
d = ImageDraw.Draw(img)

W = (255, 255, 255, 255)

# ── 音符（手绘：符头 + 符干 + 符尾）
hx, hy = S * 0.335, S * 0.640      # 符头中心
hrx, hry = S * 0.108, S * 0.078    # 符头半径
d.ellipse([hx - hrx, hy - hry, hx + hrx, hy + hry], fill=W)

stem_x = hx + hrx * 0.80
stem_w = S * 0.040
stem_top = hy - S * 0.470
d.rectangle([stem_x - stem_w / 2, stem_top, stem_x + stem_w / 2, hy], fill=W)

# 符尾（两条弧线）
d.arc([stem_x - S * 0.020, stem_top - S * 0.010, stem_x + S * 0.215, stem_top + S * 0.230],
      start=270, end=20, fill=W, width=int(S * 0.042))
d.arc([stem_x - S * 0.020, stem_top + S * 0.145, stem_x + S * 0.175, stem_top + S * 0.385],
      start=270, end=20, fill=W, width=int(S * 0.038))

# ── 右下角开着的锁
lx, ly = S * 0.605, S * 0.600
lw, lh = S * 0.275, S * 0.235
d.rounded_rectangle([lx, ly + lh * 0.42, lx + lw, ly + lh * 1.42],
                    radius=int(lw * 0.20), fill=W)
d.arc([lx + lw * 0.13, ly - lh * 0.06, lx + lw * 0.87, ly + lh * 0.86],
      start=195, end=345, fill=W, width=int(S * 0.030))
d.ellipse([lx + lw * 0.40, ly + lh * 0.70, lx + lw * 0.60, ly + lh * 0.92],
          fill=(0x45, 0x38, 0xc9, 255))

img.save(r"app_icon.png")
img.resize((256, 256), Image.LANCZOS).save(
    r"app.ico", format="ICO",
    sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print("icon done")
