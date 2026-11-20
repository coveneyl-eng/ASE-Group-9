from svglib import SVG, PAL, SUB, INK, MUTED, header, legend

s = SVG()
header(s, "Functional Architecture", "Smart City Flood, Traffic & Event Coordination System · Group 9 · "
       "[letters] = use cases each component supports")

ARROW = "#4B5563"
TOP, BOT = 120, 1085


def col(x, w, title):
    s.rect(x, TOP, w, BOT - TOP, fill=PAL["panel"][0], stroke=PAL["panel"][1], rx=10)
    s.text(x + 16, TOP + 26, title.upper(), size=12, weight=700, fill=INK, spacing=0.8)


def lane(x, y, w, h, kind, title):
    f, st = PAL[kind]
    s.rect(x, y, w, h, fill=f, stroke="none", sw=0, rx=4, accent=st, side="left")
    s.text(x + w - 14, y + 22, title, size=13, weight=700, fill=st, anchor="end")


def source(y, lines_, h=58):
    s.rect(60, y, 230, h, fill="#FFFFFF", stroke="#C9CDD3", rx=6)
    n = len(lines_)
    for i, t in enumerate(lines_):
        s.text(76, y + h / 2 + (i - (n - 1) / 2) * 17 + 5, t, size=13)
    return y + h / 2


def agent(x, y, w, h, name, letters, kind):
    st = PAL[kind][1]
    s.rect(x, y, w, h, fill="#FFFFFF", stroke="#C9CDD3", rx=5, accent=st, side="top")
    s.text(x + 16, y + h / 2 + 6, name, size=15, weight=700)
    s.text(x + w - 12, y + h / 2 + 6, letters, size=12.5, fill=MUTED, anchor="end")


def flow(pts, label=None, lx=None, ly=None, dashed=False, anchor="middle"):
    s.path(pts, color=ARROW, sw=1.4, dashed=dashed)
    if label:
        if lx is None:
            (x1, y1), (x2, y2) = pts[-2], pts[-1]
            lx, ly = (x1 + x2) / 2, min(y1, y2) - 8
        for i, t in enumerate(label if isinstance(label, list) else [label]):
            s.text(lx, ly + i * 14, t, size=11, fill=SUB, anchor=anchor, halo=True)


# ---------- columns ----------
col(40, 270, "External data sources")
col(330, 1020, "Smart City Coordination System")
col(1374, 270, "External actors")

LX, LW = 350, 720            # agent lanes
lane(LX, 160, LW, 250, "flood", "Flood management")
lane(LX, 425, LW, 270, "traffic", "Traffic management")
lane(LX, 710, LW, 360, "event", "Event management")
cf, cs_ = PAL["comm"]
s.rect(1085, 160, 250, 910, fill=cf, stroke="none", rx=4, accent=cs_, side="left")
s.text(1321, 182, "Communication & coordination", size=13, weight=700, fill=cs_, anchor="end")

AX, AW, AH = 425, 245, 58     # left agent column
BX, BW = 790, 245             # right agent column
NX, NW = 1178, 150            # notification agent

# ---------- flood ----------
y_maps = source(178, ["Flood maps & infrastructure", "(CFRAM, LiDAR, OSM)"])
y_gauge = source(258, ["River & tide gauges,", "drainage sensors"])
y_wx = source(338, ["Weather API"])
agent(AX, 258 + 0, AW, AH, "Flood Detector", "[C, F, A]", "flood")
agent(BX, 258, BW, AH, "Flood Scope Agent", "[B, A]", "flood")
agent(AX, 338, AW, AH, "Flood Predicting Agent", "[C]", "flood")
flow([(290, y_maps), (BX + BW / 2, y_maps), (BX + BW / 2, 258)], "Flood extents & assets", lx=300, ly=y_maps - 8,
     anchor="start")
flow([(290, y_gauge), (AX, y_gauge)], "Gauge levels")
flow([(290, y_wx), (AX, y_wx)], "Weather data")
flow([(AX + AW, y_gauge), (BX, y_gauge)], ["Affected reach &", "gauge levels"], lx=(AX + AW + BX) / 2, ly=y_gauge - 22)
flow([(BX + BW / 2 - 40, 367), (BX + BW / 2 - 40, 316)], dashed=True)
s.text(BX + BW / 2 - 30, 352, "upcoming risk", size=11, fill=SUB, italic=True)
flow([(BX + BW, y_gauge), (NX, y_gauge)], ["Graded infrastructure", "(safe, caution, unsafe)"], lx=(BX + BW + NX) / 2,
     ly=y_gauge - 22)
flow([(AX + AW, 367), (BX + BW / 2 - 40, 367), (BX + BW + 30, 367), (NX, 367)], ["Predicted floods", "(upcoming risk)"],
     lx=(BX + BW + NX) / 2 + 2, ly=345, dashed=True)

# ---------- traffic ----------
y_tl = source(445, ["Traffic light locations"], h=48)
y_ts = source(515, ["Traffic sensors /", "location data"])
y_bus = source(612, ["Bus routes API"])
agent(AX, 520, AW, AH, "Traffic Monitoring Agent", "[H]", "traffic")
agent(BX, 520, BW, AH, "Traffic Control Agent", "[L, E]", "traffic")
agent(BX, 615, BW, AH, "Rerouting Agent", "[D, E]", "traffic")
flow([(290, y_tl), (BX + BW / 2, y_tl), (BX + BW / 2, 520)], "Traffic light locations", lx=300, ly=y_tl - 8,
     anchor="start")
flow([(290, 549), (AX, 549)], "Traffic data")
flow([(AX + AW, 549), (BX, 549)], "Traffic conditions")
flow([(AX + AW / 2, 578), (AX + AW / 2, 630), (BX, 630)], "Traffic conditions", lx=(AX + AW / 2 + BX) / 2 + 40, ly=622)
flow([(290, 659), (BX, 659)], "Bus routes", lx=300, ly=651, anchor="start")
flow([(BX + BW / 2, 578), (BX + BW / 2, 615)], "Optimised signal timing", lx=BX + BW / 2 + 10, ly=601, anchor="start")
flow([(BX + BW, 644), (NX, 644)], ["Updated routes", "(people and buses)"], lx=(BX + BW + NX) / 2, ly=622)

# ---------- event ----------
y_ev = source(790, ["Event calendar / API"])
agent(AX, 790, AW, AH, "Event Monitoring Agent", "[I]", "event")
s.rect(BX, 775, BW, 90, fill="#FFFFFF", stroke="#C9CDD3", rx=5, accent=PAL["event"][1], side="top")
s.text(BX + 16, 815, "Event Coordinating Agent", size=15, weight=700)
s.text(BX + 16, 838, "[J, K, M]", size=12.5, fill=MUTED)
agent(BX, 975, BW, AH, "Public Transport Agent", "[J]", "event")
flow([(290, y_ev + 29 - 29 + 0), (AX, y_ev)], "Event details")
flow([(AX + AW, y_ev), (BX, y_ev)], ["Upcoming", "event details"], lx=(AX + AW + BX) / 2, ly=y_ev - 22)
flow([(BX + BW / 2, 673), (BX + BW / 2, 775)], "Affected routes", lx=BX + BW / 2 + 10, ly=764, anchor="start")
for yy, lab in [(792, "Predicted traffic"), (820, "Public transport changes"), (848, "Crowd management plan")]:
    flow([(BX + BW, yy), (NX, yy)], lab, lx=(BX + BW + NX) / 2, ly=yy - 5)
flow([(BX + BW / 2, 865), (BX + BW / 2, 975)], "Projected event volume", lx=BX + BW / 2 + 10, ly=925, anchor="start")
flow([(BX + BW, 1004), (NX, 1004)], "Higher capacity plan", lx=(BX + BW + NX) / 2, ly=996)

# ---------- notification + actors ----------
s.rect(NX, 220, NW, 830, fill="#FFFFFF", stroke="#C9CDD3", rx=5, accent=cs_, side="top")
s.text(NX + NW / 2, 620, "Notification Agent", size=15, weight=700, anchor="middle")
s.text(NX + NW / 2, 642, "[G, F, E, D, J, M]", size=12.5, fill=MUTED, anchor="middle")

actors = ["Drivers", "Pedestrians", "Public Transport Authority", "Emergency Services", "City Authorities",
          "Event Organisers"]
ys = [200 + i * 160 for i in range(len(actors))]
BUSX = 1356
s.path([(NX + NW, 630), (BUSX, 630)], color=ARROW, sw=1.4, head="none")
s.path([(BUSX, ys[0] + 26), (BUSX, ys[-1] + 26)], color=ARROW, sw=1.4, head="none")
s.text(BUSX - 8, 470, "Notifications · route changes · alerts", size=11.5, fill=SUB, anchor="middle", rot=-90,
       halo=True)
for y, a in zip(ys, actors):
    s.rect(1394, y, 230, 52, fill="#FFFFFF", stroke="#C9CDD3", rx=6)
    s.text(1410, y + 32, a, size=14, weight=500)
    s.path([(BUSX, y + 26), (1394, y + 26)], color=ARROW, sw=1.4)

legend(s, 1135, [("flood", "Flood management"), ("traffic", "Traffic management"), ("event", "Event management"),
                 ("comm", "Communication"), ("arrow", "Information flow"), ("dash", "Predictive flow")])
s.save("page2.svg", "Functional Architecture")
