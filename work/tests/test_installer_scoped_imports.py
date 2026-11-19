"""The installer modules import some modules inside functions only. A function that names such a module must
import it in its own scope chain, or it raises NameError at run time (the 2026-11-15 setup crash: _install_rest
named thinker_flow without importing it). Static, so it covers branches no test run reaches."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import install as inst              # noqa: E402


def test_no_function_uses_a_module_it_never_imports():
    """The class of the Part 3 crash: these modules import some modules inside functions only (to keep start-up and
    the bootstrap light). A function -- or a function nested in one -- that names such a module must import it in
    its own scope chain; a sibling's import does not count. Static, so it covers branches no run reaches."""
    bad = []
    for name in ("install.py", "bootstrap.py", "installer_exit.py", "thinker_flow.py", "thinker_state.py",
                 "fetch.py", "manifest.py", "preflight.py", "transact.py", "receipt.py", "patch_helptext.py"):
        path = Path(inst.__file__).parent / name
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bad += _unimported_uses(tree, name)
    assert not bad, "\n".join(bad)


_FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)


def _imported(node) -> set:
    return {(a.asname or a.name).split(".")[0] for a in node.names}


def _children(n) -> list:
    """A scope's own statements (a def's or class's body), else a node's children."""
    if isinstance(n, (*_FUNC, ast.ClassDef)):
        return list(n.body)
    return list(ast.iter_child_nodes(n))


def _scope_bindings(owner) -> set:
    """Names one scope binds (its parameters, imports, assignments, defs), not descending into nested functions,
    classes or lambdas -- those are scopes of their own."""
    out = {a.arg for a in ast.walk(owner.args) if isinstance(a, ast.arg)} if isinstance(owner, _FUNC) else set()
    todo = _children(owner)
    while todo:
        n = todo.pop()
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            out |= _imported(n)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            out.add(n.id)
        elif isinstance(n, (*_FUNC, ast.ClassDef)):
            out.add(n.name)
            continue
        elif isinstance(n, ast.Lambda):
            continue
        todo.extend(ast.iter_child_nodes(n))
    return out


def _unimported_uses(tree, name: str) -> list:
    top = _scope_bindings(tree)
    local_only = {m for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                  for m in _imported(n)} - top
    bad = []

    def visit(fn, outer: set):
        here = outer | _scope_bindings(fn)
        todo = _children(fn)
        while todo:
            n = todo.pop()
            if isinstance(n, _FUNC):
                visit(n, here)                          # a closure sees its enclosing function's names
                continue
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in local_only and n.id not in here:
                bad.append(f"{name}:{n.lineno}: {fn.name} uses {n.id} without importing it")
            todo.extend(ast.iter_child_nodes(n))

    # every function not nested in another: module level (under if / try too) and class methods
    todo = list(tree.body)
    while todo:
        n = todo.pop()
        if isinstance(n, _FUNC):
            visit(n, set())
        elif not isinstance(n, ast.expr):
            todo.extend(_children(n))
    return sorted(set(bad))
    assert not any("as before" in t for t in said)

