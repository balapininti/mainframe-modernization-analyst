import ast
import os
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile

from . import ROOT, SCRIPTS

SKILL = os.path.join(ROOT, "skill", "mainframe-modernization-analyst")


def read(*parts):
    with open(os.path.join(SKILL, *parts)) as f:
        return f.read()


def frontmatter():
    match = re.match(r"^---\n(.*?)\n---\n", read("SKILL.md"), re.S)
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


class FormatTests(unittest.TestCase):
    def test_name_follows_the_spec_and_matches_folder(self):
        name = frontmatter()["name"]
        self.assertEqual(name, os.path.basename(SKILL))
        self.assertRegex(name, r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertLessEqual(len(name), 64)

    def test_description_within_limit_with_trigger_words(self):
        description = frontmatter()["description"]
        self.assertLessEqual(len(description), 1024)
        for word in ("COBOL", "copybook", "JCL", "CICS", "Spring Boot"):
            self.assertIn(word, description)

    def test_body_is_short(self):
        self.assertLess(len(read("SKILL.md").splitlines()), 200)

    def test_every_linked_file_exists_one_level_deep(self):
        links = re.findall(r"\]\(((?:references|templates)/[^)]+)\)", read("SKILL.md"))
        self.assertGreater(len(links), 8)
        for link in links:
            self.assertTrue(os.path.exists(os.path.join(SKILL, link)), link)

    def test_every_reference_file_is_reachable(self):
        text = read("SKILL.md")
        for folder in ("references", "templates"):
            for name in os.listdir(os.path.join(SKILL, folder)):
                self.assertIn("%s/%s" % (folder, name), text)

    def test_version_is_semver(self):
        self.assertRegex(read("VERSION").strip(), r"^\d+\.\d+\.\d+$")


class ContentTests(unittest.TestCase):
    def all_docs(self):
        out = read("SKILL.md")
        for name in os.listdir(os.path.join(SKILL, "references")):
            out += read("references", name)
        return out

    def test_every_documented_command_exists(self):
        help_text = subprocess.run([sys.executable, os.path.join(SCRIPTS, "mma.py"), "--help"], capture_output=True, text=True).stdout
        commands = set(re.findall(r"mma\.py ([a-z][a-z-]+)", self.all_docs()))
        self.assertGreater(len(commands), 15)
        for command in commands:
            self.assertIn(command, help_text, command)

    def test_all_design_prompts_present(self):
        text = read("references", "prompts.md")
        for prompt in [
            "Inventory this system and tell me what's missing", "Give me the big picture", "Explain the end-to-end flow",
            "to a Spring Boot developer", "Write requirements and rules", "Build the data dictionary", "Write test scenarios",
            "Suggest a Spring Boot mapping", "What's still missing, and who do I ask", "Prepare the mainframe team request and SME questions",
            "Update the analysis", "Suggest a migration order",
        ]:
            self.assertIn(prompt, text)

    def test_hard_rules_stated_in_skill(self):
        text = read("SKILL.md")
        for phrase in ["Never generate", "read-only", "Never state", "ask_expert", "incomplete", "mma.py validate"]:
            self.assertIn(phrase, text)

    def test_all_hidden_behaviour_covered(self):
        text = read("references", "hidden-behaviour.md")
        for term in ["SORT", "IDCAMS", "COND", "COMP-3", "REDEFINES", "OCCURS DEPENDING ON", "88", "windowed", "rounding", "EBCDIC",
                     "PERFORM THRU", "GO TO", "SQLCODE", "file status", "abend", "checkpoint", "COMMAREA", "syncpoint", "locking"]:
            self.assertIn(term.lower(), text.lower(), term)

    def test_manual_fallback_documented(self):
        text = read("references", "cli.md")
        self.assertIn("by hand", text)

    def test_docs_have_no_attribution(self):
        text = self.all_docs() + read("INSTALL.md") + read("PILOT_CHECKLIST.md")
        for phrase in ("Generated with", "Co-Authored-By", "Claude"):
            self.assertNotIn(phrase, text)


class CodeRuleTests(unittest.TestCase):
    def modules(self):
        for root, _, files in os.walk(SCRIPTS):
            for name in files:
                if name.endswith(".py"):
                    yield os.path.join(root, name)

    def test_standard_library_only(self):
        for path in self.modules():
            with open(path) as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module]
                for name in names:
                    top = name.split(".")[0]
                    self.assertTrue(top in sys.stdlib_module_names or top == "mma", "%s imports %s" % (path, name))

    def test_no_network_modules(self):
        banned = {"socket", "http", "urllib", "ftplib", "smtplib", "ssl", "requests"}
        for path in self.modules():
            with open(path) as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertFalse({a.name.split(".")[0] for a in node.names} & banned, path)
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    self.assertNotIn(node.module.split(".")[0], banned, path)


class ReleaseTests(unittest.TestCase):
    def test_release_zip_installs_and_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            done = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "build_release.py"), "--out", tmp], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            version = read("VERSION").strip()
            path = os.path.join(tmp, "mainframe-modernization-analyst-%s.zip" % version)
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                z.extractall(os.path.join(tmp, "x"))
            self.assertIn("mainframe-modernization-analyst/SKILL.md", names)
            self.assertIn("mainframe-modernization-analyst/INSTALL.md", names)
            self.assertFalse([n for n in names if "__pycache__" in n or n.endswith(".pyc") or "tests/" in n or "fixtures" in n])
            cli = os.path.join(tmp, "x", "mainframe-modernization-analyst", "scripts", "mma.py")
            run = subprocess.run([sys.executable, cli, "--help"], capture_output=True, text=True, cwd=tmp)
            self.assertEqual(run.returncode, 0, run.stderr)


if __name__ == "__main__":
    unittest.main()
