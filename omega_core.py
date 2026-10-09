"""DIMACS parsing and an external-memory scheduler for OMEGA's 16-gate RTL."""
from __future__ import annotations

from array import array
from dataclasses import dataclass
from itertools import islice, product
from pathlib import Path
from typing import Iterable
import time

OP_AND, OP_OR, OP_NAND, OP_NOR, OP_XOR, OP_XNOR, OP_NOT = range(7)
PROJECT = "tt_um_omega_infinity_kaoru"
PROFILE = "omega16-constant52-v1"
BASE_BITS = (0, 1, 0, 0, 1, 0, 1, 0)


@dataclass
class CNF:
    num_vars: int
    clauses: list[array]

    @property
    def num_literals(self) -> int:
        return sum(len(clause) for clause in self.clauses)

    def used_variables(self) -> set[int]:
        return {abs(lit) for clause in self.clauses for lit in clause}


def parse_cnf(path: str | Path) -> CNF:
    """Strict DIMACS, including clauses split across lines and empty clauses."""
    header = None
    clauses: list[array] = []
    current = array("i")
    with open(path, encoding="utf-8-sig") as stream:
        for line_no, raw in enumerate(stream, 1):
            line = raw.strip()
            if not line or line.startswith("c"):
                continue
            if line.startswith("p"):
                parts = line.split()
                if header is not None or clauses or current:
                    raise ValueError(f"Linea {line_no}: cabecera DIMACS duplicada/tardia.")
                if len(parts) != 4 or parts[:2] != ["p", "cnf"]:
                    raise ValueError(f"Linea {line_no}: se esperaba 'p cnf N M'.")
                n, m = int(parts[2]), int(parts[3])
                if not 0 <= n <= 2_147_483_647 or m < 0:
                    raise ValueError("N debe estar entre 0 y 2147483647; M debe ser >= 0.")
                header = n, m
                continue
            if header is None:
                raise ValueError(f"Linea {line_no}: falta la cabecera 'p cnf N M'.")
            for token in line.split():
                try:
                    lit = int(token)
                except ValueError as exc:
                    raise ValueError(f"Linea {line_no}: literal invalido {token!r}.") from exc
                if lit == 0:
                    clauses.append(current)
                    current = array("i")
                    if len(clauses) > header[1]:
                        raise ValueError("Hay mas clausulas que las declaradas en la cabecera.")
                else:
                    if abs(lit) > header[0]:
                        raise ValueError(f"Linea {line_no}: x{abs(lit)} excede N={header[0]}.")
                    current.append(lit)
    if header is None:
        raise ValueError("El archivo no contiene cabecera DIMACS.")
    if current:
        raise ValueError("La ultima clausula no termina con 0.")
    if len(clauses) != header[1]:
        raise ValueError(f"La cabecera declara {header[1]} clausulas; se leyeron {len(clauses)}.")
    return CNF(header[0], clauses)


def uniform_assignment(cnf: CNF, value: int) -> bytearray:
    if value not in (0, 1):
        raise ValueError("Una asignacion booleana debe ser 0 o 1.")
    # One-based indexing: assignment[300000] is the PC's x300000.
    return bytearray([value]) * (cnf.num_vars + 1)


def read_assignment(path: str | Path, cnf: CNF) -> bytearray:
    """Read signed literals, or SAT-competition 's'/'v' output. Used vars required."""
    assignment = bytearray(cnf.num_vars + 1)
    specified = bytearray(cnf.num_vars + 1)
    with open(path, encoding="utf-8-sig") as stream:
        for line_no, raw in enumerate(stream, 1):
            parts = raw.strip().split()
            if not parts or parts[0] == "c":
                continue
            if parts[0] in ("s", "SAT", "SATISFIABLE", "UNSAT", "UNSATISFIABLE", "UNKNOWN"):
                status = " ".join(parts).upper()
                if "UNSAT" in status or "UNKNOWN" in status:
                    raise ValueError("Ese archivo no contiene una asignacion SAT.")
                continue
            if parts[0] == "v":
                parts = parts[1:]
            for token in parts:
                try:
                    lit = int(token)
                except ValueError as exc:
                    raise ValueError(f"Asignacion, linea {line_no}: token invalido {token!r}.") from exc
                if lit == 0:
                    continue
                var, value = abs(lit), int(lit > 0)
                if var > cnf.num_vars:
                    raise ValueError(f"La asignacion menciona x{var}, pero N={cnf.num_vars}.")
                if specified[var] and assignment[var] != value:
                    raise ValueError(f"La asignacion da dos valores distintos a x{var}.")
                specified[var], assignment[var] = 1, value
    missing = [var for var in cnf.used_variables() if not specified[var]]
    if missing:
        preview = ", ".join(f"x{var}" for var in sorted(missing)[:8])
        raise ValueError(f"Faltan valores de variables utilizadas: {preview}.")
    return assignment


def write_assignment(path: str | Path, assignment: bytearray) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("s SATISFIABLE\n")
        for start in range(1, len(assignment), 100):
            literals = [str(var if assignment[var] else -var)
                        for var in range(start, min(start + 100, len(assignment)))]
            stream.write("v " + " ".join(literals) + " 0\n")


def literal_value(lit: int, assignment: bytearray) -> int:
    value = assignment[abs(lit)]
    return value if lit > 0 else 1 - value


def reference_evaluate(cnf: CNF, assignment: bytearray) -> bool:
    return all(any(literal_value(lit, assignment) for lit in clause) for clause in cnf.clauses)


def gate_value(op: int, a: int, b: int) -> int:
    if op == OP_AND:
        return a & b
    if op == OP_OR:
        return a | b
    if op == OP_NAND:
        return 1 - (a & b)
    if op == OP_NOR:
        return 1 - (a | b)
    if op == OP_XOR:
        return a ^ b
    if op == OP_XNOR:
        return 1 - (a ^ b)
    if op == OP_NOT:
        return 1 - a
    raise ValueError("Opcode invalido; se admite 0..6.")


def validate_block(gates: list, targets: list) -> None:
    if not isinstance(gates, (list, tuple)) or not 1 <= len(gates) <= 16:
        raise ValueError("Cada bloque debe contener entre 1 y 16 gates.")
    if not isinstance(targets, (list, tuple)) or not 1 <= len(targets) <= 16:
        raise ValueError("Se necesitan entre 1 y 16 nodos de salida.")
    for index, gate in enumerate(gates):
        if not isinstance(gate, (list, tuple)) or len(gate) != 3:
            raise ValueError("Cada gate debe ser [opcode, fuente_A, fuente_B].")
        op, a, b = gate
        if any(type(value) is not int for value in gate):
            raise ValueError("Opcode e indices deben ser enteros.")
        if not 0 <= op <= 6 or not 0 <= a < 8 + index or not 0 <= b < min(8 + index, 16):
            raise ValueError(f"Gate {index}: referencia futura o indice fuera del RTL.")
    if any(type(target) is not int or not 0 <= target < 8 + len(gates) for target in targets):
        raise ValueError("El nodo solicitado no existe en este bloque.")


class MultiplexEvaluator:
    """Pack OR chains into windows, spill values to the PC, then AND clause values."""

    def __init__(self, backend, *, cross_check: bool = False, progress=None):
        self.backend = backend
        self.cross_check = cross_check
        self.progress = progress
        self.blocks = 0
        self.gates_written = 0
        self.outputs_read = 0

    def execute(self, gates: list, targets: list) -> list[int]:
        validate_block(gates, targets)
        values = self.backend.execute(gates, targets)
        if len(values) != len(targets) or any(type(value) is not int or value not in (0, 1) for value in values):
            raise RuntimeError("Respuesta incompleta o no booleana de la placa.")
        if self.cross_check:
            nodes = list(BASE_BITS)
            for op, a, b in gates:
                nodes.append(gate_value(op, nodes[a], nodes[b]))
            expected = [nodes[target] for target in targets]
            if values != expected:
                raise RuntimeError(f"Discrepancia chip/referencia: {values} frente a {expected}.")
        self.blocks += 1
        self.gates_written += len(gates)
        self.outputs_read += len(targets)
        if self.progress and self.blocks % 1000 == 0:
            self.progress(self.blocks, self.gates_written)
        return values

    def clause_results(self, cnf: CNF, assignment: bytearray) -> Iterable[int]:
        gates: list[list[int]] = []
        completed_targets: list[int] = []

        def flush(partial=None):
            targets = completed_targets[:] + ([] if partial is None else [partial])
            values = self.execute(gates, targets)
            gates.clear()
            completed_targets.clear()
            return (values, None) if partial is None else (values[:-1], values[-1])

        for clause in cnf.clauses:
            # Identity of OR is 0. Empty clauses get an actual OR(0,0) operation.
            cursor = 0
            length = max(1, len(clause))
            for offset in range(length):
                bit = literal_value(clause[offset], assignment) if clause else 0
                # BASE_BITS[bit] == bit: data enters via configuration selectors.
                gates.append([OP_OR, cursor, bit])
                cursor = 8 + len(gates) - 1
                finished = offset == length - 1
                if finished:
                    completed_targets.append(cursor)
                if len(gates) == 16:
                    values, carry = flush(None if finished else cursor)
                    if not finished:
                        cursor = carry  # PC value reinjected as constant-node index.
                    yield from values
        if gates:
            values, _ = flush()
            yield from values

    def reduce_values(self, op: int, values: Iterable[int]) -> int:
        if op not in (OP_AND, OP_OR):
            raise ValueError("La reduccion requiere AND u OR.")
        identity = int(op == OP_AND)
        carry = identity
        iterator = iter(values)
        any_block = False
        while True:
            chunk = list(islice(iterator, 16))
            if not chunk:
                break
            gates = [[op, carry if index == 0 else 8 + index - 1, int(bit)]
                     for index, bit in enumerate(chunk)]
            carry = self.execute(gates, [7 + len(gates)])[0]
            any_block = True
        if not any_block:
            carry = self.execute([[op, identity, identity]], [8])[0]
        return carry

    def evaluate(self, cnf: CNF, assignment: bytearray) -> dict:
        if len(assignment) != cnf.num_vars + 1 or any(value not in (0, 1) for value in assignment):
            raise ValueError("La asignacion debe tener N+1 bytes booleanos (indice 0 sin uso).")
        self.blocks = self.gates_written = self.outputs_read = 0
        started = time.perf_counter()
        result = self.reduce_values(OP_AND, self.clause_results(cnf, assignment))
        return {
            "mode": "evaluation", "backend": self.backend.name,
            "status": "ASSIGNMENT_SATISFIES" if result else "ASSIGNMENT_REJECTED",
            "assignment_satisfies_formula": bool(result),
            "variables": cnf.num_vars, "clauses": len(cnf.clauses),
            "literals": cnf.num_literals, "blocks": self.blocks,
            "gates_written": self.gates_written, "outputs_read": self.outputs_read,
            "elapsed_seconds": round(time.perf_counter() - started, 6),
            "cross_checked": self.cross_check,
        }


def self_test(backend) -> dict:
    backend.initialize()
    evaluator = MultiplexEvaluator(backend, cross_check=True)
    cases = 0
    for op in range(7):
        for a, b in product((0, 1), repeat=2):
            result = evaluator.execute([[op, a, b]], [8])[0]
            if result != gate_value(op, a, b):
                raise RuntimeError(f"Fallo de gate op={op}, a={a}, b={b}.")
            cases += 1
    gates = [[OP_OR, 0 if i == 0 else 8 + i - 1, int(i == 15)] for i in range(16)]
    if evaluator.execute(gates, [8, 15, 23]) != [0, 0, 1]:
        raise RuntimeError("Fallo en el bloque de 16 gates/lectura de varios nodos.")
    cnf = CNF(33, [array("i", range(1, 34)), array("i", [-1, 33])])
    assignment = uniform_assignment(cnf, 0)
    assignment[33] = 1
    report = evaluator.evaluate(cnf, assignment)
    if not report["assignment_satisfies_formula"]:
        raise RuntimeError("Fallo al trasladar resultados entre bloques.")
    return {"status": "SELF_TEST_PASS", "backend": backend.name,
            "gate_truth_table_cases": cases, "cross_block_and_multi_output": True}


def find_assignment(cnf: CNF, solver_name: str, *, conflicts: int = 0):
    """Complete PC search, or UNKNOWN when a native solver's budget expires."""
    if solver_name == "brute":
        used = sorted(cnf.used_variables())
        if len(used) > 20:
            raise ValueError("El solver didactico brute admite hasta 20 variables usadas; usa pysat.")
        assignment = uniform_assignment(cnf, 0)
        for bits in product((0, 1), repeat=len(used)):
            for var, bit in zip(used, bits):
                assignment[var] = bit
            if reference_evaluate(cnf, assignment):
                return "SAT", assignment
        return "UNSAT", None
    try:
        from pysat.solvers import Solver
    except ImportError as exc:
        raise RuntimeError("Instala el solver opcional: python -m pip install python-sat") from exc
    with Solver(name="m22", bootstrap_with=(list(clause) for clause in cnf.clauses)) as solver:
        if conflicts:
            solver.conf_budget(conflicts)
            answer = solver.solve_limited()
        else:
            answer = solver.solve()
        if answer is None:
            return "UNKNOWN", None
        if not answer:
            return "UNSAT", None
        assignment = uniform_assignment(cnf, 0)
        for lit in solver.get_model() or []:
            if abs(lit) <= cnf.num_vars:
                assignment[abs(lit)] = int(lit > 0)
    if not reference_evaluate(cnf, assignment):
        raise RuntimeError("El modelo del solver no satisface la CNF; se detuvo la verificacion.")
    return "SAT", assignment
