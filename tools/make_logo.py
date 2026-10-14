"""Original scruffy-mutt + Wi-Fi logo generator (seeded, so reproducible)."""
import math
import random


def shaggy(cx, cy, rx, ry, n, spike, seed, rot=0.0, droop=0.45, top_boost=0.0,
           start=0.0, end=2 * math.pi, close=True, extra=""):
    """Outline made of curved, drooping hair locks around an ellipse."""
    rnd = random.Random(seed)

    def rotp(x, y):
        return (cx + x * math.cos(rot) - y * math.sin(rot), cy + x * math.sin(rot) + y * math.cos(rot))

    def base(t):
        return math.cos(t) * rx, math.sin(t) * ry

    path = []
    for k in range(n + (0 if close else 0)):
        t0 = start + (end - start) * k / n
        t1 = start + (end - start) * (k + 1) / n
        tm = (t0 + t1) / 2 + rnd.uniform(-0.25, 0.25) * (t1 - t0)
        boost = 1 + top_boost * max(0.0, -math.sin(tm))
        d = spike * rnd.uniform(0.45, 1.3) * boost
        # tip direction: outward normal bent toward "down" so hair hangs
        nx, ny = math.cos(tm), math.sin(tm)
        dx, dy = nx * (1 - droop), ny * (1 - droop) + droop
        ln = math.hypot(dx, dy) or 1
        dx, dy = dx / ln, dy / ln
        bx0, by0 = base(t0)
        bx1, by1 = base(t1)
        mx, my = base(tm)
        tip = (mx + dx * d, my + dy * d)
        c1 = (mx + nx * d * 0.55 - (bx1 - bx0) * 0.15, my + ny * d * 0.55 - (by1 - by0) * 0.15)
        c2 = (mx + nx * d * 0.10 + (bx1 - bx0) * 0.20, my + ny * d * 0.10 + (by1 - by0) * 0.20)
        if k == 0:
            path.append("M%.1f %.1f" % rotp(bx0, by0))
        path.append("Q%.1f %.1f %.1f %.1f" % (*rotp(*c1), *rotp(*tip)))
        path.append("Q%.1f %.1f %.1f %.1f" % (*rotp(*c2), *rotp(bx1, by1)))
    return " ".join(path) + extra + (" Z" if close else "")


def svg(body, ear, beard, dark, wifi):
    ear_l = shaggy(52, 150, 20, 44, 8, 9, 11, rot=0.38, droop=0.7)
    ear_r = shaggy(172, 150, 20, 44, 8, 9, 12, rot=-0.38, droop=0.7)
    head = shaggy(112, 122, 58, 56, 19, 14, 3, top_boost=0.6, droop=0.35)
    chest = shaggy(112, 244, 60, 54, 14, 10, 7, droop=0.7)
    beard_p = shaggy(112, 166, 30, 28, 11, 10, 5, droop=0.8)
    brow_l = shaggy(90, 109, 14, 7, 5, 7, 21, rot=-0.3, droop=0.5)
    brow_r = shaggy(134, 109, 14, 7, 5, 7, 22, rot=0.3, droop=0.5)
    fringe = shaggy(112, 84, 30, 14, 7, 12, 31, droop=0.75)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">
  <!-- original artwork: scruffy mutt + Wi-Fi arcs (not the Ruckus mark) -->
  <g fill="none" stroke="{wifi}" stroke-width="12" stroke-linecap="round">
    <path d="M198 42 a26 26 0 0 1 26 26"/>
    <path d="M198 16 a52 52 0 0 1 52 52"/>
  </g>
  <circle cx="198" cy="68" r="8" fill="{wifi}"/>
  <g fill="{body}" stroke="{body}" stroke-width="1.5" stroke-linejoin="round">
    <path d="{chest}"/>
    <rect x="80" y="160" width="64" height="60"/>
    <path d="{head}"/>
    <path d="{fringe}"/>
  </g>
  <g fill="{ear}" stroke="{ear}" stroke-width="1.5" stroke-linejoin="round">
    <path d="{ear_l}"/>
    <path d="{ear_r}"/>
  </g>
  <g fill="{beard}" stroke="{beard}" stroke-width="1.5" stroke-linejoin="round">
    <path d="{beard_p}"/>
    <path d="{brow_l}"/>
    <path d="{brow_r}"/>
  </g>
  <circle cx="92" cy="125" r="7" fill="{dark}"/>
  <circle cx="132" cy="125" r="7" fill="{dark}"/>
  <circle cx="94.3" cy="122.7" r="2" fill="#ffffff"/>
  <circle cx="134.3" cy="122.7" r="2" fill="#ffffff"/>
  <path d="M101 147 Q112 139 123 147 Q123 157 112 161 Q101 157 101 147 Z" fill="{dark}"/>
  <path d="M112 161 L112 170 M103 174 Q112 180 121 174" fill="none" stroke="{dark}" stroke-width="3" stroke-linecap="round"/>
</svg>
'''


open("/l/icon.svg", "w").write(svg("#1F3A5F", "#2F6496", "#C9D6E3", "#0E1A26", "#12A594"))
open("/l/dark_icon.svg", "w").write(svg("#E3EAF1", "#AFC2D6", "#6F87A1", "#0E1A26", "#3DDBC9"))
