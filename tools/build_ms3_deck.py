#!/usr/bin/env python3
"""Build a local, editable MS3 review deck from saved evidence using installed pandoc."""
import argparse
import copy
import csv
import json
import re
from pathlib import Path
import subprocess
import xml.etree.ElementTree as E
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NS = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main",
      "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
for prefix, uri in NS.items():
    E.register_namespace(prefix, uri)
INK, SPRUCE, BLUE, PURPLE, MIST, MUTED, LINE = "223331", "315D4F", "466E87", "82647C", "F1F4F1", "60736C", "D6DFD8"
EMU = 914400


def tag(name):
    prefix, local = name.split(":")
    return "{" + NS[prefix] + "}" + local


def add(parent, name, attrs=None):
    return E.SubElement(parent, tag(name), {key: str(value) for key, value in (attrs or {}).items()})


def fill(parent, color):
    add(add(parent, "a:solidFill"), "a:srgbClr", {"val": color})


def frame(parent, x, y, width, height):
    transform = add(parent, "a:xfrm")
    add(transform, "a:off", {"x": round(x*EMU), "y": round(y*EMU)})
    add(transform, "a:ext", {"cx": round(width*EMU), "cy": round(height*EMU)})
    return transform


class Slide:
    def __init__(self, root):
        self.root = root
        self.tree = root.find("p:cSld/p:spTree", NS)
        self.pictures = [copy.deepcopy(p) for p in self.tree.findall("p:pic", NS)]
        for node in list(self.tree)[2:]:
            self.tree.remove(node)
        self.counter = 2
        csld = root.find("p:cSld", NS)
        old_bg = csld.find("p:bg", NS)
        if old_bg is not None:
            csld.remove(old_bg)
        background = E.Element(tag("p:bg"))
        fill(add(background, "p:bgPr"), MIST)
        csld.insert(0, background)

    def shape(self, name="Text"):
        shape = add(self.tree, "p:sp")
        nv = add(shape, "p:nvSpPr")
        add(nv, "p:cNvPr", {"id": self.counter, "name": name})
        add(nv, "p:cNvSpPr")
        add(nv, "p:nvPr")
        self.counter += 1
        return shape

    def text(self, text, x, y, width, height, size=22, color=INK, bold=False, font="Arial", background=None):
        shape = self.shape(text[:45])
        properties = add(shape, "p:spPr")
        frame(properties, x, y, width, height)
        add(add(properties, "a:prstGeom", {"prst": "rect"}), "a:avLst")
        if background:
            fill(properties, background)
        else:
            add(properties, "a:noFill")
        add(add(properties, "a:ln"), "a:noFill")
        body = add(shape, "p:txBody")
        body_props = add(body, "a:bodyPr", {"wrap": "square", "lIns": 0, "rIns": 0, "tIns": 0, "bIns": 0, "anchor": "t"})
        add(body_props, "a:noAutofit")
        add(body, "a:lstStyle")
        for line in text.split("\n"):
            paragraph = add(body, "a:p")
            props = add(paragraph, "a:pPr", {"marL": 0, "indent": 0})
            add(props, "a:buNone")
            add(add(props, "a:lnSpc"), "a:spcPct", {"val": 110000})
            add(add(props, "a:spcAft"), "a:spcPts", {"val": 700})
            run = add(paragraph, "a:r")
            style = add(run, "a:rPr", {"lang": "en-US", "sz": round(size*100), "b": int(bold)})
            fill(style, color)
            add(style, "a:latin", {"typeface": font})
            add(run, "a:t").text = line
            add(paragraph, "a:endParaRPr", {"lang": "en-US", "sz": round(size*100)})
        return shape

    def box(self, title, subtitle, x, y, width, color=SPRUCE):
        self.text("", x, y, width, 1.28, background="FFFFFF")
        self.text(title, x+.18, y+.18, width-.36, .44, 22, color, True)
        self.text(subtitle, x+.18, y+.75, width-.36, .35, 16, MUTED)

    def arrow(self, x, y, width):
        shape = add(self.tree, "p:cxnSp")
        nv = add(shape, "p:nvCxnSpPr")
        add(nv, "p:cNvPr", {"id": self.counter, "name": "Data flow"})
        add(nv, "p:cNvCxnSpPr")
        add(nv, "p:nvPr")
        self.counter += 1
        properties = add(shape, "p:spPr")
        frame(properties, x, y, width, .001)
        add(add(properties, "a:prstGeom", {"prst": "line"}), "a:avLst")
        line = add(properties, "a:ln", {"w": 19050})
        fill(line, MUTED)
        add(line, "a:tailEnd", {"type": "triangle", "w": "sm", "len": "sm"})

    def table(self, rows, x, y, widths, row_height=.56, size=17):
        shape = add(self.tree, "p:graphicFrame")
        nv = add(shape, "p:nvGraphicFramePr")
        add(nv, "p:cNvPr", {"id": self.counter, "name": "Editable evidence table"})
        add(nv, "p:cNvGraphicFramePr")
        add(nv, "p:nvPr")
        self.counter += 1
        transform = add(shape, "p:xfrm")
        add(transform, "a:off", {"x": round(x*EMU), "y": round(y*EMU)})
        add(transform, "a:ext", {"cx": round(sum(widths)*EMU), "cy": round(row_height*len(rows)*EMU)})
        data = add(add(shape, "a:graphic"), "a:graphicData", {"uri": NS["a"] + "/table"})
        table = add(data, "a:tbl")
        add(table, "a:tblPr", {"firstRow": 1, "bandRow": 0})
        grid = add(table, "a:tblGrid")
        for width in widths:
            add(grid, "a:gridCol", {"w": round(width*EMU)})
        for index, row in enumerate(rows):
            native_row = add(table, "a:tr", {"h": round(row_height*EMU)})
            for value in row:
                cell = add(native_row, "a:tc")
                body = add(cell, "a:txBody")
                add(body, "a:bodyPr", {"wrap": "square", "anchor": "ctr"})
                add(body, "a:lstStyle")
                paragraph = add(body, "a:p")
                props = add(paragraph, "a:pPr", {"marL": 0, "indent": 0})
                add(props, "a:buNone")
                run = add(paragraph, "a:r")
                style = add(run, "a:rPr", {"sz": round(size*100), "b": int(index == 0), "lang": "en-US"})
                fill(style, "FFFFFF" if index == 0 else INK)
                add(style, "a:latin", {"typeface": "Arial"})
                add(run, "a:t").text = str(value)
                properties = add(cell, "a:tcPr", {"marL": 100000, "marR": 100000, "marT": 50000, "marB": 50000})
                fill(properties, SPRUCE if index == 0 else ("FFFFFF" if index % 2 else "E8EFEA"))

    def picture(self, index, x, y, width, height):
        picture = self.pictures[index]
        nonvisual = picture.find("p:nvPicPr/p:cNvPr", NS)
        nonvisual.set("id", str(self.counter))
        nonvisual.set("descr", "TasteBridge local trained-synthetic integration screenshot")
        self.counter += 1
        properties = picture.find("p:spPr", NS)
        old = properties.find("a:xfrm", NS)
        if old is not None:
            properties.remove(old)
        transform = frame(properties, x, y, width, height)
        properties.remove(transform)
        properties.insert(0, transform)
        self.tree.append(picture)

    def heading(self, title, number):
        self.text(title, .65, .38, 12.0, .96, 33, font="Georgia")
        self.text(str(number), 12.15, 7.08, .45, .22, 11, MUTED)

    def fact(self, label, text, x, y, width=5.6):
        self.text(label, x, y, width, .4, 19, SPRUCE, True)
        self.text(text, x, y+.55, width, 1.05, 23)


def build(output: Path, work: Path):
    if output.exists():
        raise ValueError("Use a new output filename for each revision")
    evidence = ROOT / "docs/ms3/evidence/local-integration-20261104"
    run = evidence / "runs/run-a"
    record = json.loads((run / "run.json").read_text())
    comparison = json.loads((evidence / "runs/reproducibility.json").read_text())
    if record["status"] != "passed" or not comparison["passed"]:
        raise ValueError("Successful saved evidence is required before slide authoring")
    meta = json.loads((run / "export-meta.json").read_text())
    config = json.loads((run / "evaluation-config.json").read_text())
    examples = json.loads((run / "api-examples.json").read_text())["examples"]
    metrics = [row for row in csv.DictReader((run / "evaluation-summary.csv").open()) if row["pair_kind"] == "all"]
    test_reports = {name: (evidence / name).read_text() for name in
                    ("frontend-tests.tap", "preprocess-tests.txt", "integration-tests.txt")}
    if "# fail 0" not in test_reports["frontend-tests.tap"] or "failed" in test_reports["preprocess-tests.txt"] or not test_reports["integration-tests.txt"].rstrip().endswith("OK"):
        raise ValueError("Passing saved test reports are required before slide authoring")
    frontend_count = re.search(r"# pass (\d+)", test_reports["frontend-tests.tap"]).group(1)
    preprocess_count = re.search(r"(\d+) passed", test_reports["preprocess-tests.txt"]).group(1)
    integration_count = re.search(r"Ran (\d+) tests", test_reports["integration-tests.txt"]).group(1)
    titles = ["TasteBridge", "One export drives the API and interface", "Two clean runs reproduce the same outputs",
              "Evaluation and serving use separate fits", "The evaluator records both ranking rules",
              "The trained model reaches the Reading Desk", "The API contract checks actual responses",
              "Tests cover each integration boundary", "Cloud Run preparation is ready for operator review",
              "Production logging still needs cloud evidence", "MS3 evidence still has cloud requirements",
              "The remaining handoff has three gates"]
    timings = [45, 75, 75, 90, 75, 120, 75, 60, 75, 60, 75, 75]
    notes = [
        "Local integration review, November 4, 2026. Cloud execution, deployment and monitoring remain unverified. This deck is a review draft, not a completed MS3 submission. The existing algorithm and model modules come from the team's MS2 work. This continuation adds orchestration, reproducibility checks, contract verification and frontend provenance. Sources: docs/ms3/README.md; official MS3 https://harvard-iacs.github.io/2026-AC215/milestone3/.",
        "Trace processed tables through evaluation.export to four files, then app.artifacts and the frontend relay. The served model reads the same versioned files together. The optional text-embedding index is a separate workflow, not consumed by B2 serving. Sources: docker-compose.yml; src/evaluation/evaluation/export.py; src/backend/app/artifacts.py; frontend/prototype/scripts/serve.mjs.",
        "Both saved runs use source commit " + record["source_commit"] + ". Both working trees were clean at run start. Hash comparison covers five generated gzip files, two processed tables, item vectors, coordinates and summary.csv. Full-shelf API rankings also match. This establishes same-environment reproducibility, not cross-platform bitwise equality. Sources: docs/ms3/evidence/local-integration-20261104/runs/reproducibility.json; run-a/run.json; run-b/run.json. Initial run failed because the new verifier compared four-decimal API output at excessive precision; e8a3128 corrected the verifier and retained the failed run locally.",
        "The exporter fits all retained synthetic users for serving. The evaluator independently fits training users only, then evaluates disjoint held-out users. There are 316 training, 40 tuning and 39 test users; 23 test readers have enough catalogue likes for simulated pairs. Favorites are excluded from ranking. The local smoke uses 16 factors and 8 iterations. The previous tuned MS2 configuration remains 128 factors and 15 iterations. No model replacement or quality improvement is claimed. Sources: src/evaluation/evaluation/run.py; export.py; als.py; saved evaluation-config.json and export-meta.json.",
        "All numbers on this slide are from invented input and 20 simulated pairs. They verify metric generation and configuration coverage only. They do not rank models for Goodreads, and the local ALS smoke is not claimed to beat the baselines. Min-Recall@10 is the smaller of the two readers' hidden-like recalls. NDCG@10 averages the two readers' values. Source: saved evaluation-summary.csv and src/evaluation/evaluation/metrics.py.",
        "Demonstration: open the actual model-backed UI, choose another recommendation, inspect each reader's reference, mark both Interested, explicitly choose, then change one reader to Pass. At 320px the choice is revoked, focus returns to Review & respond and no horizontal overflow appears. Switching to average changes the five titles. The footer explicitly identifies synthetic training data. Chrome remains limited by its extension error and blank native capture; actual interaction checks use supported local HTTP in the in-app browser. Sources: trained-ui-desktop.jpg, trained-choice-320.jpg, browser-checks.json; frontend/prototype/src/a/.",
        "The JSON is the actual five-seed request saved in api-examples.json. The verifier uses two known catalogue IDs for the minimal endpoint check and additionally records full-shelf responses. It checks signed finite similarities and four-decimal serialization tolerance, correct aggregation, unique non-seed results, reader-specific reasons, matching projection IDs/positions, model identity and private-route isolation. It sends no feedback. Sources: deploy/cloud-run/smoke.py; tools/verify_local_integration.py; saved api-check.json and api-examples.json.",
        "Frontend, preprocessing and integration checks were rerun for this continuation. The unchanged backend's 77 and evaluation's 54 tests passed earlier the same day and are retained with their reports. New end-to-end training and HTTP checks ran twice after that. Test counts are not cloud evidence. Sources: docs/ms3/evidence/local-integration-20261104 test reports; docs/ms3/local-continuation-20261104/ backend and evaluation reports.",
        "This is the existing prepared Cloud Run design, not a deployed diagram. Frontend port 8080 reaches the internal API at 9000. Images keep the model private. Build and smoke require a Docker daemon and a real approved export, currently absent here. gcloud is also absent. The existing publish operator command uploads images and grants public invocation, so it requires separate explicit authorization; the course also permits teaching-staff access with an authentication arrangement discussed with the TF. Sources: deploy/cloud-run/deploy.py; Dockerfile.backend; README.md; historical verification.local.json. Historical Docker evidence is not a current live deployment check.",
        "The log excerpt is from the actual local trained-model run. Request logging records method, path, status and elapsed time. The values are examples, not a latency benchmark. Cloud Logging must still show the real service revision and an actual response/error or feedback event with access instructions. No external feedback was sent here. Sources: src/backend/app/main.py; saved backend.log; deploy/cloud-run/README.md.",
        "The official rubric asks for at least one tracked reproducible serverless training run, an automated ML workflow, deployed model/API with staff access, basic production logging, documented/tested API, code/README/screenshots and a 15-minute presentation. Local automation and logs do not replace the cloud items. All unverified cells remain explicit in the evidence index. Source: https://harvard-iacs.github.io/2026-AC215/milestone3/ and docs/ms3/evidence/index.json.",
        "First confirm the team's chosen tracking and cloud workflow and any prior cloud executions. Then the authorized operator collects real run, service and log evidence using the approved data and existing deployment package. Finally review the integrated branch, reconcile architecture PR 11, and have the authorized maintainer create/update milestone3 and submit its full hash on Canvas by November 12, 10pm ET. Security review has denied pushing this branch; no bypass or alternate remote publishing is authorized. This deck's placeholders require replacement before the graded presentation. Sources: docs/ms3/README.md; reproduce.md; official rubric."
    ]
    work.mkdir(parents=True, exist_ok=True)
    seed = work / "deck-source.md"
    manuscript = []
    for index, title in enumerate(titles):
        manuscript += ["# " + title, "", "::: notes", f"Timing: {timings[index]} seconds.", "", notes[index], ":::", ""]
        if index == 5:
            manuscript += [f"![]({evidence / 'trained-ui-desktop.jpg'})", ""]
    seed.write_text("\n".join(manuscript))
    (ROOT / "docs/ms3/presentation-source.md").write_text("\n".join(manuscript).replace(str(evidence) + "/", "evidence/local-integration-20261104/").replace(str(ROOT) + "/", ""))
    base = work / "seed.pptx"
    subprocess.run(["pandoc", str(seed), "--slide-level=1", "--to=pptx", "--output", str(base)], check=True)
    with zipfile.ZipFile(base) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    presentation = E.fromstring(parts["ppt/presentation.xml"])
    if len(presentation.find("p:sldIdLst", NS)) != 12:
        raise ValueError("The deck must contain exactly 12 slides")
    presentation.find("p:sldSz", NS).set("cx", str(12192000))
    presentation.find("p:sldSz", NS).set("cy", str(6858000))
    parts["ppt/presentation.xml"] = E.tostring(presentation, encoding="utf-8", xml_declaration=True)
    roots = [E.fromstring(parts[f"ppt/slides/slide{n}.xml"]) for n in range(1, 13)]
    # Add the second evidence image to the same slide. Pandoc otherwise creates
    # another slide for a second standalone image paragraph.
    relationships = E.fromstring(parts["ppt/slides/_rels/slide6.xml.rels"])
    rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    E.SubElement(relationships, "{" + rel_ns + "}Relationship", {
        "Id": "rIdMobile", "Type": NS["r"] + "/image", "Target": "../media/ms3-mobile.jpg"})
    parts["ppt/slides/_rels/slide6.xml.rels"] = E.tostring(relationships, encoding="utf-8", xml_declaration=True)
    parts["ppt/media/ms3-mobile.jpg"] = (evidence / "trained-choice-320.jpg").read_bytes()
    picture = copy.deepcopy(roots[5].find("p:cSld/p:spTree/p:pic", NS))
    picture.find("p:blipFill/a:blip", NS).set(tag("r:embed"), "rIdMobile")
    roots[5].find("p:cSld/p:spTree", NS).append(picture)
    slides = [Slide(root) for root in roots]
    for index, slide in enumerate(slides):
        slide.heading(titles[index], index+1)

    s = slides[0]
    s.tree.remove(list(s.tree)[2])
    s.text("TasteBridge", .8, 1.12, 11.8, 1.0, 58, font="Georgia")
    s.text("MS3 integration review", .85, 2.55, 11.6, .7, 32, SPRUCE)
    s.text("Local model-to-UI path verified", .85, 3.8, 11.6, .55, 25, bold=True)
    s.text("Cloud training, deployment and production evidence pending", .85, 4.65, 11.6, .6, 22, MUTED)
    s.text("AC215 TasteBridge team\nNovember 4, 2026", .85, 6.1, 10.8, .8, 18, MUTED)

    s = slides[1]
    s.box("Processed tables", "books + interactions", .65, 2.2, 3.25)
    s.arrow(3.98, 2.84, .7)
    s.box("B2 ALS export", "one versioned artifact folder", 4.78, 2.2, 3.25)
    s.arrow(8.1, 2.84, .7)
    s.box("API + Reading Desk", "same model identity", 8.9, 2.2, 3.75)
    s.text("books.json     item_embeddings.npy     coords_2d.npy     meta.json", .7, 4.25, 11.9, .6, 18, font="Menlo")
    s.text("The runtime checks catalogue order, vector dimensions and finite values before serving.", .7, 5.4, 11.7, 1.1, 25)

    s = slides[2]
    s.fact("Same source", record["source_commit"][:12] + "\nClean working tree at both run starts", .7, 1.7)
    s.fact("Same input identity", record["data_version"], 7.0, 1.7, 5.5)
    s.table([["Compared output", "Two-run result"], ["5 compressed raw files", "All hashes match"],
             ["2 processed tables", "Both hashes match"], ["Vectors + projection", "Both hashes match"],
             ["Metric summary + API lists", "Exact match in this environment"]], .7, 3.8, [5.6, 6.25], .49, 18)
    s.text("Seed 42. Timestamps, durations and ports may differ.", .7, 6.7, 11.8, .4, 16, MUTED)

    s = slides[3]
    s.fact("Serving fit", "395 retained synthetic readers\n160 book vectors", .7, 1.65)
    s.fact("Held-out evaluation", "316 train / 40 tune / 39 test readers\n23 eligible test readers", 7.0, 1.65, 5.5)
    s.text("9,072 processed interactions", .7, 4.1, 11.8, .7, 34, SPRUCE)
    s.text("Local smoke: 16 factors, 8 ALS iterations, regularization 50, alpha 20.\nThe evaluator fits only training readers; the serving export refits all retained readers.", .7, 5.2, 11.8, 1.25, 22)

    s = slides[4]
    rows = [["Model", "Rule", "Min-Recall@10", "NDCG@10"]]
    for row in metrics:
        rows.append([{"popularity": "B0 popularity", "item_knn": "B1 item-kNN", "als": "B2 ALS"}[row["model"]],
                     "Balance both" if row["aggregation"] == "least_misery" else "Average",
                     f"{float(row['min_recall']):.4f}", f"{float(row['mean_ndcg']):.4f}"])
    s.text("Synthetic input, 20 simulated pairs, 5 favorites each", .7, 1.55, 11.8, .55, 23, SPRUCE)
    s.table(rows, .7, 2.45, [3.25, 3.0, 2.8, 2.8], .5, 18)
    s.text("This verifies evaluation output. It provides no Goodreads quality estimate.", .7, 6.35, 11.8, .65, 19, MUTED)

    s = slides[5]
    s.picture(0, .65, 1.45, 6.1, 6.1*1182/1280)
    s.picture(1, 7.02, 1.7, 2.1, 4.2)
    s.text("160 books\nSynthetic training data", 9.5, 1.85, 3.0, 1.3, 23, SPRUCE, True)
    s.text("Actual reader references\n\nExplicit shared choice\n\nPass revokes the choice", 9.5, 3.4, 3.0, 3.0, 20)

    s = slides[6]
    request = examples[0]["request"]
    lines = ['{', '  "reader_a": ' + json.dumps(request["reader_a"]) + ',',
             '  "reader_b": ' + json.dumps(request["reader_b"]) + ',', '  "k": 5,', '  "aggregation": "least_misery"', '}']
    s.text("POST /api/recommend", .7, 1.6, 6.0, .5, 23, SPRUCE, True)
    s.text("\n".join(lines), .7, 2.5, 7.35, 2.3, 13.2, font="Menlo")
    s.text("From the saved actual request", .7, 5.15, 7.1, .5, 17, MUTED)
    s.text("5 unique non-favorite results\n\nBoth reader references\n\nFinite scores + matching coordinates\n\nCorrect model identity", 8.35, 1.6, 4.1, 4.9, 23)
    s.text("The verifier accounts for the API's four-decimal response precision.", .7, 6.35, 11.8, .6, 18, MUTED)

    s = slides[7]
    s.table([["Boundary", "Tests", "What the result establishes"],
             ["Frontend", frontend_count + " passed", "Selection, recovery, decisions, API mapping"],
             ["Preprocessing", preprocess_count + " passed", "Table contract + deterministic gzip inputs"],
             ["Local integration tools", integration_count + " passed", "Incomplete runs fail; score precision checked"],
             ["Backend / evaluation", "77 / 54 passed", "Existing component suites, earlier today"],
             ["Complete local chain", "2 passed runs", "Training, export, evaluation, HTTP relay"]],
            .7, 1.75, [3.0, 2.1, 6.75], .68, 17.5)
    s.text("No test row certifies a cloud execution or production service.", .7, 6.5, 11.8, .5, 18, MUTED)

    s = slides[8]
    s.text("Prepared configuration; no live deployment verified", .7, 1.55, 11.8, .5, 23, "9A6D37", True)
    s.box("HTTPS frontend", "Cloud Run ingress :8080", 1.0, 2.7, 4.65)
    s.arrow(5.85, 3.34, 1.25)
    s.box("Internal API", "localhost :9000 + private model", 7.3, 2.7, 4.65)
    s.text("Existing package: deploy/cloud-run/\nTarget: tastebridge-511403 / us-central1 / tastebridge-staging", .85, 4.8, 11.8, 1.25, 21)
    s.text("Operator needs approved access, a real export, image verification and an access policy.", .85, 6.35, 11.7, .7, 19, MUTED)

    s = slides[9]
    lines = [line.split('tastebridge.requests ', 1)[1] for line in (run / 'backend.log').read_text().splitlines()
             if 'tastebridge.requests ' in line]
    excerpt = [lines[0], next(line for line in lines if line.startswith('POST /recommend'))]
    s.text("Actual local request log", .7, 1.65, 6.0, .5, 23, SPRUCE, True)
    s.text("\n\n".join(excerpt), .7, 2.6, 7.2, 1.4, 17, font="Menlo")
    s.text("Method, path, status and elapsed time\nNo external feedback submitted", .7, 4.6, 6.9, 1.35, 23)
    s.text("Production evidence still needed", 8.3, 1.65, 4.1, .9, 23, "9A6D37", True)
    s.text("Real service revision\n\nCloud request/error event\n\nTeaching-staff log access", 8.3, 3.0, 4.1, 3.1, 23)

    s = slides[10]
    s.table([["MS3 requirement", "Local evidence", "Remaining evidence"],
             ["Tracked serverless training", "Source, config, hashes, local fit", "Successful tracked cloud run"],
             ["Automated ML workflow", "Reproducible local B2 chain", "Approved cloud workflow / equivalent"],
             ["Deployed model/API", "Actual local relay + model API", "Live service with staff access"],
             ["Production monitoring", "Actual local request logging", "Deployed logs and access"],
             ["Documented, tested API", "SPEC + suites + HTTP contracts", "Verify the deployed endpoint"],
             ["Code, slides, submission", "Local branch + this review deck", "Review, milestone3, Canvas hash"]],
            .65, 1.6, [3.3, 4.1, 4.55], .69, 16)
    s.text("Official deadline: November 12, 10pm ET. TF presentation: 15 minutes.", .7, 6.75, 11.8, .4, 17, MUTED)

    s = slides[11]
    s.fact("1. Team and cloud decisions", "Confirm the chosen tracker/workflow,\nexisting cloud runs and approved data.", .8, 1.7, 11.8)
    s.fact("2. Operator evidence", "Implement the approved cloud workflow and deploy the model,\nverify staff access and capture production logs.", .8, 3.45, 11.8)
    s.fact("3. Reviewed submission", "Resolve the push denial, reconcile team work,\ncreate milestone3 and submit the full hash on Canvas.", .8, 5.2, 11.8)

    for index, root in enumerate(roots, 1):
        parts[f"ppt/slides/slide{index}.xml"] = E.tostring(root, encoding="utf-8", xml_declaration=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    (work / "authoring.json").write_text(json.dumps({"slides": len(slides), "timing_seconds": sum(timings),
        "fonts": {"basis": "design", "families": ["Georgia", "Arial", "Menlo"]},
        "source_commit": record["source_commit"], "data_version": record["data_version"],
        "runtime_limit": "Artifact Tool runtime unavailable in delegated environment; pandoc packaging and native DrawingML used.",
        "draft": str(output)}, indent=2))
    print(json.dumps({"path": str(output), "slides": len(slides), "timing_seconds": sum(timings)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--historical-synthetic", action="store_true",
                        help="Explicitly reproduce the dated November 4 synthetic review, not the current MS3 deck")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    if not args.historical_synthetic:
        parser.error("This generator describes the historical November 4 synthetic review. "
                     "Use the current reviewed PPTX and presentation-source.md. "
                     "Pass --historical-synthetic only when deliberately reproducing that archived review.")
    build(args.output.resolve(), args.work.resolve())
