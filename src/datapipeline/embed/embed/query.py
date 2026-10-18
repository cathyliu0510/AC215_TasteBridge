"""Retrieval examples (MS2 evidence) and a small search CLI.

    python -m embed.query "a heist with a crew of con artists" --k 5 [--genre fantasy]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from embed.config import Settings
from embed.encoder import SentenceTransformerEncoder
from embed.store import open_collection, release_chroma, search

DEFAULT_K = 5
EXCERPT_CHARS = 200


def run_examples(collection, encoder, queries: Sequence[str], k: int = DEFAULT_K,
                 excerpts: bool = False) -> list[dict]:
    queries = list(queries)
    vectors = encoder.encode(queries)
    examples = []
    for query, vector in zip(queries, vectors):
        results = search(collection, vector, k=k)
        for result in results:
            document = result.pop("document")
            if excerpts:
                result["excerpt"] = document[:EXCERPT_CHARS]
        examples.append({"query": query, "results": results})
    return examples


def _cell(value: object) -> str:
    return "" if value is None else str(value).replace("|", "\\|")


def format_examples_md(examples: list[dict]) -> str:
    lines = [
        "# Retrieval examples",
        "",
        "| Query | Rank | Title | Author | Genre | Similarity | Text source |",
        "|---|---|---|---|---|---|---|",
    ]
    for example in examples:
        for result in example["results"]:
            query = _cell(example["query"]) if result["rank"] == 1 else ""
            lines.append(
                f"| {query} | {result['rank']} | {_cell(result['title'])} | "
                f"{_cell(result['author'])} | {_cell(result['genre'])} | "
                f"{result['similarity']:.4f} | {_cell(result['text_source'])} |"
            )
    return "\n".join(lines) + "\n"


def write_examples(out_dir: Path, examples: list[dict]) -> None:
    out_dir = Path(out_dir)
    (out_dir / "retrieval_example.json").write_text(json.dumps(examples, indent=2), encoding="utf-8")
    (out_dir / "retrieval_example.md").write_text(format_examples_md(examples), encoding="utf-8")


def main(argv: list[str] | None = None, encoder_factory=SentenceTransformerEncoder) -> int:
    parser = argparse.ArgumentParser(description="Search the book-description index.")
    parser.add_argument("query")
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--genre", choices=["fantasy", "mystery"])
    parser.add_argument("--dir", type=Path, default=None, help="embed output folder")
    args = parser.parse_args(argv)
    out_dir = args.dir or Settings.from_env().output_dir

    try:
        meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
        model = (meta["embedding_model"], meta["model_revision"])
        collection = open_collection(out_dir / "chroma")
    except KeyError as exc:
        print(f"error: {out_dir / 'meta.json'} lacks {exc}. "
              "Re-run `python -m embed.run` to rebuild it.", file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError) as exc:
        print(f"error: cannot open the index in {out_dir} ({exc}). "
              "Run `python -m embed.run` first.", file=sys.stderr)
        release_chroma()
        return 1

    encoder = encoder_factory(*model)
    results = search(collection, encoder.encode([args.query])[0], k=args.k, genre=args.genre)
    for result in results:
        print(f"{result['rank']:>2}  {result['similarity']:.4f}  {result['title']} "
              f"- {result['author'] or '?'} [{result['genre'] or '?'}]")
    release_chroma()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
