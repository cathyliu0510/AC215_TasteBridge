"""Capture backend MS2 evidence: request/response pairs against a running API."""
import json, sys, urllib.request, urllib.error
from pathlib import Path

base, books_path, out = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
books = json.loads(books_path.read_text())
fantasy = [b["book_id"] for b in books if "fantasy" in b["shelves"][:2] and "mystery" not in b["shelves"]][:5]
mystery = [b["book_id"] for b in books if "mystery" in b["shelves"][:2] and "fantasy" not in b["shelves"]][:5]
assert len(fantasy) == 5 and len(mystery) == 5

def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

cases = [
    ("01_health", "GET", "/health", None),
    ("02_search", "GET", "/books/search?q=invented%20book%2012&limit=3", None),
    ("03_book", "GET", f"/books/{fantasy[0]}", None),
    ("04_recommend_least_misery", "POST", "/recommend",
     {"reader_a": fantasy, "reader_b": mystery, "aggregation": "least-misery"}),
    ("05_recommend_average", "POST", "/recommend",
     {"reader_a": fantasy, "reader_b": mystery, "aggregation": "average"}),
    ("06_feedback", "POST", "/feedback", None),  # filled below
    ("07_error_unknown_book", "POST", "/recommend", {"reader_a": ["999999999"], "reader_b": mystery}),
    ("08_error_too_many_books", "POST", "/recommend",
     {"reader_a": fantasy + [mystery[0]], "reader_b": mystery[1:]}),
]
summary = []
for name, method, path, body in cases:
    if name == "06_feedback":
        rec = json.loads((out / "04_recommend_least_misery.json").read_text())["response"]
        body = {"book_id": rec["recommendations"][0]["book"]["book_id"], "vote": "would_read",
                "model_version": rec["model_version"]}
    status, resp = call(method, path, body)
    record = {"request": {"method": method, "path": path, **({"body": body} if body else {})},
              "status": status, "response": resp}
    (out / f"{name}.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    summary.append(f"{name}: {method} {path} -> {status}")
print("\n".join(summary))
