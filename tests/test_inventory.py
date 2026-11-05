import filecmp
import json
import os
import shutil
import unittest

from mma.config import ConfigError, Workspace, init_workspace
from mma.depmap import build_map, load_map
from mma.gaps import detect_gaps, load_gaps
from mma.inventory import load_catalogue, run_inventory

from .helpers import sample_workspace


def run_all(ws):
    summary = run_inventory(ws)
    build_map(ws)
    detect_gaps(ws)
    return summary


def tree_snapshot(path, skip=("logs", "cache")):
    out = {}
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in skip]
        for name in files:
            full = os.path.join(root, name)
            with open(full, "rb") as f:
                out[os.path.relpath(full, path)] = f.read()
    return out


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.ws, self.src = sample_workspace(self)

    def test_counts_by_kind(self):
        summary = run_inventory(self.ws)
        counts = summary["file_counts"]
        self.assertEqual(counts["cobol_program"], 5)
        self.assertEqual(counts["copybook"], 4)
        self.assertEqual(counts["jcl_job"], 1)
        self.assertEqual(counts["jcl_proc"], 1)
        self.assertEqual(counts["csd"], 1)
        self.assertEqual(counts["assembler"], 1)
        self.assertEqual(counts["undecodable"], 1)
        self.assertEqual(counts["unknown"], 1)

    def test_readme_ignored(self):
        run_inventory(self.ws)
        self.assertNotIn("README", {m["name"] for m in load_catalogue(self.ws)})

    def test_file_with_no_extension_found_by_content(self):
        run_inventory(self.ws)
        kinds = {m["name"]: m["kind"] for m in load_catalogue(self.ws)}
        self.assertEqual(kinds["ORDENTRY"], "cobol_program")
        self.assertEqual(kinds["CUSTREC"], "copybook")

    def test_path_with_spaces(self):
        os.makedirs(os.path.join(self.src, "my folder"))
        shutil.copy(os.path.join(self.src, "cobol", "ORPHAN.cbl"), os.path.join(self.src, "my folder", "SPACED"))
        with open(os.path.join(self.src, "my folder", "SPACED"), "a") as f:
            f.write("000600*    DIFFERENT\n")
        run_inventory(self.ws)
        self.assertIn("SPACED", {m["name"] for m in load_catalogue(self.ws)})

    def test_output_folder_never_scanned(self):
        ws = init_workspace(self.ws.root, ["."])
        run_inventory(ws)
        first = len(load_catalogue(ws))
        run_inventory(ws)
        self.assertEqual(len(load_catalogue(ws)), first)

    def test_cache_used_on_rerun(self):
        run_inventory(self.ws)
        self.assertGreater(run_inventory(self.ws)["cached_files"], 10)

    def test_ebcdic_source_is_read(self):
        with open(os.path.join(self.src, "cobol", "ORPHAN.cbl")) as f:
            text = f.read().replace("ORPHAN", "EBCPGM")
        with open(os.path.join(self.src, "cobol", "EBCPGM"), "wb") as f:
            f.write(text.encode("cp037"))
        run_inventory(self.ws)
        entry = [m for m in load_catalogue(self.ws) if m["name"] == "EBCPGM"][0]
        self.assertEqual((entry["kind"], entry["encoding"]), ("cobol_program", "cp037"))

    def test_rerun_is_byte_identical(self):
        run_all(self.ws)
        first = tree_snapshot(self.ws.out)
        run_all(self.ws)
        self.assertEqual(first, tree_snapshot(self.ws.out))


class ParallelFallbackTests(unittest.TestCase):
    def test_broken_worker_pool_falls_back_to_one_process(self):
        import concurrent.futures
        from unittest import mock
        import mma.inventory as inventory

        ws, _ = sample_workspace(self)
        with mock.patch.object(inventory, "PARALLEL_THRESHOLD", 1), mock.patch.object(
            concurrent.futures, "ProcessPoolExecutor", side_effect=OSError("not allowed")
        ):
            summary = run_inventory(ws)
        self.assertEqual(summary["file_counts"]["cobol_program"], 5)


class ParseFailureTests(unittest.TestCase):
    def test_one_bad_file_does_not_stop_the_run(self):
        from unittest import mock
        import mma.inventory as inventory

        ws, _ = sample_workspace(self)
        with mock.patch.object(inventory, "parse_text", side_effect=MemoryError("boom")):
            run_inventory(ws)
        self.assertTrue(all(m.get("parse_error") for m in load_catalogue(ws) if m["kind"] == "cobol_program"))


class MapTests(unittest.TestCase):
    def setUp(self):
        self.ws, self.src = sample_workspace(self)
        run_all(self.ws)
        self.map = load_map(self.ws)
        self.edges = {(e["from"], e["type"], e["to"]) for e in self.map["edges"]}

    def has(self, *edge):
        self.assertIn(edge, self.edges)

    def test_cobol_edges(self):
        self.has("program:BILLCALC", "calls", "program:PRICELIB")
        self.has("program:ORDENTRY", "copies", "copybook:ORDREC")
        self.has("program:ORDENTRY", "links", "program:PRICECHK")
        self.has("program:ORDENTRY", "writes", "table:ORDERS")
        self.has("program:BILLCALC", "reads", "table:ORDERS")
        self.has("program:ORDENTRY", "receives_map", "mapset:ORDSET")
        self.has("program:PRICECHK", "reads", "cics_file:PRICEFL")

    def test_jcl_edges(self):
        self.has("job:NITEBILL", "runs_program", "program:BILLCALC")
        self.has("job:NITEBILL", "runs_proc", "proc:BILLPROC")
        self.has("job:NITEBILL", "runs_program", "program:ORPHANX")

    def test_db2_batch_program_edge_cites_the_run_line(self):
        edge = [e for e in self.map["edges"] if e["to"] == "program:ORPHANX"][0]
        self.assertEqual(edge["line"], 18)

    def test_program_file_joined_to_dataset_through_dd(self):
        self.has("program:BILLCALC", "updates", "dataset:PROD.CUST.MASTER")
        self.has("program:BILLCALC", "writes", "dataset:PROD.BILL.OUT")

    def test_transaction_and_cics_file_definitions(self):
        self.has("transaction:ORD1", "starts", "program:ORDENTRY")
        self.has("cics_file:PRICEFL", "defined_as", "dataset:PROD.PRICE.KSDS")
        self.has("program:ORDENTRY", "returns_to", "transaction:ORD1")

    def test_edge_has_evidence(self):
        edge = [e for e in self.map["edges"] if e["to"] == "program:PRICELIB"][0]
        self.assertEqual(edge["line"], 41)
        self.assertTrue(edge["file"].endswith("BILLCALC.cbl"))

    def test_inferred_edge_is_labeled(self):
        edge = [e for e in self.map["edges"] if e["to"] == "program:AUDITLOG"][0]
        self.assertEqual(edge["confidence"], "inferred")
        edge = [e for e in self.map["edges"] if e["to"] == "program:PRICELIB"][0]
        self.assertEqual(edge["confidence"], "confirmed")

    def test_system_programs_are_not_nodes_of_interest(self):
        self.assertNotIn("program:IEFBR14", self.map["missing"])
        self.assertNotIn("copybook:SQLCA", self.map["missing"])
        self.assertIn("program:PRICELIB", self.map["missing"])


class GapTests(unittest.TestCase):
    def setUp(self):
        self.ws, self.src = sample_workspace(self)
        run_all(self.ws)

    def gaps(self):
        return {(g["kind"], g["name"]): g for g in load_gaps(self.ws)}

    def test_missing_copybook_has_owner_and_reference(self):
        gap = self.gaps()[("missing_copybook", "MISSCPY")]
        self.assertEqual(gap["owner"], "mainframe_team")
        self.assertEqual(gap["references"][0]["line"], 5)
        self.assertTrue(gap["references"][0]["file"].endswith("PRICECHK.cbl"))
        self.assertEqual(gap["blocks"], ["program:PRICECHK"])
        self.assertEqual(gap["status"], "open")

    def test_each_detected_kind(self):
        gaps = self.gaps()
        for key in [
            ("missing_program", "PRICELIB"), ("missing_program", "AUDITLOG"), ("missing_program", "ORPHANX"),
            ("missing_proc", "NOPROC"), ("missing_control_card", "BILLPARM"), ("missing_vsam_def", "PROD.CUST.MASTER"),
            ("missing_schedule", "ALL-JOBS"), ("dynamic_reference", "BILLCALC:WS-DYN"),
            ("unsupported_technology", "assembler"), ("unsupported_technology", "ims"),
            ("undecodable_files", "ALL"), ("unrecognized_files", "ALL"),
        ]:
            with self.subTest(key=key):
                self.assertIn(key, gaps)

    def test_things_present_are_not_gaps(self):
        names = {name for _, name in self.gaps()}
        for name in ["SQLCA", "DFHAID", "ORDERS", "PRICEFL", "SORT", "IEFBR14", "IDCAMS", "BILLPROC", "LIBMEMB", "ORD1", "ORDSET"]:
            with self.subTest(name=name):
                self.assertNotIn(name, names)

    def test_inline_define_counts_as_vsam_definition(self):
        self.assertNotIn(("missing_vsam_def", "PROD.INLINE.KSDS"), self.gaps())

    def test_missing_ddl_detected_when_table_has_no_definition(self):
        os.remove(os.path.join(self.src, "defs", "orders.ddl"))
        run_all(self.ws)
        self.assertIn(("missing_db2_ddl", "ORDERS"), self.gaps())

    def test_missing_map_and_transaction_detected(self):
        os.remove(os.path.join(self.src, "defs", "ORDSET.bms"))
        os.remove(os.path.join(self.src, "defs", "app.csd"))
        run_all(self.ws)
        gaps = self.gaps()
        self.assertIn(("missing_bms_map", "ORDSET"), gaps)
        self.assertIn(("missing_cics_def", "TRANSACTION ORD1"), gaps)
        self.assertIn(("missing_cics_def", "FILE PRICEFL"), gaps)

    def test_gap_id_stable_and_no_duplicates_on_rerun(self):
        before = {g["id"] for g in load_gaps(self.ws)}
        run_all(self.ws)
        self.assertEqual(before, {g["id"] for g in load_gaps(self.ws)})

    def test_gap_resolves_itself_when_file_arrives(self):
        with open(os.path.join(self.src, "copy", "MISSCPY"), "w") as f:
            f.write("000100 01  M PIC X.\n")
        run_all(self.ws)
        gap = self.gaps()[("missing_copybook", "MISSCPY")]
        self.assertEqual((gap["status"], gap["resolution"]), ("resolved", "found_in_source"))

    def test_gap_reopens_when_file_disappears_again(self):
        path = os.path.join(self.src, "copy", "MISSCPY")
        with open(path, "w") as f:
            f.write("000100 01  M PIC X.\n")
        run_all(self.ws)
        os.remove(path)
        run_all(self.ws)
        self.assertEqual(self.gaps()[("missing_copybook", "MISSCPY")]["status"], "open")

    def test_one_file_per_gap(self):
        items = os.listdir(os.path.join(self.ws.out, "gaps", "items"))
        self.assertEqual(len(items), len(load_gaps(self.ws)))


class DuplicateTests(unittest.TestCase):
    def setUp(self):
        self.ws, self.src = sample_workspace(self)
        os.makedirs(os.path.join(self.src, "prod"))
        with open(os.path.join(self.src, "prod", "CUSTREC.cpy"), "w") as f:
            f.write("000100 01  OTHER-LAYOUT PIC X(9).\n")

    def test_differing_duplicate_is_a_gap_not_a_choice(self):
        run_all(self.ws)
        gaps = {(g["kind"], g["name"]): g for g in load_gaps(self.ws)}
        gap = gaps[("duplicate_member", "COPYBOOK CUSTREC")]
        self.assertEqual(len(gap["references"]), 2)
        edge = [e for e in load_map(self.ws)["edges"] if e["to"] == "copybook:CUSTREC"][0]
        self.assertEqual(edge["confidence"], "ambiguous")

    def test_precedence_rule_settles_it(self):
        self.ws.config["library_precedence"] = ["prod/"]
        self.ws.save()
        run_all(self.ws)
        gaps = {(g["kind"], g["name"]): g for g in load_gaps(self.ws)}
        self.assertNotIn(("duplicate_member", "COPYBOOK CUSTREC"), [k for k, g in gaps.items() if g["status"] == "open"])
        catalogue = load_catalogue(self.ws)
        chosen = [m for m in catalogue if m["name"] == "CUSTREC" and m.get("selected")]
        self.assertEqual(len(chosen), 1)
        self.assertIn("prod/", chosen[0]["path"])

    def test_identical_duplicate_is_not_a_gap(self):
        shutil.copy(os.path.join(self.src, "copy", "CUSTREC"), os.path.join(self.src, "prod", "CUSTREC.cpy"))
        run_all(self.ws)
        self.assertNotIn(("duplicate_member", "COPYBOOK CUSTREC"), {(g["kind"], g["name"]) for g in load_gaps(self.ws)})


class WorkspaceTests(unittest.TestCase):
    def test_missing_workspace_gives_plain_error(self):
        with self.assertRaises(ConfigError) as ctx:
            Workspace.load("/nonexistent/place")
        self.assertIn("mma.py init", str(ctx.exception))

    def test_wrong_source_path_gives_plain_error(self):
        ws, _ = sample_workspace(self)
        with self.assertRaises(ConfigError) as ctx:
            init_workspace(ws.root, ["does-not-exist"])
        self.assertIn("does-not-exist", str(ctx.exception))

    def test_config_is_valid_json_with_relative_paths(self):
        ws, _ = sample_workspace(self)
        with open(os.path.join(ws.out, "config.json")) as f:
            self.assertEqual(json.load(f)["source_roots"], ["src"])


if __name__ == "__main__":
    unittest.main()
