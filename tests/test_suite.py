"""Meaningful software/board-protocol checks, using only Python's standard library."""
from array import array
import contextlib
import io
import json
from pathlib import Path
import random
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "rp2040"))

from make_demo import generate
from omega_core import (CNF, PROJECT, MultiplexEvaluator, find_assignment, parse_cnf,
                        read_assignment, reference_evaluate, self_test, uniform_assignment,
                        validate_block, write_assignment)
from omega_model import RTLModel, SimBackend
from omega_transport import SerialBackend
from omega_board_server import BoardController, read_frame
from run_sat_hw import main


class Port:
    def __init__(self, get_value, set_value=None):
        self.get_value = get_value
        self.set_value = set_value

    @property
    def value(self):
        return self.get_value()

    @value.setter
    def value(self, value):
        if not self.set_value:
            raise RuntimeError("Puerto de solo lectura.")
        self.set_value(value)


class FakeBoard:
    """SDK double wired to the functional RTL model, with write/clock tracing."""
    def __init__(self):
        from types import SimpleNamespace
        self.model = RTLModel()
        self.ui_in = Port(lambda: self.model.ui, lambda val: setattr(self.model, "ui", val))
        self.uio_in = Port(lambda: self.model.uio, lambda val: setattr(self.model, "uio", val))
        self.uo_out = Port(self.model.outputs)
        self.uio_oe_pico = SimpleNamespace(value=0)
        self.manual_project_clock = SimpleNamespace(monitoring=True)
        self.auto_clocking = False
        self.mode = None
        self.writes = []
        self.clock_cycles = 0
        self.shuttle = SimpleNamespace(**{PROJECT: SimpleNamespace(enable=self.enable)})

    def enable(self):
        self.auto_clocking = True  # SDK enable() may start configured PWM.

    def clock_project_stop(self):
        self.auto_clocking = False

    def clock_project_once(self):
        if self.auto_clocking:
            raise RuntimeError("Se intento programar con PWM continuo.")
        if self.model.rst_n and self.model.uio & 3 == 3:
            self.writes.append((self.model.ui, self.model.uio))
        self.clock_cycles += 1
        self.model.rising_clock()

    def reset_project(self, asserted):
        self.model.rst_n = not asserted
        if asserted:
            self.model.reset()


class LoopSerial:
    """Bytes pass through the actual board-side JSON dispatcher and fake SDK."""
    def __init__(self, controller, transform=None, drop=False):
        self.controller = controller
        self.transform = transform
        self.drop = drop
        self.pending = bytearray(b"SDK startup diagnostic\n")
        self.closed = False

    def write(self, frame):
        request = json.loads(frame)
        response = self.controller.handle(request)
        if self.transform:
            response = self.transform(response)
        if not self.drop:
            self.pending.extend((json.dumps(response) + "\n").encode())
        return len(frame)

    def read(self, size):
        result = bytes(self.pending[:size])
        del self.pending[:size]
        if not result:
            time.sleep(0.0001)
        return result

    def close(self):
        self.closed = True


def serial_loop(transform=None, drop=False):
    board = FakeBoard()
    controller = BoardController(board, "ASIC_RP_CONTROL", settle_us=0)
    serial = LoopSerial(controller, transform, drop)
    backend = SerialBackend("test", serial_obj=serial, timeout=0.04)
    return board, controller, backend


class ParserTests(unittest.TestCase):
    def load_text(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.cnf"
            path.write_text(text, encoding="utf-8")
            return parse_cnf(path)

    def test_multiline_and_multiple_clauses_per_line(self):
        cnf = self.load_text("c comment\np cnf 4 3\n1 -2\nc comment inside clause\n3 0 4 0\n0\n")
        self.assertEqual(cnf.num_vars, 4)
        self.assertEqual([list(clause) for clause in cnf.clauses], [[1, -2, 3], [4], []])

    def test_reject_malformed(self):
        for text in ("1 0\n", "p cnf 1 1\n2 0\n", "p cnf 1 1\n1\n",
                     "p cnf 1 2\n1 0\n", "p cnf 1 0\n1 0\n", "p cnf -1 0\n",
                     "p cnf 1 1\np cnf 1 1\n1 0\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.load_text(text)

    def test_assignment_roundtrip_and_missing_conflicting_values(self):
        cnf = CNF(33, [array("i", [1, -33])])
        assignment = uniform_assignment(cnf, 0)
        assignment[33] = 1
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.txt"
            write_assignment(path, assignment)
            self.assertEqual(read_assignment(path, cnf), assignment)
            for text in ("v 1 0\n", "v 1 -1 33 0\n", "s UNSATISFIABLE\n", "v 1 34 0\n"):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    read_assignment(path, cnf)


class EvaluationTests(unittest.TestCase):
    def evaluate(self, cnf, assignment):
        return MultiplexEvaluator(SimBackend(), cross_check=True).evaluate(cnf, assignment)

    def test_truth_tables_and_spills(self):
        self.assertEqual(self_test(SimBackend())["gate_truth_table_cases"], 28)

    def test_empty_formula_and_empty_clause(self):
        for clauses, expected in (([], True), ([array("i")], False)):
            cnf = CNF(0, clauses)
            report = self.evaluate(cnf, bytearray(1))
            self.assertEqual(report["assignment_satisfies_formula"], expected)
            self.assertGreater(report["blocks"], 0)

    def test_random_cnfs_against_independent_evaluator(self):
        rng = random.Random(20261009)
        for _ in range(160):
            n = rng.randrange(1, 90)
            clauses = [array("i", [(1 if rng.randrange(2) else -1) * rng.randint(1, n)
                                    for _ in range(rng.randrange(0, 70))])
                       for _ in range(rng.randrange(0, 50))]
            cnf = CNF(n, clauses)
            assignment = bytearray([0] + [rng.randrange(2) for _ in range(n)])
            report = self.evaluate(cnf, assignment)
            self.assertEqual(report["assignment_satisfies_formula"], reference_evaluate(cnf, assignment))

    def test_300000_variables_both_assignments_and_last_id(self):
        cnf = CNF(300000, [array("i", range(1, 300001))])
        assignment = uniform_assignment(cnf, 0)
        for last in (0, 1):
            assignment[300000] = last
            report = self.evaluate(cnf, assignment)
            self.assertEqual(report["assignment_satisfies_formula"], bool(last))
            self.assertEqual(report["blocks"], 18751)
            self.assertEqual(report["gates_written"], 300001)

    def test_3sat_packing_uses_every_variable(self):
        with tempfile.TemporaryDirectory() as directory:
            generate(directory, 300000, "3sat", 42)
            cnf = parse_cnf(Path(directory) / "demo.cnf")
            assignment = read_assignment(Path(directory) / "assignment.txt", cnf)
            self.assertEqual(len(cnf.used_variables()), 300000)
            report = self.evaluate(cnf, assignment)
            self.assertTrue(report["assignment_satisfies_formula"])
            self.assertEqual(report["blocks"], 25000)
            self.assertEqual(report["gates_written"], 400000)

    def test_invalid_forward_refs_b_limit_and_oversized_blocks(self):
        for gates, targets in (([[1, 8, 0]], [8]), ([[1, 0, 16]], [8]),
                               ([[1, 0, 0]] * 17, [8]), ([[1, 0, 0]], [9]),
                               ([[True, 0, 0]], [8])):
            with self.assertRaises(ValueError):
                validate_block(gates, targets)

    def test_reject_bad_backend_data(self):
        class BadBackend:
            name = "broken"
            def execute(self, gates, targets):
                return [0]
        evaluator = MultiplexEvaluator(BadBackend(), cross_check=True)
        with self.assertRaises(RuntimeError):
            evaluator.execute([[1, 1, 0]], [8])


class ProtocolTests(unittest.TestCase):
    def test_full_roundtrip_through_actual_board_controller(self):
        board, controller, backend = serial_loop()
        report = self_test(backend)
        self.assertEqual(report["status"], "SELF_TEST_PASS")
        self.assertEqual(board.uio_oe_pico.value, 0xFB)
        self.assertFalse(board.auto_clocking)
        self.assertFalse(board.manual_project_clock.monitoring)
        self.assertEqual(board.model.uio, 0)
        self.assertGreater(len(board.writes), 28)
        backend.close()

    def test_exactly_one_write_per_gate_and_no_target_writes(self):
        board, controller, backend = serial_loop()
        backend.initialize()
        before = len(board.writes)
        gates = [[1, 0 if i == 0 else 7 + i, int(i == 15)] for i in range(16)]
        self.assertEqual(backend.execute(gates, [8, 23]), [0, 1])
        self.assertEqual(len(board.writes) - before, 16)
        self.assertEqual(board.model.wr_ptr, 0)
        self.assertEqual(board.model.uio, 0)

    def test_block_before_init_and_invalid_block_are_errors(self):
        board, controller, backend = serial_loop()
        with self.assertRaises(RuntimeError):
            backend.execute([[1, 0, 1]], [8])
        backend.initialize()
        before = len(board.writes)
        answer = controller.handle({"v": 1, "id": 99, "cmd": "block", "gates": [[1, 8, 0]], "targets": [8]})
        self.assertFalse(answer["ok"])
        self.assertEqual(before, len(board.writes))
        self.assertEqual(board.model.uio, 0)

    def test_done_bit_corruption_is_not_a_boolean_result(self):
        def corrupt(response):
            if "raw_outputs" in response:
                response["raw_outputs"][0] &= ~4
            return response
        _, _, backend = serial_loop(corrupt)
        backend.initialize()
        with self.assertRaises(RuntimeError):
            backend.execute([[1, 0, 1]], [8])

    def test_profile_mismatch(self):
        def corrupt(response):
            if "base_bits" in response:
                response["base_bits"][0] = 1
            return response
        _, _, backend = serial_loop(corrupt)
        with self.assertRaises(RuntimeError):
            backend.initialize()

    def test_timeout_never_becomes_zero_or_unsat(self):
        _, _, backend = serial_loop(drop=True)
        with self.assertRaises(TimeoutError):
            backend.initialize()

    def test_oversized_frame_is_rejected(self):
        with self.assertRaises(ValueError):
            read_frame(io.StringIO("x" * 4100 + "\n"))


class SolverAndCliTests(unittest.TestCase):
    def test_brute_sat_and_unsat(self):
        sat = parse_cnf(ROOT / "examples/small.cnf")
        status, assignment = find_assignment(sat, "brute")
        self.assertEqual(status, "SAT")
        self.assertTrue(reference_evaluate(sat, assignment))
        unsat = parse_cnf(ROOT / "examples/unsat.cnf")
        self.assertEqual(find_assignment(unsat, "brute"), ("UNSAT", None))

    def test_evaluate_false_is_not_unsat_and_has_distinct_exit_code(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["evaluate", str(ROOT / "examples/small.cnf"), "--backend", "sim", "--all", "0"])
        report = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "ASSIGNMENT_REJECTED")

    def test_solve_sat_produces_verified_assignment_and_report(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "model.txt"
            report = Path(directory) / "report.json"
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(["solve", str(ROOT / "examples/small.cnf"), "--backend", "sim",
                             "--solver", "brute", "--model-out", str(model), "--report", str(report)])
            data = json.loads(report.read_text())
            self.assertEqual(code, 0)
            self.assertTrue(data["verification_performed"])
            self.assertFalse(data["hardware_verified"])
            self.assertTrue(reference_evaluate(parse_cnf(ROOT / "examples/small.cnf"),
                                               read_assignment(model, parse_cnf(ROOT / "examples/small.cnf"))))

    def test_native_solver_api_budget_unknown_and_model_validation(self):
        # API double: validates our integration/control flow, not the native solver.
        class FakeSolver:
            answer = None
            model = [1]
            last = None
            def __init__(self, name, bootstrap_with):
                self.name = name
                self.clauses = list(bootstrap_with)
                self.budget = None
                FakeSolver.last = self
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def conf_budget(self, value):
                self.budget = value
            def solve_limited(self):
                return self.answer
            def solve(self):
                return self.answer
            def get_model(self):
                return self.model
        package, module = ModuleType("pysat"), ModuleType("pysat.solvers")
        module.Solver = FakeSolver
        with patch.dict(sys.modules, {"pysat": package, "pysat.solvers": module}):
            cnf = CNF(1, [array("i", [1])])
            self.assertEqual(find_assignment(cnf, "pysat", conflicts=100), ("UNKNOWN", None))
            self.assertEqual(FakeSolver.last.budget, 100)
            self.assertEqual(FakeSolver.last.name, "m22")
            FakeSolver.answer = True
            status, assignment = find_assignment(cnf, "pysat")
            self.assertEqual(status, "SAT")
            self.assertTrue(reference_evaluate(cnf, assignment))
            FakeSolver.model = [-1]
            with self.assertRaises(RuntimeError):
                find_assignment(cnf, "pysat")

    def test_unknown_cli_exit_is_distinct_and_does_not_write_model(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "model.txt"
            output = io.StringIO()
            with patch("run_sat_hw.find_assignment", return_value=("UNKNOWN", None)), contextlib.redirect_stdout(output):
                code = main(["solve", str(ROOT / "examples/small.cnf"), "--backend", "sim",
                             "--solver", "pysat", "--conflicts", "100", "--model-out", str(model)])
            report = json.loads(output.getvalue())
            self.assertEqual(code, 3)
            self.assertEqual(report["status"], "UNKNOWN")
            self.assertFalse(model.exists())
            self.assertFalse(report["verification_performed"])

    def test_reference_verilog_matches_recorded_identity(self):
        import hashlib
        profile = json.loads((ROOT / "RTL_PROFILE.json").read_text())
        source = (ROOT / profile["source"]).read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(), profile["source_sha256"])


if __name__ == "__main__":
    unittest.main()
