"""Operator CLI. Run inside the backend environment; no admin HTTP endpoint."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.models.db import init_db
from app.services import course_library as library


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "publish"):
        p = commands.add_parser(name)
        p.add_argument("bundle", type=Path)
        if name == "publish":
            p.add_argument("--inactive", action="store_true")
    p = commands.add_parser("activate", help="Select an existing release; rebuild its index if needed")
    p.add_argument("release_id")
    for name, key in (("withdraw", "release_id"), ("withdraw-source", "sha256")):
        p = commands.add_parser(name)
        p.add_argument(key)
        p.add_argument("--reason", required=True)
    args = parser.parse_args()
    if args.command == "validate":
        data = json.loads(args.bundle.read_text(encoding="utf-8"))
        library.validate_bundle(data)
        print(json.dumps({"valid": True, "release": data["release_id"], "lessons": len(data["lessons"])}, ensure_ascii=False))
        return
    init_db()
    if args.command == "publish":
        data = json.loads(args.bundle.read_text(encoding="utf-8"))
        result = library.publish(data, activate=not args.inactive)
    elif args.command == "activate":
        data, _ = library.load_release(args.release_id)
        result = library.publish(data)
    elif args.command == "withdraw":
        library.withdraw(args.release_id, args.reason)
        result = args.release_id
    else:
        result = library.withdraw_source(args.sha256, args.reason)
    print(json.dumps({"operation": args.command, "result": result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
