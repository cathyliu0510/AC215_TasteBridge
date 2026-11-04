#!/usr/bin/env python3
"""Make a browser review of this deck's native DrawingML geometry. Not a PowerPoint renderer."""
import argparse
import base64
import html
from pathlib import Path, PurePosixPath
import posixpath
import xml.etree.ElementTree as E
import zipfile

N = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main",
     "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
     "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
EMU_PER_PX = 9525


def geometry(node):
    offset, extent = node.find("a:off", N), node.find("a:ext", N)
    values = [int(offset.get("x")), int(offset.get("y")), int(extent.get("cx")), int(extent.get("cy"))]
    x, y, width, height = [v / EMU_PER_PX for v in values]
    return f"left:{x}px;top:{y}px;width:{width}px;height:{height}px"


def color(node, fallback="#223331"):
    if node is None:
        return fallback
    value = node.find("a:solidFill/a:srgbClr", N)
    return "#" + value.get("val") if value is not None else fallback


def paragraphs(body, cell=False):
    output = []
    for paragraph in body.findall("a:p", N):
        spans = []
        for run in paragraph.findall("a:r", N):
            style = run.find("a:rPr", N)
            font = style.find("a:latin", N).get("typeface")
            size = int(style.get("sz", "1800")) / 75
            spans.append(f'<span style="font-family:{html.escape(font)};font-size:{size}px;color:{color(style)};font-weight:{700 if style.get("b")=="1" else 400}">{html.escape(run.findtext("a:t",default="",namespaces=N))}</span>')
        output.append('<p style="margin:0 0 ' + ('0' if cell else '9.333px') + ';line-height:1.1">' + ''.join(spans) + '</p>')
    return ''.join(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pptx", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Use a new preview output path")
    with zipfile.ZipFile(args.pptx) as archive:
        sections = []
        for number in range(1, 13):
            name = f"ppt/slides/slide{number}.xml"
            root = E.fromstring(archive.read(name))
            rels = E.fromstring(archive.read(f"ppt/slides/_rels/slide{number}.xml.rels"))
            relations = {r.get("Id"): posixpath.normpath("ppt/slides/" + r.get("Target")) for r in rels}
            shapes = []
            tree = root.find("p:cSld/p:spTree", N)
            for shape in list(tree)[2:]:
                kind = shape.tag.rsplit("}", 1)[-1]
                if kind == "sp":
                    properties, body = shape.find("p:spPr", N), shape.find("p:txBody", N)
                    frame = geometry(properties.find("a:xfrm", N))
                    background = color(properties, "transparent")
                    shapes.append(f'<div class="shape" data-text-shape style="{frame};background:{background}">{paragraphs(body)}</div>')
                elif kind == "pic":
                    path = relations[shape.find("p:blipFill/a:blip", N).get("{"+N["r"]+"}embed")]
                    data = base64.b64encode(archive.read(path)).decode()
                    frame = geometry(shape.find("p:spPr/a:xfrm", N))
                    shapes.append(f'<img class="shape" style="{frame};object-fit:contain" src="data:image/jpeg;base64,{data}" alt="Actual local application evidence">')
                elif kind == "graphicFrame":
                    frame = geometry(shape.find("p:xfrm", N))
                    table = shape.find("a:graphic/a:graphicData/a:tbl", N)
                    widths = [int(c.get("w"))/EMU_PER_PX for c in table.find("a:tblGrid", N)]
                    rows = []
                    for row in table.findall("a:tr", N):
                        height = int(row.get("h"))/EMU_PER_PX
                        cells = []
                        for cell, width in zip(row.findall("a:tc", N), widths):
                            cells.append(f'<td style="width:{width}px;height:{height}px;background:{color(cell.find("a:tcPr",N))}">{paragraphs(cell.find("a:txBody",N),True)}</td>')
                        rows.append('<tr>'+''.join(cells)+'</tr>')
                    shapes.append(f'<table class="shape" style="{frame}"><tbody>'+''.join(rows)+'</tbody></table>')
                elif kind == "cxnSp":
                    frame = geometry(shape.find("p:spPr/a:xfrm", N))
                    shapes.append(f'<div class="shape flow" style="{frame}"></div>')
            sections.append(f'<section class="slide" data-slide="{number}" aria-label="Slide {number}">'+''.join(shapes)+'</section>')
    content = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TasteBridge MS3 deck review</title><style>body{margin:0;background:#dce4de;font-family:Arial;color:#223331}main{position:relative;margin:20px auto;width:1280px;height:720px}.slide{position:absolute;inset:0;background:#F1F4F1;display:none;overflow:hidden}.slide.active{display:block}.shape{position:absolute;box-sizing:border-box}.flow{border-top:2px solid #60736c}.flow:after{content:"";position:absolute;right:-1px;top:-6px;border-left:9px solid #60736c;border-top:5px solid transparent;border-bottom:5px solid transparent}table{border-collapse:collapse;table-layout:fixed}td{box-sizing:border-box;padding:5.25px 10.5px;vertical-align:middle}nav{display:flex;gap:14px;justify-content:center;align-items:center;padding:8px}button{border:1px solid #60736c;background:white;color:#223331;padding:8px 16px;font:16px Arial;border-radius:5px}#status{min-width:95px;text-align:center}aside{font-size:13px;text-align:center;color:#60736c;margin:5px}@media print{nav,aside{display:none}main{margin:0;height:auto}.slide{display:block;position:relative;break-after:page}}</style><main>' + ''.join(sections) + '</main><nav><button id="previous" aria-label="Previous slide">Previous</button><span id="status"></span><button id="next" aria-label="Next slide">Next</button></nav><aside>DrawingML browser review. Native PowerPoint/Keynote rendering remains unverified.</aside><script>let current=0;const slides=[...document.querySelectorAll(".slide")];function show(n){current=(n+slides.length)%slides.length;slides.forEach((s,i)=>s.classList.toggle("active",i===current));document.getElementById("status").textContent=`${current+1} / ${slides.length}`;}document.getElementById("previous").onclick=()=>show(current-1);document.getElementById("next").onclick=()=>show(current+1);document.addEventListener("keydown",e=>{if(e.key==="ArrowRight")show(current+1);if(e.key==="ArrowLeft")show(current-1)});show(0);</script></html>'
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(content)
    print(args.out)


if __name__ == "__main__":
    main()
