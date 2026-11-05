#!/usr/bin/env python3
"""Build the zip that gets handed to the receiving team."""
import argparse
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "mainframe-modernization-analyst"
SKILL = os.path.join(ROOT, "skill", NAME)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=os.path.join(ROOT, "dist"))
    args = parser.parse_args()
    with open(os.path.join(SKILL, "VERSION")) as f:
        version = f.read().strip()
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, "%s-%s.zip" % (NAME, version))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for folder, dirs, files in os.walk(SKILL):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for name in sorted(files):
                if name.endswith(".pyc") or name.startswith("."):
                    continue
                full = os.path.join(folder, name)
                archive.write(full, os.path.join(NAME, os.path.relpath(full, SKILL)))
    print(path)


if __name__ == "__main__":
    main()
