"""Tiny SVG drawing helper for the three architecture figures (vector output, A3 landscape)."""
import math
from xml.sax.saxutils import escape

W, H = 1684, 1191  # A3 landscape in PostScript points
INK, SUB, MUTED = "#1F2328", "#5B6470", "#8A929C"

PAL = {
    "flood": ("#EAF4EA", "#3E8E41"),
    "traffic": ("#E8EFF9", "#3A6BC4"),
    "event": ("#F9EBED", "#C0392B"),
    "comm": ("#FCF3E3", "#D9901A"),
    "data": ("#F1EDF9", "#7E57C2"),
    "dmz": ("#ECEEF1", "#6B7280"),
    "panel": ("#F4F5F7", "#D5D8DD"),
    "white": ("#FFFFFF", "#C9CDD3"),
}
UC = {  # use-case ellipse fills
    "blue": ("#DCEBF8", "#4A90C8"),
    "red": ("#F9DCDD", "#D9625E"),
    "green": ("#DAF3E4", "#4CAF7A"),
}


class SVG:
    def __init__(self, w=W, h=H):
        self.w, self.h = w, h
        self.body: list[str] = []
        self.markers: dict[str, str] = {}

    # ---------- primitives ----------
    def _marker(self, color: str) -> str:
        mid = "a" + color.strip("#")
        if mid not in self.markers:
            self.markers[mid] = (
                f'<marker id="{mid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
                f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{color}"/></marker>')
        return mid

    def rect(self, x, y, w, h, fill="#fff", stroke="#C9CDD3", sw=1.0, rx=6, accent=None, side="top", dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.body.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
                         f'stroke="{stroke}" stroke-width="{sw}"{d}/>')
        if accent:
            if side == "top":
                self.body.append(f'<rect x="{x}" y="{y}" width="{w}" height="3.5" fill="{accent}"/>')
            elif side == "bottom":
                self.body.append(f'<rect x="{x}" y="{y + h - 3.5}" width="{w}" height="3.5" fill="{accent}"/>')
            else:
                self.body.append(f'<rect x="{x}" y="{y}" width="4" height="{h}" fill="{accent}"/>')

    def text(self, x, y, s, size=11, weight=400, fill=INK, anchor="start", italic=False, halo=False, spacing=0, rot=0):
        style = ' font-style="italic"' if italic else ""
        hl = ' stroke="#FFFFFF" stroke-width="4" paint-order="stroke" stroke-linejoin="round"' if halo else ""
        ls = f' letter-spacing="{spacing}"' if spacing else ""
        if rot:
            ls += f' transform="rotate({rot} {x} {y})"'
        self.body.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
                         f'text-anchor="{anchor}"{style}{hl}{ls}>{escape(s)}</text>')

    def lines(self, x, y, items, size=11, lh=None, **kw):
        lh = lh or size * 1.3
        for i, s in enumerate(items):
            self.text(x, y + i * lh, s, size=size, **kw)

    def path(self, pts, color=SUB, sw=1.3, dashed=False, head="end", curve=False):
        d = f"M{pts[0][0]},{pts[0][1]} " + " ".join(f"L{x},{y}" for x, y in pts[1:])
        if curve and len(pts) == 3:
            d = f"M{pts[0][0]},{pts[0][1]} Q{pts[1][0]},{pts[1][1]} {pts[2][0]},{pts[2][1]}"
        m = self._marker(color)
        ms = ""
        if head in ("end", "both"):
            ms += f' marker-end="url(#{m})"'
        if head in ("start", "both"):
            ms += f' marker-start="url(#{m})"'
        dash = ' stroke-dasharray="6 4"' if dashed else ""
        self.body.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}"{dash}{ms} '
                         f'stroke-linejoin="round"/>')

    # ---------- UML ----------
    def usecase(self, cx, cy, label, kind="blue", rx=104, ry=31, size=11.5):
        fill, stroke = UC[kind]
        self.body.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{fill}" stroke="{stroke}" '
                         f'stroke-width="1.3"/>')
        n = len(label)
        lh = size * 1.25
        for i, s in enumerate(label):
            self.text(cx, cy + (i - (n - 1) / 2) * lh + size * 0.35, s, size=size, weight=500, anchor="middle")
        return (cx, cy, rx, ry)

    def actor(self, x, y, label, color="#4A90C8", size=11.5):
        c = color
        self.body.append(
            f'<g fill="none" stroke="{c}" stroke-width="1.6" stroke-linecap="round">'
            f'<circle cx="{x}" cy="{y - 26}" r="8" fill="{c}" fill-opacity="0.25"/>'
            f'<line x1="{x}" y1="{y - 18}" x2="{x}" y2="{y + 6}"/>'
            f'<line x1="{x - 13}" y1="{y - 9}" x2="{x + 13}" y2="{y - 9}"/>'
            f'<line x1="{x}" y1="{y + 6}" x2="{x - 10}" y2="{y + 22}"/>'
            f'<line x1="{x}" y1="{y + 6}" x2="{x + 10}" y2="{y + 22}"/></g>')
        for i, s in enumerate(label):
            self.text(x, y + 38 + i * size * 1.25, s, size=size, weight=500, anchor="middle")
        return (x, y)

    def save(self, path, title=""):
        defs = "<defs>" + "".join(self.markers.values()) + "</defs>"
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w * 1191 / 1684:.2f}pt" height="{self.h * 1191 / 1684:.2f}pt" '
               f'viewBox="0 0 {self.w} {self.h}" font-family="Inter, DejaVu Sans, sans-serif">'
               f'<title>{escape(title)}</title><rect width="100%" height="100%" fill="#FFFFFF"/>{defs}'
               + "".join(self.body) + "</svg>")
        open(path, "w").write(svg)


def ellipse_edge(uc, toward):
    """Point on a use-case ellipse boundary in the direction of `toward`."""
    cx, cy, rx, ry = uc
    dx, dy = toward[0] - cx, toward[1] - cy
    if dx == dy == 0:
        return cx, cy
    t = 1 / math.sqrt((dx / rx) ** 2 + (dy / ry) ** 2)
    return cx + dx * t, cy + dy * t


def header(svg: SVG, title: str, subtitle: str):
    svg.text(40, 58, title, size=30, weight=700)
    svg.text(40, 84, subtitle, size=14, fill=SUB)


def legend(svg: SVG, y: float, items: list[tuple[str, str]]):
    """items: (kind, label) where kind is a PAL key, 'arrow', 'dash', 'both' or 'uc:<colour>'."""
    x = 40
    for kind, label in items:
        if kind in PAL:
            f, s = PAL[kind]
            svg.rect(x, y - 10, 14, 14, fill=f, stroke=s, sw=1.4, rx=3)
            x += 22
        elif kind.startswith("uc:"):
            f, s = UC[kind[3:]]
            svg.body.append(f'<ellipse cx="{x + 12}" cy="{y - 3}" rx="12" ry="7" fill="{f}" stroke="{s}"/>')
            x += 32
        else:
            dashed = kind in ("dash", "extend", "include")
            color = {"extend": "#E07B22", "include": "#3A78B5"}.get(kind, SUB)
            svg.path([(x, y - 3), (x + 34, y - 3)], color=color, dashed=dashed,
                     head="both" if kind == "both" else ("none" if kind == "assoc" else "end"))
            x += 44
        svg.text(x, y + 1, label, size=12, fill=SUB)
        x += 9 * len(label) * 0.62 + 34
