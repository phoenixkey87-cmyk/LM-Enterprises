#!/usr/bin/env python3
"""Validate generated /data/*.json against /data/schema/*.schema.json.

Exit 0 when every file that exists is valid. Missing generated files are allowed
(first run before any data); an invalid file fails the Action so it is never committed.
Requires: pip install jsonschema
"""
import json
import sys
from pathlib import Path

from jsonschema import Draft7Validator

DATA = Path(__file__).resolve().parent.parent / "data"
NAMES = ["fares", "explore", "calendar", "stays"]


def main():
    bad = 0
    for name in NAMES:
        path = DATA / (name + ".json")
        if not path.exists():
            print("skip   %s.json (not generated yet)" % name)
            continue
        schema = json.loads((DATA / "schema" / (name + ".schema.json")).read_text(encoding="utf-8"))
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print("FAIL   %s.json: invalid JSON (%s)" % (name, e))
            bad += 1
            continue
        errors = sorted(Draft7Validator(schema).iter_errors(doc), key=lambda e: list(e.path))
        if errors:
            bad += 1
            print("FAIL   %s.json" % name)
            for e in errors[:10]:
                print("       /%s: %s" % ("/".join(map(str, e.path)), e.message[:160]))
        else:
            print("ok     %s.json" % name)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
