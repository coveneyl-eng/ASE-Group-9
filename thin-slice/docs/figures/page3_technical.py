from svglib import SVG, PAL, SUB, INK, MUTED, header, legend

s = SVG()
header(s, "Technical Architecture", "Smart City Flood, Traffic & Event Coordination System · Group 9 · "
       "deployment, network and technology view")
ARROW = "#4B5563"
Y0, Y1 = 112, 968


def col(x, w, title, right=None):
    s.rect(x, Y0, w, Y1 - Y0, fill=PAL["panel"][0], stroke=PAL["panel"][1], rx=10)
    s.text(x + 16, Y0 + 26, title.upper(), size=12, weight=700, spacing=0.8)
    if right:
        s.text(x + w - 16, Y0 + 26, right.upper(), size=12, weight=700, fill=SUB, anchor="end", spacing=0.8)


def section(x, y, t):
    s.text(x, y, t.upper(), size=11, weight=700, fill=SUB, spacing=0.6)


def box(x, y, w, h, title, desc=(), accent=None, side="bottom", tsize=14):
    s.rect(x, y, w, h, fill="#FFFFFF", stroke="#C9CDD3", rx=5, accent=accent, side=side)
    s.text(x + 14, y + 24, title, size=tsize, weight=700)
    for i, d in enumerate(desc):
        s.text(x + 14, y + 42 + i * 15, d, size=11.5, fill=SUB)


def band(x, y, w, h, kind, label):
    f, st = PAL[kind]
    s.rect(x, y, w, h, fill=f, stroke="none", sw=0, rx=4, accent=st, side="left")
    s.text(x + w - 12, y + 19, label, size=12.5, weight=700, fill=st if kind != "dmz" else SUB, anchor="end")


def arrow(pts, head="end", dashed=False, label=None, lx=None, ly=None, rot=0, anchor="middle"):
    s.path(pts, color=ARROW, sw=1.4, head=head, dashed=dashed)
    if label:
        s.text(lx, ly, label, size=11, weight=600, fill=SUB, anchor=anchor, rot=rot, halo=True)


# ================= left: external & field =================
col(40, 290, "External & field")
LXB, LW = 56, 258
section(LXB, 168, "City field network · MQTT / TLS")
box(LXB, 180, LW, 58, "Sensor simulators", ["PiForge, Python: water, cameras"])
box(LXB, 262, LW, 90, "Edge gateway", ["Mosquitto MQTT broker + Python", "forwarder, local buffer, TLS 1.3",
                                        "one device near the sensors"])
arrow([(LXB + LW / 2, 238), (LXB + LW / 2, 262)])
section(LXB, 384, "Public internet · HTTPS")
apis = [("Met Éireann API", "Warnings JSON, point forecast XML"), ("OPW waterlevel.ie", "River gauges, GeoJSON, 15 min"),
        ("Marine Institute ERDDAP", "Dublin Port and Howth tide, 5 min"), ("Ticketmaster API", "Discovery API: Dublin events, venues"),
        ("NTA and TomTom APIs", "Bus GTFS-R, traffic flow, incidents")]
api_y = []
for i, (t, d) in enumerate(apis):
    y = 396 + i * 62
    box(LXB, y, LW, 52, t, [d])
    api_y.append(y + 26)
section(LXB, 732, "Static geospatial layers · batch")
box(LXB, 744, LW, 74, "Flood maps and base layers", ["OPW CFRAM extents and nodes,", "LiDAR DTM, OSM, CSO small areas"])

# ================= middle: Azure =================
col(355, 975, "Smart City coordination system", "Microsoft Azure · EU region")
IX, IW = 375, 935
# DMZ
band(IX, 150, IW, 112, "dmz", "DMZ · public edge")
dmz = [("Ingest workers", ["Python, polls 5–15 min,", "range, spike, stale checks"]),
       ("MQTT bridge", ["MQTT to Kafka", "TLS 1.3, QoS 1"]),
       ("NGINX gateway", ["Reverse proxy", "OAuth2 + JWT"]),
       ("Front Door", ["WAF, DDoS shield", "TLS termination"])]
DX = [392 + i * 227 for i in range(4)]
for x, (t, d) in zip(DX, dmz):
    box(x, 176, 215, 76, t, d)
# Kafka
s.rect(IX, 282, IW, 62, fill="#FFFFFF", stroke=INK, sw=1.6, rx=6)
s.text(IX + IW / 2 - 120, 306, "Apache Kafka event bus", size=16, weight=700, anchor="middle")
s.text(IX + IW / 2 - 6, 306, "· SASL over TLS · one topic per domain", size=13, fill=SUB)
s.text(IX + IW / 2, 330, "flood.readings · flood.events · flood.forecast · flood.impacts · event.* · traffic.*",
       size=13, weight=600, fill=PAL["flood"][1], anchor="middle")
arrow([(DX[0] + 107, 252), (DX[0] + 107, 282)])
arrow([(DX[1] + 107, 252), (DX[1] + 107, 282)])
# agent lanes
lanes = [("flood", "Flood management", [
    ("Flood Detector", ["Levels vs CFRAM node thresholds,", "gauges grouped by reach"]),
    ("Flood Scope Agent", ["Extent builder + impact engine:", "safe, caution, unsafe per asset"]),
    ("Flood Predicting Agent", ["scikit-learn level forecast,", "graded as expected impacts"])]),
    ("event", "Event management", [
        ("Event Monitoring Agent", ["Polls events calendar"]),
        ("Event Coordinating Agent", ["Crowd, traffic, parking plans,", "venue access from flood impacts"]),
        ("Public Transport Agent", ["Capacity plans from demand,", "moves stops off flooded roads"])]),
    ("traffic", "Traffic management", [
        ("Traffic Monitoring Agent", ["Congestion from TomTom flow", "and camera feeds"]),
        ("Traffic Control Agent", ["Signal timing optimiser"]),
        ("Rerouting Agent", ["Safe routes, buses and drivers;", "pgRouting avoids unsafe roads"])])]
LANE_X = [IX + i * 317.5 for i in range(3)]
for lx, (kind, title, agents) in zip(LANE_X, lanes):
    band(lx, 364, 300, 284, kind, title)
    for j, (t, d) in enumerate(agents):
        box(lx + 14, 390 + j * 86, 274, 76, t, d, accent=PAL[kind][1], side="bottom")
    arrow([(lx + 150, 344), (lx + 150, 364)], head="both")
    arrow([(lx + 150, 648), (lx + 150, 668)])
# communication
band(IX, 668, IW, 104, "comm", "Communication & coordination")
CX = [392, 704, 1016]
comm = [("Notification Agent", ["FastAPI, decides who is told", "from flood.impacts"]),
        ("Approval service", ["Role-checked official sign-off,", "incl. flood dispatch"]),
        ("WebSocket hub", ["Live updates to the portal"])]
for x, (t, d) in zip(CX, comm):
    box(x, 690, 290, 70, t, d)
# data
band(IX, 792, IW, 160, "data", "Data and secrets · private endpoints, AES-256 at rest")
data = [("Static layer loader", ["AKS CronJob: ogr2ogr,", "osm2pgsql, GDAL"]),
        ("PostgreSQL", ["PostGIS + TimescaleDB,", "impacts, audit log"]),
        ("Blob Storage", ["Backups, reports,", "CFRAM and LiDAR files"]),
        ("Key Vault", ["Secrets and TLS keys"])]
for x, (t, d) in zip(DX, data):
    box(x, 836, 215, 80, t, d, accent=PAL["data"][1], side="left")
arrow([(790, 760), (790, 836)], head="both")

# ================= right: clients & city systems =================
col(1355, 289, "Clients & city systems")
RX, RW = 1371, 257
box(RX, 176, RW, 76, "Public status map", ["Flood, event and congestion maps,", "React + TypeScript, MapLibre"])
box(RX, 392, RW, 70, "City control APIs", ["Traffic-light commands to SCATS", "sites (simulated for the slice)"])
box(RX, 602, RW, 76, "Officials' portal", ["React + TypeScript, WebSocket,", "role-based approvals"])
box(RX, 692, RW, 70, "SMS alerts", ["Drivers and pedestrians,", "SMSAPI"])
box(RX, 776, RW, 70, "Email", ["Authorities and responders,", "Gmail API"])

# ================= connections =================
# field network -> MQTT bridge (over the top)
arrow([(LXB + LW, 300), (343, 300), (343, 98), (DX[1] + 107, 98), (DX[1] + 107, 176)],
      label="MQTT / TLS", lx=DX[1] + 115, ly=141, anchor="start")
# public APIs -> ingest workers
for y in api_y:
    s.path([(LXB + LW, y), (364, y)], color=ARROW, sw=1.4, head="none")
arrow([(364, api_y[-1]), (364, 214), (DX[0], 214)], label="HTTPS", lx=359, ly=560, rot=-90)
# static layers -> loader (batch)
arrow([(LXB + LW, 781), (350, 781), (350, 876), (DX[0], 876)], dashed=True)
# Front Door -> public map
arrow([(DX[3] + 215, 214), (RX, 214)], label="HTTPS", lx=(DX[3] + 215 + RX) / 2, ly=206)
# traffic lane -> city control APIs
arrow([(LANE_X[2] + 300, 427), (RX, 427)], label="HTTPS", lx=(LANE_X[2] + 300 + RX) / 2, ly=419)
# communication -> portal, SMS, email
s.path([(CX[2] + 290, 725), (1343, 725)], color=ARROW, sw=1.4, head="none")
s.path([(1343, 640), (1343, 811)], color=ARROW, sw=1.4, head="none")
for y in (640, 727, 811):
    arrow([(1343, y), (RX, y)])
s.text(1337, 690, "HTTPS", size=11, weight=600, fill=SUB, anchor="middle", rot=-90, halo=True)

# ================= technology table =================
s.rect(40, 984, 1604, 148, fill="#FFFFFF", stroke=PAL["panel"][1], rx=10)
rows = [("Languages & frameworks", "Python 3 · FastAPI · scikit-learn · React + TypeScript · Eclipse Mosquitto · "
                                   "PiForge simulators"),
        ("Geospatial", "PostGIS · TimescaleDB · GDAL / ogr2ogr · osm2pgsql · GeoPandas · rasterio · pgRouting · "
                       "MapLibre GL"),
        ("Delivery", "Git + GitHub · GitHub Actions CI/CD · Docker · Azure Container Registry · Terraform · AKS"),
        ("Testing", "pytest · JUnit · Postman · replays of archived OPW and Marine Institute storms"),
        ("Observability", "OpenTelemetry · Prometheus + Grafana in AKS · Azure Monitor + Log Analytics")]
for i, (k, v) in enumerate(rows):
    y = 1012 + i * 26
    s.text(64, y, k.upper(), size=11, weight=700, fill=SUB, spacing=0.6)
    s.text(300, y, v, size=13.5)

legend(s, 1166, [("dmz", "DMZ"), ("flood", "Flood management"), ("event", "Event management"),
                 ("traffic", "Traffic management"), ("comm", "Communication"), ("data", "Data stores"),
                 ("arrow", "Data flow"), ("both", "Publish / subscribe"), ("dash", "Batch load")])
s.save("page3.svg", "Technical Architecture")
