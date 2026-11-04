"""Workspace settings and paths. All results live in <project>/modernization/."""
import json
import os

from .logs import Logger

OUTPUT_DIR = "modernization"
DEFAULTS = {
    "source_roots": [],
    "code_page": "cp037",
    "record_length": 80,
    "quote_source": True,
    "library_precedence": [],
    "ignore_extensions": [
        ".md", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".xlsx", ".docx", ".pptx", ".zip", ".gz", ".jar",
        ".class", ".py", ".java", ".sh", ".json", ".yml", ".yaml", ".html", ".css", ".js", ".ts", ".log",
    ],
    "system_programs": [],
    "system_copybooks": [],
    "max_file_mb": 20,
    "hub_threshold": 5,
    "max_slice_programs": 25,
    "jobs": 0,
}
SKIP_DIRS = {".git", ".github", ".svn", ".vscode", ".idea", ".superpowers", "node_modules", "__pycache__", OUTPUT_DIR}
GITIGNORE = "logs/\nlogs-export/\ninventory/cache/\n"


class ConfigError(Exception):
    """A problem the user can fix. The message is shown as is, with no traceback."""


class Workspace:
    def __init__(self, root, config):
        self.root = os.path.abspath(root)
        self.out = os.path.join(self.root, OUTPUT_DIR)
        self.config = config
        self._logger = None

    @classmethod
    def load(cls, root="."):
        path = os.path.join(os.path.abspath(root), OUTPUT_DIR, "config.json")
        if not os.path.exists(path):
            raise ConfigError(
                "No analysis has been set up in %s. Run: python mma.py init --source <folder with the mainframe code>" % os.path.abspath(root))
        with open(path) as f:
            saved = json.load(f)
        config = dict(DEFAULTS)
        config.update(saved)
        return cls(root, config)

    @property
    def logger(self):
        if self._logger is None:
            self._logger = Logger(self.out)
        return self._logger

    def save(self):
        write_json(os.path.join(self.out, "config.json"), self.config)

    def path(self, *parts):
        return os.path.join(self.out, *parts)

    def source_paths(self):
        return [os.path.normpath(os.path.join(self.root, s)) for s in self.config["source_roots"]]

    def rel(self, path):
        return os.path.relpath(path, self.root).replace(os.sep, "/")

    def abs(self, relative):
        return os.path.normpath(os.path.join(self.root, relative))


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
        f.write("\n")


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def init_workspace(root, sources, code_page=None, record_length=None, quote_source=None):
    root = os.path.abspath(root)
    relative = []
    for source in sources:
        full = os.path.normpath(os.path.join(root, source))
        if not os.path.isdir(full):
            raise ConfigError("Can't find the source folder '%s'. Check the path and try again." % source)
        relative.append(os.path.relpath(full, root).replace(os.sep, "/"))
    if not relative:
        raise ConfigError("Tell me where the mainframe code is: --source <folder>.")
    existing = read_json(os.path.join(root, OUTPUT_DIR, "config.json"), {})
    config = dict(DEFAULTS)
    config.update(existing)
    config["source_roots"] = relative
    if code_page:
        config["code_page"] = code_page
    if record_length:
        config["record_length"] = record_length
    if quote_source is not None:
        config["quote_source"] = quote_source
    ws = Workspace(root, config)
    try:
        ws.save()
        write_text(ws.path(".gitignore"), GITIGNORE)
    except OSError:
        raise ConfigError("I can't write to %s. Results are saved there, so write access is needed." % ws.out)
    return ws
