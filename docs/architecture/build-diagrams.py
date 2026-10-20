#!/usr/bin/env python3
"""Build editable SVG and diagrams.net XML from the same layout.

Run with Python 3.10+: python build-diagrams.py
PNG export: open the SVG in a vector editor, or use Sharp / librsvg at 2x.
All coordinates are in a 1600 × 900, 16:9 canvas. No network access is used.
"""
from pathlib import Path
import html
import json
import xml.etree.ElementTree as ET
from urllib.parse import quote

OUT = Path(__file__).resolve().parent
W, H = 1600, 900
C = dict(ink="#172B3A", muted="#526575", line="#8A9EAE",
         pink="#FCEEF0", pinkline="#E6B9C2",
         blue="#EDF5FC", blueline="#B6D2E8",
         green="#EEF7F0", greenline="#B8D7C0",
         neutral="#F7F9FB", border="#D4DFE7", white="#FFFFFF",
         rose="#A34D67", azure="#256C9F", forest="#3A8058")

# Original outline pictograms. Each stays vector-based in SVG and draw.io.
ICONS = {
    "people": '<circle cx="8" cy="6" r="3"/><circle cx="18" cy="8" r="2.5"/><path d="M2 21v-3a6 6 0 0 1 12 0v3M16 15a4 4 0 0 1 6 3v3"/>',
    "laptop": '<rect x="3" y="3" width="18" height="14" rx="2"/><path d="M1 21h22M9 7l-3 3 3 3m6-6 3 3-3 3"/>',
    "network": '<circle cx="5" cy="5" r="3"/><circle cx="19" cy="5" r="3"/><circle cx="12" cy="20" r="3"/><path d="M8 5h8M6 8l5 9m7-9-5 9"/>',
    "book": '<path d="M12 5c-3-2-6-3-10-2v17c4-1 7 0 10 2 3-2 6-3 10-2V3c-4-1-7 0-10 2zm0 0v17"/>',
    "database": '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 4 18 4 18 0V5M3 12c0 4 18 4 18 0"/>',
    "cube": '<path d="M12 2 22 7v11l-10 5-10-5V7zm0 10L2 7m10 5 10-5M12 12v11M7 4.5l10 5"/>',
    "server": '<rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><path d="M12 6h6M12 18h6"/><circle cx="6" cy="6" r="1"/><circle cx="6" cy="18" r="1"/>',
    "browser": '<rect x="2" y="3" width="20" height="18" rx="2"/><path d="M2 8h20M5 5.5h.1M8 5.5h.1M11 5.5h.1"/>',
    "branch": '<circle cx="6" cy="4" r="2"/><circle cx="6" cy="20" r="2"/><circle cx="19" cy="4" r="2"/><path d="M6 6v12m13-12v3c0 6-13 3-13 9"/>',
    "chat": '<path d="M4 3h16a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2h-7l-6 4v-4H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zM7 8h10M7 12h7"/>',
    "search": '<circle cx="10" cy="10" r="7"/><path d="m15 15 7 7"/>',
    "cloud": '<path d="M6 20a5 5 0 0 1-1-10 7 7 0 0 1 13-3 6.5 6.5 0 0 1 0 13z"/>',
    "check": '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="m7 12 3 3 7-7"/>',
    "file": '<path d="M5 2h9l5 5v15H5zM14 2v6h5M8 13h8M8 17h6"/>',
}


def icon_svg(symbol, color):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24">'
            f'<g fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
            f'{ICONS[symbol]}</g></svg>')


class Diagram:
    def __init__(self, name, title, subtitle):
        self.name, self.items = name, []
        self.text(40, 36, title, 36, bold=True)
        self.text(42, 83, subtitle, 20, color=C["muted"])
        self.text(1326, 52, "TASTEBRIDGE / MS2", 17, bold=True, color=C["muted"])

    def rect(self, id, x, y, w, h, fill="white", stroke="border", radius=14,
             dashed=False, background=False):
        self.items.append(dict(kind="rect", id=id, x=x, y=y, w=w, h=h,
                               fill=C.get(fill, fill), stroke=C.get(stroke, stroke),
                               radius=radius, dashed=dashed, background=background))

    def text(self, x, y, text, size=20, bold=False, color=None, width=None,
             align="left"):
        self.items.append(dict(kind="text", id=f"text-{len(self.items)}", x=x, y=y,
                               text=text, size=size, bold=bold, color=color or C["ink"],
                               width=width, align=align))

    def card(self, id, x, y, w, h, title, lines=(), fill="white", stroke="border",
             title_size=23, body_size=18, gap=25, dashed=False, icon=None,
             accent="azure", body_offset=None):
        self.rect(id, x, y, w, h, fill, stroke, dashed=dashed)
        compact = h <= 56
        if icon:
            self.icon(id + "-icon", x + 17, y + (13 if compact else 16),
                      icon, 26 if compact else 32, accent)
        tx = x + (55 if compact else 62) if icon else x + 18
        self.text(tx, y + (15 if compact else 19), title, title_size, bold=True,
                  width=x+w-16-tx)
        body_offset = body_offset if body_offset is not None else (57 if icon else 49)
        for i, line in enumerate(lines):
            self.text(x + 18, y + body_offset + gap * i, line, body_size,
                      color=C["muted"], width=w - 36)

    def icon(self, id, x, y, symbol, size=32, color="azure"):
        self.items.append(dict(kind="icon", id=id, x=x, y=y, size=size,
                               symbol=symbol, color=C.get(color, color)))

    def edge(self, id, points, double=False, dashed=False, label=None,
             label_xy=None, color=None, weight=2):
        self.items.append(dict(kind="edge", id=id, points=points, double=double,
                               dashed=dashed, color=C.get(color, color) or C["line"],
                               weight=weight))
        if label:
            x, y = label_xy
            self.text(x, y, label, 16, color=C["muted"])

    def save(self):
        # Backgrounds first, followed by connectors, cards, then labels.
        ordered = sorted(self.items, key=lambda i: 0 if i.get("background") else
                         1 if i["kind"] == "edge" else 2 if i["kind"] == "rect" else 3)
        svg = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc">',
            f'<title id="title">{html.escape(self.name.replace("-", " ").title())} — TasteBridge</title>',
            '<desc id="desc">Source-grounded architecture of the implemented TasteBridge MS2 system. See architecture-notes.md for evidence and planned features.</desc>',
            '<rect width="1600" height="900" fill="white"/>'
        ]
        for color in sorted({i["color"] for i in self.items if i["kind"] == "edge"}):
            svg.append(f'<defs><marker id="arrow-{color[1:]}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M1 1 L9 5 L1 9" fill="none" stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></marker></defs>')
        for i in ordered:
            if i["kind"] == "rect":
                dash = ' stroke-dasharray="7 5"' if i["dashed"] else ""
                svg.append(f'<rect id="{i["id"]}" x="{i["x"]}" y="{i["y"]}" width="{i["w"]}" height="{i["h"]}" rx="{i["radius"]}" fill="{i["fill"]}" stroke="{i["stroke"]}" stroke-width="1.5"{dash}/>')
            elif i["kind"] == "edge":
                path = " ".join(("M" if n == 0 else "L") + f"{p[0]} {p[1]}"
                                for n, p in enumerate(i["points"]))
                dash = ' stroke-dasharray="7 5"' if i["dashed"] else ""
                marker = f"arrow-{i['color'][1:]}"
                start = f' marker-start="url(#{marker})"' if i["double"] else ""
                svg.append(f'<path id="{i["id"]}" d="{path}" fill="none" stroke="{i["color"]}" stroke-width="{i["weight"]}" stroke-linejoin="round" marker-end="url(#{marker})"{start}{dash}/>')
            elif i["kind"] == "icon":
                svg.append(f'<g id="{i["id"]}" transform="translate({i["x"]} {i["y"]}) scale({i["size"]/24})" fill="none" stroke="{i["color"]}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{ICONS[i["symbol"]]}</g>')
            else:
                svg.append(f'<text x="{i["x"]}" y="{i["y"] + i["size"]}" font-family="Arial, Helvetica, sans-serif" font-size="{i["size"]}" font-weight="{700 if i["bold"] else 400}" fill="{i["color"]}">{html.escape(i["text"])}</text>')
        svg.append("</svg>")
        (OUT / f"{self.name}.svg").write_text("\n".join(svg), encoding="utf-8")

        mx = ET.Element("mxfile", host="app.diagrams.net", version="24.7.17",
                        type="device")
        page = ET.SubElement(mx, "diagram", name=self.name.replace("-", " ").title(),
                             id=self.name)
        model = ET.SubElement(page, "mxGraphModel", dx=str(W), dy=str(H), grid="1",
                              gridSize="10", guides="1", tooltips="1", connect="1",
                              arrows="1", fold="1", page="1", pageScale="1",
                              pageWidth=str(W), pageHeight=str(H), math="0",
                              shadow="0", background="#FFFFFF")
        root = ET.SubElement(model, "root")
        ET.SubElement(root, "mxCell", id="0")
        ET.SubElement(root, "mxCell", id="1", parent="0")
        for i in ordered:
            if i["kind"] == "edge":
                pts = i["points"]
                style = ("edgeStyle=none;rounded=0;html=1;endArrow=open;endFill=0;"
                         f"strokeWidth={i['weight']};strokeColor={i['color']};"
                         f"startArrow={'open' if i['double'] else 'none'};startFill=0;"
                         f"dashed={int(i['dashed'])};")
                cell = ET.SubElement(root, "mxCell", id=i["id"], value="",
                                     style=style, parent="1", edge="1")
                geo = ET.SubElement(cell, "mxGeometry", relative="1", **{"as": "geometry"})
                for p, typ in [(pts[0], "sourcePoint"), (pts[-1], "targetPoint")]:
                    ET.SubElement(geo, "mxPoint", x=str(p[0]), y=str(p[1]), **{"as": typ})
                if len(pts) > 2:
                    arr = ET.SubElement(geo, "Array", **{"as": "points"})
                    for x, y in pts[1:-1]:
                        ET.SubElement(arr, "mxPoint", x=str(x), y=str(y))
            elif i["kind"] == "rect":
                style = (f"rounded=1;arcSize=12;whiteSpace=wrap;html=1;fillColor={i['fill']};"
                         f"strokeColor={i['stroke']};strokeWidth=1.5;dashed={int(i['dashed'])};")
                cell = ET.SubElement(root, "mxCell", id=i["id"], value="", style=style,
                                     parent="1", vertex="1")
                ET.SubElement(cell, "mxGeometry", x=str(i["x"]), y=str(i["y"]),
                              width=str(i["w"]), height=str(i["h"]), **{"as": "geometry"})
            elif i["kind"] == "icon":
                uri = "data:image/svg+xml," + quote(icon_svg(i["symbol"], i["color"]), safe="")
                cell = ET.SubElement(root, "mxCell", id=i["id"], value="",
                                     style=f"shape=image;imageAspect=0;aspect=fixed;image={uri};",
                                     parent="1", vertex="1")
                ET.SubElement(cell, "mxGeometry", x=str(i["x"]), y=str(i["y"]),
                              width=str(i["size"]), height=str(i["size"]), **{"as": "geometry"})
            else:
                style = (f"text;html=0;strokeColor=none;fillColor=none;align=left;verticalAlign=top;"
                         f"whiteSpace=wrap;rounded=0;fontFamily=Arial;fontSize={i['size']};"
                         f"fontStyle={1 if i['bold'] else 0};fontColor={i['color']};spacing=0;")
                cell = ET.SubElement(root, "mxCell", id=i["id"], value=i["text"],
                                     style=style, parent="1", vertex="1")
                ET.SubElement(cell, "mxGeometry", x=str(i["x"]), y=str(i["y"]),
                              width=str(i["width"] or min(W-i["x"]-20, len(i["text"])*i["size"]*.65)),
                              height=str(i["size"]*1.5), **{"as": "geometry"})
        ET.indent(mx)
        ET.ElementTree(mx).write(OUT / f"{self.name}.drawio", encoding="utf-8",
                                xml_declaration=True)
        return self.items


def solution():
    d = Diagram("solution-architecture", "Solution architecture",
                "Find a book you both want to read.")
    for id, y, h, fill, stroke in [
        ("process", 123, 145, "pink", "pinkline"),
        ("execution", 284, 326, "blue", "blueline"),
        ("state", 627, 224, "green", "greenline")]:
        d.rect(id, 30, y, 1540, h, fill, stroke, background=True)
    d.icon("people-layer-icon", 50, 145, "people", 34, "rose")
    d.text(50, 187, "PROCESS", 21, True)
    d.text(50, 217, "People", 18, color=C["muted"])
    d.icon("code-layer-icon", 50, 311, "laptop", 34)
    d.text(50, 354, "EXECUTION", 21, True)
    d.text(50, 384, "Code", 18, color=C["muted"])
    d.icon("state-layer-icon", 50, 666, "database", 34, "forest")
    d.text(50, 708, "STATE", 21, True)
    d.text(50, 738, "Source, Data,", 18, color=C["muted"])
    d.text(50, 763, "Models", 18, color=C["muted"])
    d.card("developers", 250, 157, 210, 80, "Developers", ["Build · test"], stroke="pinkline",
           title_size=21, icon="laptop", accent="rose", body_offset=52)
    d.card("ml-team", 490, 157, 505, 80, "Data & ML team",
           ["Prepare · train · evaluate"], stroke="pinkline", icon="network", accent="rose", body_offset=52)
    d.card("readers", 1030, 157, 510, 80, "Two readers",
           ["Choose 5 favorites each → find a shared read"], stroke="pinkline", icon="people", accent="rose", body_offset=52)
    for id, x, w in [("development-group", 240, 230), ("data-model-group", 480, 525),
                     ("reader-app-group", 1020, 530)]:
        d.rect(id, x, 300, w, 297, "#F7FBFF", "#D7E5EF", background=True)
    d.text(250, 312, "DEVELOPMENT", 15, True, color=C["muted"])
    d.text(490, 312, "DATA & MODEL WORKFLOWS", 15, True, color=C["muted"])
    d.text(1030, 312, "READER APPLICATION", 15, True, color=C["muted"])
    d.card("build", 250, 350, 210, 132, "Build & test",
           ["Code · containers", "Run checks"], stroke="blueline", title_size=21, icon="check")
    d.card("prep", 490, 350, 220, 112, "Prepare data",
           ["Collect · clean · version"], stroke="blueline", title_size=21, body_size=17, icon="database")
    d.card("models", 760, 350, 235, 112, "Baselines",
           ["Compare B0 · B1 · B2", "Export B2 ALS"], stroke="blueline", title_size=22, icon="network", body_offset=55)
    d.card("text-retrieval", 490, 500, 505, 82, "Offline text retrieval",
           ["Descriptions → vectors → index → query"],
           stroke="blueline", title_size=22, body_size=18, icon="search", body_offset=53)
    d.card("frontend", 1030, 350, 225, 112, "Web app",
           ["Pick 5 books each", "Explore 5 shared reads"], stroke="blueline", title_size=23, icon="browser", body_offset=55)
    d.card("backend", 1310, 350, 230, 132, "Book API",
           ["Search · rank · explain", "Save shared feedback"],
           stroke="blueline", title_size=23, body_size=17, icon="server")
    for id, x, w, title, line, icon in [
        ("git", 250, 210, "Source", "Code + evidence", "branch"),
        ("datasets", 490, 220, "Datasets", "Raw + processed", "database"),
        ("text-index", 760, 235, "Text index", "Vectors + index", "search"),
        ("model-files", 1030, 225, "ALS model", "Factors · books · map", "cube"),
        ("feedback", 1310, 230, "Feedback", "Shared votes", "chat")]:
        d.card(id, x, 719, w, 106, title, [line], stroke="greenline",
               title_size=22, body_size=17, icon=icon, accent="forest", body_offset=64)
    d.edge("dev-build", [(355, 237), (355, 300)])
    d.edge("ml-data", [(742, 237), (742, 300)])
    d.edge("reader-interface", [(1142, 237), (1142, 300)], double=True, color="azure", weight=3)
    d.edge("tables-to-models", [(710, 406), (760, 406)])
    d.edge("books-to-encoder", [(600, 462), (600, 500)])
    d.edge("app-api", [(1255, 406), (1310, 406)], double=True,
           label="API", label_xy=(1269, 379), color="azure", weight=3)
    d.edge("source-build", [(355, 719), (355, 482)],
           label="source", label_xy=(367, 648))
    d.edge("data-store", [(490, 416), (475, 416), (475, 682), (600, 682), (600, 719)],
           double=True, label="read / write", label_xy=(505, 650))
    d.edge("index-retrieval", [(877, 582), (877, 719)], double=True,
           label="index / query", label_xy=(770, 650))
    d.edge("export-model", [(995, 430), (1012, 430), (1012, 686), (1100, 686), (1100, 719)],
           label="export", label_xy=(1020, 651))
    d.edge("load-model", [(1190, 719), (1190, 659), (1425, 659), (1425, 482)],
           label="load model", label_xy=(1270, 633), color="forest", weight=2.5)
    d.edge("save-feedback", [(1508, 482), (1508, 719)],
           label="save", label_xy=(1465, 690))
    d.text(42, 866, "Current implementation · Text retrieval remains offline.",
           16, color=C["muted"])
    return d


def technical():
    d = Diagram("technical-architecture", "Technical architecture",
                "Local app · Offline ML · Versioned cloud storage")
    d.rect("local", 30, 128, 1095, 724, "neutral", "border", background=True)
    d.icon("local-environment-icon", 50, 143, "laptop", 28)
    d.text(90, 143, "DEVELOPER MACHINE", 21, True)
    d.text(50, 174, "Git · DVC CLI · Make · Docker Compose", 19, color=C["muted"])
    d.text(1180, 139, "EXTERNAL SERVICES", 21, True)
    d.rect("app-group", 52, 227, 1048, 285, "blue", "blueline", background=True)
    d.text(72, 242, "01   CONNECTED APP", 19, True, color=C["azure"])
    d.card("browser", 80, 299, 180, 120, "Browser",
           ["Version A", "HTML · CSS · JS"], stroke="blueline", title_size=22, icon="browser")
    d.card("node", 370, 299, 230, 120, "Node.js 24",
           ["UI + /api proxy", "Container :8080"], stroke="blueline", body_size=18, icon="server")
    d.card("fastapi", 720, 299, 355, 120, "FastAPI + Uvicorn",
           ["ALS ranking · :9000", "Search · explain · feedback"],
           stroke="blueline", body_size=18, icon="network")
    d.card("artifact-files", 370, 445, 360, 52, "ALS export",
           [], fill="green", stroke="greenline", title_size=19, icon="cube", accent="forest")
    d.text(548, 462, "JSON + NPY", 17, color=C["muted"])
    d.card("feedback-volume", 815, 445, 260, 52, "Feedback · JSONL",
           [], fill="green", stroke="greenline", title_size=18, icon="chat", accent="forest")
    d.edge("browser-http", [(260, 358), (370, 358)], double=True,
           label="HTTP :4176", label_xy=(269, 329), color="azure", weight=3)
    d.edge("proxy-http", [(600, 358), (720, 358)], double=True,
           label="HTTP :9000", label_xy=(614, 329), color="azure", weight=3)
    d.edge("startup-load", [(700, 445), (700, 433), (790, 433), (790, 419)],
           label="read-only mount", label_xy=(564, 420), color="forest", weight=2.5)
    d.edge("feedback-write", [(962, 419), (962, 445)])
    d.rect("jobs", 52, 566, 1048, 152, "blue", "blueline", background=True)
    d.text(72, 581, "02   OFFLINE ML JOBS", 19, True, color=C["azure"])
    d.card("data-jobs", 80, 626, 260, 82, "Data pipeline",
           ["Ingest → preprocess"], stroke="blueline", title_size=22, body_size=18, icon="database", body_offset=53)
    d.card("model-jobs", 390, 626, 310, 82, "Train + evaluate",
           ["B0 · B1 · B2 ALS"], stroke="blueline", title_size=22, body_size=18, icon="network", body_offset=53)
    d.card("embedding-job", 750, 626, 325, 82, "Text retrieval",
           ["MiniLM → Chroma → query"], stroke="blueline", title_size=22, body_size=18, icon="search", body_offset=53)
    d.rect("disk", 80, 751, 995, 76, "green", "greenline")
    d.icon("local-data-icon", 98, 766, "database", 32, "forest")
    d.text(145, 761, "Local data + models", 22, True)
    d.text(145, 795, "Raw files · Parquet · Chroma · ALS artifacts", 18,
           color=C["muted"], width=900)
    d.edge("data-disk", [(210, 708), (210, 751)], double=True)
    d.edge("model-disk", [(545, 751), (545, 708)], double=True)
    d.edge("text-disk", [(910, 751), (910, 708)], double=True)
    d.edge("model-export", [(545, 626), (545, 497)])
    d.text(554, 505, "B2 export", 16, color=C["muted"])
    d.card("github", 1180, 184, 390, 103, "GitHub",
           ["Code · DVC pointers · evidence"], title_size=24, icon="branch")
    d.edge("git-sync", [(1125, 202), (1150, 202), (1150, 235), (1180, 235)],
           double=True)
    d.text(1094, 174, "Git", 16, color=C["muted"])
    d.card("goodreads", 1180, 315, 390, 88, "UCSD Goodreads",
           ["Books + reader interactions"], title_size=24, icon="book")
    d.card("hugging-face", 1180, 429, 390, 88, "Hugging Face",
           ["Pinned MiniLM encoder"], title_size=24, icon="cube")
    d.edge("goodreads-download", [(1180, 359), (1147, 359), (1147, 543), (65, 543), (65, 663), (80, 663)])
    d.text(905, 517, "HTTPS download", 16, color=C["muted"])
    d.edge("weights-build", [(1180, 474), (1133, 474), (1133, 557), (910, 557), (910, 626)],
           dashed=True)
    d.text(935, 582, "build-time weights", 15, color=C["muted"])
    d.rect("gcp-boundary", 1180, 579, 390, 273, "neutral", "border", background=True)
    d.text(1200, 595, "GOOGLE CLOUD", 20, True)
    d.card("gcs", 1200, 643, 350, 182, "Cloud Storage",
           ["gs://tastebridge-dvc", "Versioned data + models", "DVC pull / push"],
           fill="green", stroke="greenline", title_size=25, body_size=18, gap=33,
           icon="cloud", accent="forest")
    d.edge("dvc-sync", [(1075, 790), (1148, 790), (1148, 741), (1200, 741)], double=True)
    d.text(1087, 803, "DVC", 16, color=C["muted"])
    d.text(42, 866, "Solid: runtime / files   ·   Dashed: image-build download   ·   Planned work: see notes.",
           16, color=C["muted"])
    return d


if __name__ == "__main__":
    layouts = {d.name: d.save() for d in (solution(), technical())}
    (OUT / "diagram-layout.json").write_text(json.dumps(layouts, indent=2) + "\n")
    print("Wrote 2 SVGs, 2 editable draw.io diagrams and layout JSON.")
