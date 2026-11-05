"""Generated-system checks. MMA_SCALE sets the program count for the large timed run."""
import json
import os
import random
import subprocess
import sys
import tempfile
import time
import unittest

from . import SCRIPTS

CLI = os.path.join(SCRIPTS, "mma.py")


def generate(root, programs):
    random.seed(7)
    for folder in ("cbl", "cpy", "jcl", "csd"):
        os.makedirs(os.path.join(root, "src", folder))
    copybooks = max(programs // 3, 1)
    for i in range(copybooks):
        with open(os.path.join(root, "src", "cpy", "CPY%05d.cpy" % i), "w") as f:
            f.write("".join("000%03d     05 FLD%03d PIC S9(7)V99 COMP-3.\n" % (j, j) for j in range(40)))
    for i in range(programs):
        name = "PGM%05d" % i
        body = ["       IDENTIFICATION DIVISION.", "       PROGRAM-ID. %s." % name, "       DATA DIVISION.", "       WORKING-STORAGE SECTION."]
        body += ["       COPY CPY%05d." % random.randrange(copybooks) for _ in range(4)]
        body += ["       PROCEDURE DIVISION."]
        for p in range(30):
            body += ["       P%03d-PARA." % p, "           IF A = 1", "              PERFORM P%03d-PARA" % min(p + 1, 29), "           END-IF."]
            body += ["           COMPUTE X = Y * 2."] * 4
        if i:
            body += ["           CALL 'PGM%05d'." % random.randrange(i)]
        with open(os.path.join(root, "src", "cbl", name + ".cbl"), "w") as f:
            f.write("\n".join(body) + "\n")
    for i in range(programs // 5 or 1):
        with open(os.path.join(root, "src", "jcl", "JOB%05d.jcl" % i), "w") as f:
            f.write("//JOB%05d JOB (A)\n//S1 EXEC PGM=PGM%05d\n//IN DD DSN=PROD.F%05d,DISP=SHR\n" % (i, random.randrange(programs), i))


def run(root, *args):
    return subprocess.run([sys.executable, CLI] + list(args), cwd=root, capture_output=True, text=True)


class ScaleTests(unittest.TestCase):
    def test_parallel_path_works_through_the_real_command(self):
        with tempfile.TemporaryDirectory() as root:
            generate(root, 300)
            self.assertEqual(run(root, "init", "--source", "src").returncode, 0)
            done = run(root, "scan")
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("cobol_program: 300", done.stdout)
            self.assertNotIn("parsed 0", done.stdout)
            again = run(root, "scan")
            self.assertIn("parsed 0", again.stdout)

    @unittest.skipUnless(os.environ.get("MMA_SCALE"), "set MMA_SCALE to run")
    def test_large_system_timing(self):
        programs = int(os.environ["MMA_SCALE"])
        with tempfile.TemporaryDirectory() as root:
            started = time.time()
            generate(root, programs)
            generated = time.time() - started
            run(root, "init", "--source", "src")
            started = time.time()
            done = run(root, "scan")
            first = time.time() - started
            self.assertEqual(done.returncode, 0, done.stderr[-2000:])
            started = time.time()
            done = run(root, "scan")
            second = time.time() - started
            self.assertEqual(done.returncode, 0, done.stderr[-2000:])
            started = time.time()
            flow = run(root, "flow", "PGM%05d" % (programs - 1))
            flow_time = time.time() - started
            self.assertEqual(flow.returncode, 0, flow.stderr[-2000:])
            size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(os.path.join(root, "modernization")) for f in fs)
            lines = sum(1 for d, _, fs in os.walk(os.path.join(root, "src")) for f in fs for _ in open(os.path.join(d, f)))
            print(json.dumps({"programs": programs, "lines": lines, "generate_s": round(generated, 1), "first_scan_s": round(first, 1), "rescan_s": round(second, 1), "flow_s": round(flow_time, 1), "output_mb": round(size / 1e6, 1)}))


if __name__ == "__main__":
    unittest.main()
