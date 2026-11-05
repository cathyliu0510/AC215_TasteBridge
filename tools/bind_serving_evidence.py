#!/usr/bin/env python3
"""Hash supplied local evidence against the verified source manifest and all four model files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.evidence_contracts import bind_serving_evidence, read_json, verify_evidence_binding


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    bind = commands.add_parser('bind', help='Create a fresh manifest; never overwrite earlier evidence')
    bind.add_argument('--run', type=Path, required=True, help='Successful run.json; evidence paths are relative to its folder')
    bind.add_argument('--artifact-dir', type=Path, required=True, help='Read-only existing four-file model export')
    bind.add_argument('--source-root', type=Path, default=ROOT, help='Checkout to match against the recorded source manifest')
    bind.add_argument('--evidence', action='append', default=[], metavar='ROLE=RELATIVE_PATH',
                      help='Additional screenshot, test, browser_report, log or report file inside the run folder')
    bind.add_argument('--out', type=Path, required=True, help='New binding JSON file')
    verify = commands.add_parser('verify', help='Check binding and evidence bytes only; no browser or service actions')
    verify.add_argument('binding', type=Path)
    verify.add_argument('--bundle-root', type=Path, help='Defaults to the binding file folder')
    args = parser.parse_args(argv)
    if args.command == 'verify':
        verify_evidence_binding(read_json(args.binding), args.bundle_root or args.binding.parent)
        print(json.dumps({'evidence_bytes_verified': True, 'browser_actions_verified': False}))
        return 0
    if args.out.exists() or args.out.is_symlink():
        raise ValueError('Binding output already exists; choose a fresh file')
    evidence = []
    for item in args.evidence:
        role, separator, path = item.partition('=')
        if not separator or not role or not path:
            parser.error('--evidence must be ROLE=RELATIVE_PATH')
        evidence.append((role, Path(path)))
    result = bind_serving_evidence(args.run.absolute(), args.artifact_dir, evidence, source_root=args.source_root)
    # Exclusive create also prevents accidentally overwriting a previous binding in a race.
    with args.out.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'binding': str(args.out), 'sha256': result['sha256'],
                      'evidence_files': len(result['evidence']), 'browser_actions_verified': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
