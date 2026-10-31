"""Deterministic integer constraint solving for exact checks.

Frontier models are unreliable at bitwise arithmetic. This module gives the
agent a mathematical oracle: Z3 when installed, and a bounded pure-Python
fallback for small finite domains. The fallback is explicit about its limits
instead of pretending an unbounded search happened.
"""

from __future__ import annotations

import itertools
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

try:  # optional
    import z3  # type: ignore
except Exception:  # pragma: no cover - depends on the host
    z3 = None  # type: ignore


class SymbolicError(Exception):
    pass


@dataclass
class SolveResult:
    status: str                       # sat | unsat | unknown
    method: str
    model: dict[str, int] = field(default_factory=dict)
    tried: int = 0
    reason: str = ""
    z3_available: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def z3_available() -> bool:
    return z3 is not None


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        return int(value, 0)
    raise SymbolicError(f"not an integer: {value!r}")


def _expr(expr: Any, env: dict[str, int], bits: int) -> int:
    if not isinstance(expr, dict):
        return _int(expr)
    mask = (1 << bits) - 1
    if "var" in expr:
        name = str(expr["var"])
        if name not in env:
            raise SymbolicError(f"unknown variable: {name}")
        return env[name] & mask
    if "const" in expr:
        return _int(expr["const"]) & mask
    if "neg" in expr:
        return (-_expr(expr["neg"], env, bits)) & mask
    if "not" in expr:
        return (~_expr(expr["not"], env, bits)) & mask
    for op in ("add", "sub", "mul", "xor", "and", "or", "shl", "shr", "mod"):
        if op in expr:
            args = expr[op]
            if not isinstance(args, list) or not args:
                raise SymbolicError(f"{op} needs a non-empty list")
            vals = [_expr(a, env, bits) for a in args]
            if op == "add":
                return sum(vals) & mask
            if op == "sub":
                out = vals[0]
                for v in vals[1:]:
                    out -= v
                return out & mask
            if op == "mul":
                out = 1
                for v in vals:
                    out *= v
                return out & mask
            if op == "xor":
                out = 0
                for v in vals:
                    out ^= v
                return out & mask
            if op == "and":
                out = mask
                for v in vals:
                    out &= v
                return out & mask
            if op == "or":
                out = 0
                for v in vals:
                    out |= v
                return out & mask
            if op == "shl":
                return (vals[0] << (vals[1] % bits)) & mask
            if op == "shr":
                return (vals[0] >> (vals[1] % bits)) & mask
            if op == "mod":
                if vals[1] == 0:
                    raise SymbolicError("mod by zero")
                return vals[0] % vals[1]
    raise SymbolicError(f"unsupported expression: {expr}")


def _check(constraint: dict[str, Any], env: dict[str, int], bits: int) -> bool:
    op = str(constraint.get("op") or "").lower()
    left = _expr(constraint.get("left"), env, bits)
    right = _expr(constraint.get("right"), env, bits)
    if op == "eq":
        return left == right
    if op == "ne":
        return left != right
    if op == "lt":
        return left < right
    if op == "le":
        return left <= right
    if op == "gt":
        return left > right
    if op == "ge":
        return left >= right
    raise SymbolicError(f"unsupported constraint op: {op or '(missing)'}")


def _variables(spec: Any, bits: int) -> list[tuple[str, int, int]]:
    if spec is None:
        return []
    rows: list[tuple[str, int, int]] = []
    if isinstance(spec, dict):
        items = list(spec.items())
    elif isinstance(spec, list):
        items = []
        for row in spec:
            if isinstance(row, str):
                items.append((row, {}))
            elif isinstance(row, dict):
                items.append((str(row.get("name") or ""), row))
    else:
        raise SymbolicError("variables must be an object or list")
    for name, value in items:
        name = str(name or "").strip()
        if not name:
            continue
        if isinstance(value, dict):
            lo = _int(value.get("min", 0))
            hi = _int(value.get("max", 255 if bits <= 8 else 65535))
        else:
            lo, hi = 0, (_int(value) if value is not None else
                          (255 if bits <= 8 else 65535))
        if hi < lo:
            raise SymbolicError(f"variable {name} has max < min")
        rows.append((name, lo, hi))
    if len(rows) > 8:
        raise SymbolicError("at most 8 variables are allowed")
    return rows


def _z3_expr(expr: Any, variables: dict[str, Any], bits: int):
    if not isinstance(expr, dict):
        return z3.BitVecVal(_int(expr), bits)
    if "var" in expr:
        name = str(expr["var"])
        if name not in variables:
            raise SymbolicError(f"unknown variable: {name}")
        return variables[name]
    if "const" in expr:
        return z3.BitVecVal(_int(expr["const"]) & ((1 << bits) - 1), bits)
    if "neg" in expr:
        return -_z3_expr(expr["neg"], variables, bits)
    if "not" in expr:
        return ~_z3_expr(expr["not"], variables, bits)
    for op in ("add", "sub", "mul", "xor", "and", "or", "shl", "shr", "mod"):
        if op in expr:
            args = expr[op]
            if not isinstance(args, list) or not args:
                raise SymbolicError(f"{op} needs a non-empty list")
            vals = [_z3_expr(a, variables, bits) for a in args]
            out = vals[0]
            if op in ("add", "mul", "xor", "and", "or"):
                out = vals[0]
                for v in vals[1:]:
                    out = {"add": out + v, "mul": out * v, "xor": out ^ v,
                           "and": out & v, "or": out | v}[op]
            elif op == "sub":
                for v in vals[1:]:
                    out -= v
            elif op == "shl":
                out = out << vals[1]
            elif op == "shr":
                out = z3.LShR(out, vals[1])
            elif op == "mod":
                out = z3.URem(out, vals[1])
            return out
    raise SymbolicError(f"unsupported expression: {expr}")


def _solve_z3(constraints, variables_spec, bits, timeout):
    variables = {name: z3.BitVec(name, bits) for name, _lo, _hi in variables_spec}
    solver = z3.Solver()
    solver.set("timeout", max(1, int(timeout * 1000)))
    for name, lo, hi in variables_spec:
        solver.add(z3.UGE(variables[name], z3.BitVecVal(lo, bits)))
        solver.add(z3.ULE(variables[name], z3.BitVecVal(hi, bits)))
    for c in constraints:
        left = _z3_expr(c.get("left"), variables, bits)
        right = _z3_expr(c.get("right"), variables, bits)
        op = str(c.get("op") or "").lower()
        cmp = {"eq": left == right, "ne": left != right,
               "lt": z3.ULT(left, right), "le": z3.ULE(left, right),
               "gt": z3.UGT(left, right), "ge": z3.UGE(left, right)}.get(op)
        if cmp is None:
            raise SymbolicError(f"unsupported constraint op: {op}")
        solver.add(cmp)
    check = solver.check()
    if check == z3.sat:
        model = solver.model()
        values = {name: model.eval(variables[name], model_completion=True).as_long()
                  for name in variables}
        return SolveResult("sat", "z3", values, z3_available=True)
    if check == z3.unsat:
        return SolveResult("unsat", "z3", z3_available=True)
    return SolveResult("unknown", "z3", reason="z3 timed out", z3_available=True)


def solve(constraints: list[dict[str, Any]], variables: Any = None, *,
          bits: int = 64, max_candidates: int = 200_000,
          timeout: float = 2.0) -> SolveResult:
    """Solve integer constraints, using Z3 when installed.

    The fallback enumerates finite variable domains. If the domain is larger
    than ``max_candidates`` the result is ``unknown``, never a false claim.
    """
    constraints = [c for c in (constraints or []) if isinstance(c, dict)]
    if not constraints:
        raise SymbolicError("at least one constraint is required")
    bits = max(1, min(int(bits), 128))
    specs = _variables(variables, bits)
    names = {name for name, _lo, _hi in specs}
    for c in constraints:
        for side in ("left", "right"):
            expr = c.get(side)
            if isinstance(expr, dict) and "var" in expr and str(expr["var"]) not in names:
                raise SymbolicError(f"unknown variable: {expr['var']}")
    if z3 is not None:
        return _solve_z3(constraints, specs, bits, timeout)
    if not specs:
        env: dict[str, int] = {}
        for c in constraints:
            if not _check(c, env, bits):
                return SolveResult("unsat", "constant evaluation", z3_available=False)
        return SolveResult("sat", "constant evaluation", {}, z3_available=False)
    total = 1
    for _name, lo, hi in specs:
        total *= (hi - lo + 1)
        if total > max_candidates:
            return SolveResult(
                "unknown", "bounded enumeration", tried=0,
                reason=(f"domain has more than {max_candidates} candidates; "
                        "add ranges or install z3 for unbounded solving"),
                z3_available=False)
    started = time.monotonic()
    tried = 0
    for values in itertools.product(*(range(lo, hi + 1) for _n, lo, hi in specs)):
        tried += 1
        env = {name: v for (name, _lo, _hi), v in zip(specs, values)}
        if all(_check(c, env, bits) for c in constraints):
            return SolveResult("sat", "bounded enumeration", env, tried,
                               z3_available=False)
        if time.monotonic() - started > timeout:
            return SolveResult("unknown", "bounded enumeration", tried=tried,
                               reason="timeout", z3_available=False)
    return SolveResult("unsat", "bounded enumeration", tried=tried,
                       z3_available=False)
