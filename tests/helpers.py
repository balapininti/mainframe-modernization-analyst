import os
import shutil
import tempfile

from mma.config import init_workspace

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample")


def sample_workspace(test):
    """A temp project holding a copy of the sample system, removed after the test."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    src = os.path.join(tmp.name, "src")
    shutil.copytree(FIXTURE, src)
    return init_workspace(tmp.name, ["src"]), src
