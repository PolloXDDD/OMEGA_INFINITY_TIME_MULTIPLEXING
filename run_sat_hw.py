#!/usr/bin/env python3
"""PC entry point: evaluate through the chip, or search on PC and verify on chip."""
import argparse
import json
from pathlib import Path
import sys
import time

from omega_core import (PROJECT, MultiplexEvaluator, find_assignment, parse_cnf,
                        read_assignment, reference_evaluate, self_test,
                        uniform_assignment, write_assignment)
from omega_model import SimBackend
from omega_transport import SerialBackend


def build_parser():
    parser = argparse.ArgumentParser(description="OMEGA INFINITY: time-multiplexing externo de 16 gates.")
    sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--backend", choices=("serial", "sim"), default="serial")
    common.add_argument("--port", help="Puerto USB: COM3 o /dev/ttyACM0, por ejemplo.")
    common.add_argument("--project", default=PROJECT)
    common.add_argument("--timeout", type=float, default=10.0, help="Timeout por transaccion USB, en segundos.")
    common.add_argument("--report", type=Path, help="Guardar resultado y estadisticas en JSON.")
    common.add_argument("--cross-check", action="store_true", help="Comparar cada bloque con una referencia en CPU.")
    sub.add_parser("probe", parents=[common], help="Seleccionar el proyecto y comprobar sus ocho nodos base.")
    sub.add_parser("self-test", parents=[common], help="Probar los siete opcodes y transferencias entre bloques.")
    evaluate = sub.add_parser("evaluate", parents=[common], help="Evaluar una asignacion concreta mediante los gates.")
    evaluate.add_argument("cnf", type=Path)
    values = evaluate.add_mutually_exclusive_group(required=True)
    values.add_argument("--assignment", type=Path, help="Archivo de literales con valores de las variables.")
    values.add_argument("--all", type=int, choices=(0, 1), help="Asignar 0 o 1 a todas las variables.")
    solve = sub.add_parser("solve", parents=[common], help="Buscar en PC y verificar el modelo con los gates.")
    solve.add_argument("cnf", type=Path)
    solve.add_argument("--solver", choices=("pysat", "brute"), default="pysat")
    solve.add_argument("--conflicts", type=int, default=0, help="Presupuesto PySAT: 0=sin limite; agotado=UNKNOWN.")
    solve.add_argument("--model-out", type=Path, default=Path("assignment.txt"))
    return parser


def open_backend(args):
    if args.backend == "sim":
        return SimBackend(args.project)
    if not args.port:
        raise ValueError("El modo serial requiere --port COM3 (o el puerto correspondiente).")
    return SerialBackend(args.port, project=args.project, timeout=args.timeout)


def print_report(report, path=None):
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")


def main(argv=None):
    args = build_parser().parse_args(argv)
    backend = None
    try:
        if getattr(args, "conflicts", 0) < 0:
            raise ValueError("--conflicts debe ser >= 0.")
        cnf = parse_cnf(args.cnf) if args.command in ("evaluate", "solve") else None
        if args.command == "evaluate":
            assignment = (read_assignment(args.assignment, cnf) if args.assignment
                          else uniform_assignment(cnf, args.all))
        if args.command == "solve":
            # Opening the board first catches configuration errors before a long search.
            backend = open_backend(args)
            backend.initialize()
            started = time.perf_counter()
            status, assignment = find_assignment(cnf, args.solver, conflicts=args.conflicts)
            report = {"mode": "solve", "status": status, "search_backend": "PC/" + args.solver,
                      "verification_backend": backend.name, "variables": cnf.num_vars,
                      "clauses": len(cnf.clauses), "search_seconds": round(time.perf_counter() - started, 6),
                      "hardware_verified": False, "verification_performed": False}
            if status == "SAT":
                evaluator = MultiplexEvaluator(backend, cross_check=args.cross_check, progress=progress)
                verification = evaluator.evaluate(cnf, assignment)
                if not verification["assignment_satisfies_formula"] or not reference_evaluate(cnf, assignment):
                    raise RuntimeError("La candidata SAT fallo la verificacion; no se emitio un resultado SAT/UNSAT.")
                write_assignment(args.model_out, assignment)
                report.update(verification=verification, verification_performed=True,
                              hardware_verified=args.backend == "serial", model_file=str(args.model_out))
            elif status == "UNSAT":
                report["decision_source"] = "PC/" + args.solver
            else:
                report["reason"] = "Presupuesto agotado o busqueda interrumpida; no hay decision SAT/UNSAT."
            print_report(report, args.report)
            return 3 if status == "UNKNOWN" else 0
        backend = open_backend(args)
        if args.command == "self-test":
            report = self_test(backend)
        elif args.command == "probe":
            report = {"status": "PROFILE_MATCH", **backend.initialize()}
        else:
            backend.initialize()
            evaluator = MultiplexEvaluator(backend, cross_check=args.cross_check, progress=progress)
            report = evaluator.evaluate(cnf, assignment)
        print_report(report, args.report)
        if args.command == "evaluate" and not report["assignment_satisfies_formula"]:
            return 1
        return 0
    except KeyboardInterrupt:
        print("Interrumpido por el usuario; no se concluyo UNSAT.", file=sys.stderr)
        return 130
    except Exception as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2
    finally:
        if backend is not None:
            backend.close()


def progress(blocks, gates):
    print(f"Progreso: {blocks:,} bloques; {gates:,} gates programados.", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
