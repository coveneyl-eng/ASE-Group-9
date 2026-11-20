from svglib import SVG, PAL, SUB, INK, header, legend, ellipse_edge

s = SVG()
header(s, "Use Cases", "Smart City Coordinating Agents for Public Events and Flooding · Group 9 · "
       "letters A–M match the use-case descriptions and the agents in the functional architecture")

EXT, INC, ASSOC = "#E07B22", "#3A78B5", "#4B5563"


def assoc(actor, uc, via=()):
    a = (actor[0], actor[1] - 4)
    end = ellipse_edge(uc, via[-1] if via else a)
    pts = [a] + list(via) + [end]
    s.path(pts, color=ASSOC, sw=1.2, head="none")


def rel(src, dst, label, kind, lx=None, ly=None, dx=0, dy=-6, via=None):
    p1 = ellipse_edge(src, via or dst[:2])
    p2 = ellipse_edge(dst, via or src[:2])
    s.path([p1] + ([via] if via else []) + [p2], color=EXT if kind == "extend" else INC, sw=1.3, dashed=True)
    mx, my = via if via else ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
    s.text(lx or mx + dx, ly or my + dy, f"«{kind}»", size=11, fill=EXT if kind == "extend" else INC,
           anchor="middle", halo=True)


def panel(x, y, w, h, title):
    s.rect(x, y, w, h, fill="#F6F9FD", stroke="#2F5D8A", sw=1.3, rx=8)
    s.text(x + w / 2, y + 24, title, size=14, weight=700, fill="#2F5D8A", anchor="middle")


# ======================= Scenario 1: Flooding =======================
s.text(40, 140, "Scenario 1 · Flooding", size=19, weight=700)
panel(230, 165, 440, 880, "Smart City Flood Management System")
cs = s.actor(115, 255, ["City Sensors"], "#E3B23C")
es = s.actor(115, 470, ["Emergency", "Services"], "#D9625E")
dr = s.actor(115, 690, ["Driver", "(Motorist / Bus)"], "#4CAF7A")
ci = s.actor(115, 860, ["Citizen"], "#4CAF7A")
ga = s.actor(115, 990, ["Government", "Admin"], "#4A90C8")
sat = s.actor(770, 470, ["Satellite"], "#8E6BBF")
bus = s.actor(770, 700, ["Bus API"], "#8E6BBF")
wx = s.actor(770, 950, ["Weather API"], "#8E6BBF")

A = (450, 255, 108, 32)
G = (360, 395, 104, 32)
D = (360, 565, 104, 32)
B = (548, 480, 100, 34)
E = (425, 715, 118, 32)
F = (385, 865, 108, 32)
C = (555, 970, 92, 28)

for actor, uc in [(cs, A), (es, G), (es, D), (dr, D), (dr, E), (ci, F), (ga, F), (sat, B), (bus, E), (wx, C)]:
    assoc(actor, uc)

rel(A, B, "include", "include", dx=26)
rel(G, B, "extend", "extend", dx=8, dy=-8)
rel(G, D, "extend", "extend", lx=300, ly=474)
s.text(300, 489, "(if unable to divert)", size=10.5, fill=EXT, anchor="middle", italic=True, halo=True)
rel(D, B, "extend", "extend", dx=-6, dy=-8)
rel(E, B, "extend", "extend", dx=40, dy=0)
rel(F, B, "extend", "extend", via=(612, 790), dx=-38, dy=4)
rel(F, C, "extend", "extend", dx=0, dy=-8)

s.usecase(*A[:2], ["A · Flood Detection &", "Scope Assessment"], "blue", rx=A[2], ry=A[3])
s.usecase(*G[:2], ["G · Dispatch Responders", "to Flood Zone"], "red", rx=G[2], ry=G[3])
s.usecase(*D[:2], ["D · Reroute Transport", "in Affected Area"], "red", rx=D[2], ry=D[3])
s.usecase(*B[:2], ["B · Check Infrastructure", "Within Flood Zone"], "blue", rx=B[2], ry=B[3])
s.usecase(*E[:2], ["E · Reroute Drivers Outside", "Affected Area"], "green", rx=E[2], ry=E[3])
s.usecase(*F[:2], ["F · Inform Citizens /", "Pedestrians"], "green", rx=F[2], ry=F[3])
s.usecase(*C[:2], ["C · Disaster Prediction"], "blue", rx=C[2], ry=C[3])

# divider
s.path([(842, 125), (842, 1060)], color="#D5D8DD", sw=1, head="none")

# ======================= Scenario 2: Large public event =======================
s.text(880, 140, "Scenario 2 · Large Public Event", size=19, weight=700)
panel(1060, 165, 450, 880, "Smart City Public Event Management System")
sen = s.actor(955, 255, ["Traffic & Parking", "Sensors / Cameras"], "#E3B23C")
evl = s.actor(955, 470, ["Event Listings"], "#8E6BBF")
drv = s.actor(955, 900, ["Driver"], "#4CAF7A")
emg = s.actor(1595, 235, ["Emergency", "Services"], "#D9625E")
gov = s.actor(1595, 375, ["Government", "Admin"], "#4A90C8")
bra = s.actor(1595, 520, ["City Bus", "Route API"], "#4CAF7A")
cta = s.actor(1595, 665, ["City Transportation", "Authority"], "#4CAF7A")
tl = s.actor(1595, 925, ["Traffic Light"], "#4CAF7A")

L = (1180, 255, 98, 32)
I = (1150, 470, 92, 32)
M = (1395, 300, 104, 32)
J = (1402, 470, 100, 34)
K = (1395, 640, 104, 34)
Hh = (1235, 780, 90, 28)
E2 = (1330, 925, 112, 32)

assoc(sen, L)
assoc(sen, Hh, via=[(1046, 300), (1046, 780)])
assoc(evl, I)
assoc(drv, E2)
assoc(drv, L, via=[(1032, 860), (1032, 240)])
for actor, uc in [(emg, M), (gov, M), (bra, J), (cta, J), (cta, K), (tl, E2)]:
    assoc(actor, uc)

rel(L, I, "extend", "extend", dx=34, dy=4)
rel(I, M, "include", "include", dx=-6, dy=-8)
rel(I, J, "include", "include", dx=0, dy=-10)
rel(I, K, "include", "include", dx=-10, dy=-8)
rel(K, Hh, "extend", "extend", dx=34, dy=0)
rel(Hh, E2, "extend", "extend", dx=34, dy=-2)

s.usecase(*L[:2], ["L · Monitor Parking", "Capacity"], "blue", rx=L[2], ry=L[3])
s.usecase(*I[:2], ["I · Monitor For", "Future Events"], "blue", rx=I[2], ry=I[3])
s.usecase(*M[:2], ["M · Develop Crowd", "Management / Security Plan"], "red", rx=M[2], ry=M[3])
s.usecase(*J[:2], ["J · Change Public Transport", "Volume According to Demand"], "green", rx=J[2], ry=J[3])
s.usecase(*K[:2], ["K · Predict Congestion During", "Large Public Event"], "green", rx=K[2], ry=K[3])
s.usecase(*Hh[:2], ["H · Monitor Traffic"], "blue", rx=Hh[2], ry=Hh[3])
s.usecase(*E2[:2], ["E · Reroute Drivers Outside", "Affected Area"], "green", rx=E2[2], ry=E2[3])

legend(s, 1135, [("uc:blue", "Detection & monitoring"), ("uc:red", "Emergency & security"),
                 ("uc:green", "Mobility & public information"), ("assoc", "Association"),
                 ("include", "«include»"), ("extend", "«extend»")])
s.save("page1.svg", "Use Cases")
