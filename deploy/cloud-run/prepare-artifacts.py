#!/usr/bin/env python3
"""Validate and stage only the four backend model exports, using the stdlib."""

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import tempfile


EXPORTS = ("books.json", "item_embeddings.npy", "coords_2d.npy", "meta.json")
MANIFEST = "manifest.json"


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON in {path.name}: {exc}") from exc


def check_books(path):
    books = read_json(path)
    if not isinstance(books, list) or not books:
        raise ValueError("books.json must contain a nonempty list")
    ids = set()
    for index, book in enumerate(books):
        if not isinstance(book, dict):
            raise ValueError(f"Book {index} must be an object")
        book_id = book.get("book_id")
        if not isinstance(book_id, str) or not 1 <= len(book_id) <= 64:
            raise ValueError(f"Book {index} must have a book_id of 1–64 characters")
        if book_id in ids:
            raise ValueError(f"Duplicate book_id at book {index}")
        ids.add(book_id)
        if any(not isinstance(book.get(key), str) for key in ("title", "author")):
            raise ValueError(f"Book {index} must have string title and author fields")
        if book.get("year") is not None and type(book["year"]) is not int:
            raise ValueError(f"Book {index} year must be an integer or null")
        if book.get("cover_url") is not None and not isinstance(book["cover_url"], str):
            raise ValueError(f"Book {index} cover_url must be a string or null")
        shelves = book.get("shelves", [])
        if not isinstance(shelves, list) or any(not isinstance(shelf, str) for shelf in shelves):
            raise ValueError(f"Book {index} shelves must be a list of strings")
    return len(books)


def check_matrix(path, rows, columns=None):
    """Read NPY metadata and finite floats without NumPy or pickle loading."""
    with path.open("rb") as source:
        if source.read(6) != b"\x93NUMPY":
            raise ValueError(f"{path.name} is not an NPY file")
        version = source.read(2)
        if version not in (b"\x01\x00", b"\x02\x00", b"\x03\x00"):
            raise ValueError(f"{path.name} has an unsupported NPY version")
        length_size = 2 if version[0] == 1 else 4
        length_bytes = source.read(length_size)
        if len(length_bytes) != length_size:
            raise ValueError(f"{path.name} has a truncated NPY header")
        length = int.from_bytes(length_bytes, "little")
        if not 0 < length <= 65536:
            raise ValueError(f"{path.name} has an invalid or oversized NPY header")
        header_bytes = source.read(length)
        if len(header_bytes) != length:
            raise ValueError(f"{path.name} has a truncated NPY header")
        try:
            header = ast.literal_eval(header_bytes.decode("utf-8" if version[0] == 3 else "latin1").strip())
        except (ValueError, SyntaxError, UnicodeError) as exc:
            raise ValueError(f"{path.name} has an invalid NPY header") from exc
        if not isinstance(header, dict) or type(header.get("fortran_order")) is not bool:
            raise ValueError(f"{path.name} has an invalid NPY header")
        shape = header.get("shape")
        if not isinstance(shape, tuple) or len(shape) != 2 or any(type(size) is not int or size <= 0 for size in shape):
            raise ValueError(f"{path.name} must be a nonempty two-dimensional matrix")
        if shape[0] != rows or (columns is not None and shape[1] != columns):
            raise ValueError(f"{path.name} shape {shape} does not match {rows} books" + (f" and {columns} columns" if columns else ""))
        dtype = header.get("descr")
        if not isinstance(dtype, str) or not re.fullmatch(r"[<>=|]f[248]", dtype):
            raise ValueError(f"{path.name} must use float16, float32, or float64 values; objects are not allowed")
        item_size = int(dtype[-1])
        expected = math.prod(shape) * item_size
        if path.stat().st_size - source.tell() != expected:
            raise ValueError(f"{path.name} byte length does not match its NPY shape")
        format_string = (dtype[0] if dtype[0] in "<>" else "=") + {2: "e", 4: "f", 8: "d"}[item_size]
        while chunk := source.read(65536):
            if any(not math.isfinite(value) or abs(value) > 3.4028234663852886e38 for (value,) in struct.iter_unpack(format_string, chunk)):
                raise ValueError(f"{path.name} contains nonfinite values or values outside the backend float32 range")
    return {"shape": list(shape), "dtype": dtype}


def prepare(source, output):
    source = source.expanduser().resolve(strict=True)
    output = output.expanduser().absolute()
    if not source.is_dir():
        raise ValueError("Artifact source must be a directory")
    if output.is_symlink() or (output.exists() and not output.is_dir()):
        raise ValueError("Output must be a directory, not a file or symlink")
    output = output.resolve()
    if output == source or output in source.parents or source in output.parents:
        raise ValueError("Source and output must be separate, non-nested directories")
    if output.exists():
        unexpected = [item.name for item in output.iterdir() if item.name not in (*EXPORTS, MANIFEST) or not item.is_file() or item.is_symlink()]
        if unexpected:
            raise ValueError("Output contains unexpected entries; choose a clean staging directory")
    for name in EXPORTS:
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing regular artifact file: {name}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".artifact-check-", dir=output.parent) as temporary:
        stage = Path(temporary)
        for name in EXPORTS:
            shutil.copyfile(source / name, stage / name)
        count = check_books(stage / "books.json")
        meta = read_json(stage / "meta.json")
        if not isinstance(meta, dict) or not isinstance(meta.get("model_version"), str) or not meta["model_version"].strip():
            raise ValueError("meta.json must contain a nonempty model_version")
        declared_count = meta.get("counts", {}).get("books") if isinstance(meta.get("counts"), dict) else None
        if declared_count is not None and (type(declared_count) is not int or declared_count != count):
            raise ValueError("meta.json counts.books does not match books.json")
        matrices = {
            "item_embeddings.npy": check_matrix(stage / "item_embeddings.npy", count),
            "coords_2d.npy": check_matrix(stage / "coords_2d.npy", count, columns=2),
        }
        manifest = {
            "model_version": meta["model_version"],
            "num_books": count,
            "prepared_at": datetime.now(timezone.utc).isoformat(),
            "files": {},
        }
        if isinstance(meta.get("data_version"), str):
            manifest["data_version"] = meta["data_version"]
        for name in EXPORTS:
            path = stage / name
            digest = hashlib.sha256()
            with path.open("rb") as file:
                for chunk in iter(lambda: file.read(1048576), b""):
                    digest.update(chunk)
            manifest["files"][name] = {"sha256": digest.hexdigest(), "bytes": path.stat().st_size, **matrices.get(name, {})}
        (stage / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        output.mkdir(exist_ok=True)
        for name in (*EXPORTS, MANIFEST):
            os.replace(stage / name, output / name)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Existing model-export directory")
    parser.add_argument("output", type=Path, help="Ignored staging directory (deploy/cloud-run/.artifacts)")
    args = parser.parse_args()
    try:
        manifest = prepare(args.source, args.output)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Artifact preparation failed: {exc}\n")
    print(json.dumps({"model_version": manifest["model_version"], "num_books": manifest["num_books"], "files": list(EXPORTS), "manifest": str(args.output / MANIFEST)}, indent=2))


if __name__ == "__main__":
    main()
