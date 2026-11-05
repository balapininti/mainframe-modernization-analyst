"""Check the machine and folder are ready, and explain any problem in plain language."""
import os
import sys
import tempfile

from .config import OUTPUT_DIR, SKIP_DIRS, read_json
from .sourcefile import classify, decode_bytes

MINIMUM = (3, 9)
SAMPLE_FILES = 200


def _sources(root, given):
    if given:
        return given
    saved = read_json(os.path.join(root, OUTPUT_DIR, "config.json"), {})
    return saved.get("source_roots", [])


def _sample(path, code_page):
    total, kinds = 0, {}
    for folder, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            total += 1
            if sum(kinds.values()) < SAMPLE_FILES:
                try:
                    with open(os.path.join(folder, name), "rb") as f:
                        decoded = decode_bytes(f.read(1024 * 256), code_page)
                except OSError:
                    continue
                kind = classify(decoded.text, name) if decoded.ok else "undecodable"
                kinds[kind] = kinds.get(kind, 0) + 1
    return total, kinds


def run(root, given_sources=None):
    problems = 0
    root = os.path.abspath(root)
    version = ".".join(str(n) for n in sys.version_info[:3])
    if sys.version_info[:2] >= MINIMUM:
        print("OK: Python %s" % version)
    else:
        print("PROBLEM: Python %s is too old. Install Python %d.%d or newer." % ((version,) + MINIMUM))
        problems += 1
    target = os.path.join(root, OUTPUT_DIR) if os.path.isdir(os.path.join(root, OUTPUT_DIR)) else root
    try:
        with tempfile.TemporaryFile(dir=target):
            pass
        print("OK: results can be saved in %s" % os.path.join(root, OUTPUT_DIR))
    except OSError:
        print("PROBLEM: I can't write to %s. Results are saved there, so write access is needed." % target)
        problems += 1
    sources = _sources(root, given_sources)
    if not sources:
        print("PROBLEM: no source folder given. Add --source <folder with the mainframe code>.")
        problems += 1
    for source in sources:
        path = os.path.normpath(os.path.join(root, source))
        if not os.path.isdir(path):
            print("PROBLEM: can't find the source folder '%s'. Check the path." % source)
            problems += 1
            continue
        total, kinds = _sample(path, read_json(os.path.join(root, OUTPUT_DIR, "config.json"), {}).get("code_page", "cp037"))
        if not total:
            print("PROBLEM: the source folder '%s' is empty." % source)
            problems += 1
            continue
        recognized = sum(n for k, n in kinds.items() if k not in ("unknown", "undecodable"))
        print("OK: '%s' has %d files. In a sample of %d, %d look like mainframe source." % (source, total, sum(kinds.values()), recognized))
        if not recognized:
            print("PROBLEM: nothing in that sample looks like mainframe source. Check the folder or its encoding.")
            problems += 1
    if problems:
        print("Not ready: %d problem(s) above." % problems)
        return 2
    print("Ready. Next: python mma.py init --source <folder>, then python mma.py scan")
    return 0
