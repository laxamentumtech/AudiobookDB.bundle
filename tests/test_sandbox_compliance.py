# -*- coding: utf-8 -*-
"""
Sandbox compliance guard for the shipped bundle code.

Plex compiles plug-in code with RestrictedPython's "standard policy"
(Framework 2.6.3). ``RestrictionMutator.checkName`` / ``checkAttrName`` reject
at COMPILE TIME every identifier, attribute name, parameter name and import
alias that starts with ``_``; the only names allowed through are the bare
``_`` and the dunder names ``__init__``, ``__call__``, ``__str__`` and
``__repr__``. Module names in ``import`` / ``from ... import`` statements are
NOT checked, so ``from _version import version`` stays legal.

Live evidence (this is the bug this test prevents from coming back): on
2026-10-17 Plex Media Server 1.43.5 refused to load the agent and logged

    SyntaxError: Line 20: "_decode" is an invalid variable name because it
    starts with "_"

the bundle was therefore dead on arrival as a plug-in, and reinstalling it
could never fix that.

The test parses every ``Contents/Code/*.py`` with ``ast`` and fails listing
``file:lineno: name`` for any banned name, so a module the sandbox cannot
compile can never ship again. It runs under both Python 2.7 (``make
test-py2``) and Python 3 (``make test``), hence no f-strings, no annotations
and ``io.open`` for reading sources.

The second half of the file guards the sandbox's *runtime* environment. The
bundle runs under Plex's ``StandardPolicy`` (``Framework/policies/
standardpolicy.py`` is ``pass``, and ``Framework/policies/base.py`` has an
empty ``environment = {}``), so the only usable names are RestrictedPython's
``safe_builtins`` (abs, bool, callable, chr, cmp, complex, divmod, float,
hash, hex, id, int, isinstance, issubclass, len, long, oct, ord, pow, range,
repr, round, str, tuple, unichr, unicode, xrange, zip, setattr, delattr and
the exception classes) plus the explicit env dict in
``Framework/code/sandbox.py`` (str, unicode, min, max, list, dict, set,
sorted, reversed, reduce, filter, map, enumerate, object, property,
staticmethod, classmethod, xrange, hexlify, unhexlify). ``getattr``,
``hasattr``, ``setattr``, ``dir``, ``super`` and ``type`` exist only under
``ElevatedPolicy``, which system bundles use -- this plugin does not.
Everything else (``bytes``, ``open``, ``sum``, ``any``, ``all``, ``iter``,
``next``, ...) resolves to a NameError at runtime, *even though the py3 test
run happily provides it*; the second check therefore flags such uses.

The sanctioned feature-detection idiom (a ``try`` whose handler catches
``NameError``, bare ``except:`` included) is exempt, so
``try: BYTES_TYPE = bytes / except NameError: BYTES_TYPE = str`` is allowed.
Names shadowed by a local binding (e.g. the ``input`` parameter of
``SearchTool.search_asin``) are not references to the builtin and are skipped.
"""

import ast
import io
import os
import unittest

try:
    string_types = (str, unicode)
except NameError:  # Python 3
    string_types = (str,)

# Names the sandbox accepts even though they start with an underscore.
ALLOWED_NAMES = frozenset([
    '_',
    '__init__',
    '__call__',
    '__str__',
    '__repr__',
])

# (AST node class name, attribute holding the identifier). Both the Python 3 /
# Python 2.7 node names and the pre-2.6 old-style node names are listed; the
# classes a given interpreter does not define are simply never matched.
IDENTIFIER_ATTRS = (
    ('Name', 'id'),
    ('Attribute', 'attr'),
    ('Getattr', 'attrname'),
    ('AssName', 'name'),
    ('AssAttr', 'attrname'),
    ('FunctionDef', 'name'),
    ('Function', 'name'),
    ('ClassDef', 'name'),
    ('Class', 'name'),
    ('alias', 'asname'),
    ('arg', 'arg'),
)

CODE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'Contents', 'Code')


def iter_identifiers(tree):
    """Yields ``(lineno, name)`` for every identifier the sandbox checks."""
    for node in ast.walk(tree):
        node_type = type(node).__name__
        lineno = getattr(node, 'lineno', 0)
        for class_name, attr in IDENTIFIER_ATTRS:
            if node_type != class_name:
                continue
            name = getattr(node, attr, None)
            if isinstance(name, string_types):
                yield lineno, name
        # Old-style AST kept function parameters as plain strings.
        arg_names = getattr(node, 'argnames', None)
        if arg_names:
            for name in arg_names:
                if isinstance(name, string_types):
                    yield lineno, name


def parse_source(source):
    """Parses source, working around a Python 2 ``compile()`` limitation.

    Python 2 refuses a *unicode* string that carries a PEP 263 coding
    declaration ("SyntaxError: encoding declaration in Unicode string"), so
    the source is always handed to the parser as bytes. Files are still read
    as UTF-8 text; only the parse input is re-encoded.
    """
    if not isinstance(source, bytes):
        source = source.encode('utf-8')
    return ast.parse(source)


def banned_names(source):
    """Returns ``[(lineno, name), ...]`` for banned identifiers in source."""
    tree = parse_source(source)
    found = []
    seen = set()
    for lineno, name in iter_identifiers(tree):
        if not name.startswith('_') or name in ALLOWED_NAMES:
            continue
        key = (lineno, name)
        if key in seen:
            continue
        seen.add(key)
        found.append(key)
    found.sort()
    return found


def shipped_code_files():
    """Returns the sorted names of the shipped bundle modules."""
    return sorted(
        name for name in os.listdir(CODE_DIR)
        if name.endswith('.py')
    )


def shipped_sources():
    """Yields ``(display_path, source_text)`` for every shipped module."""
    for name in shipped_code_files():
        path = os.path.join(CODE_DIR, name)
        with io.open(path, encoding='utf-8') as handle:
            yield os.path.join('Contents', 'Code', name), handle.read()


# Builtins the sandbox does NOT provide (see the module docstring): neither
# RestrictedPython's ``safe_builtins`` nor the env dict of
# ``Framework/code/sandbox.py`` defines them, and ``StandardPolicy`` adds
# nothing. ``getattr``/``hasattr``/``setattr``/``dir``/``super``/``type`` are
# ``ElevatedPolicy``-only. Using any of these is a runtime NameError inside
# Plex, even though a plain Python 3 test run provides them.
UNAVAILABLE_BUILTINS = frozenset([
    'bytes', 'getattr', 'hasattr', 'open', 'file', 'input', 'raw_input',
    'eval', 'exec', 'compile', 'globals', 'locals', 'vars', 'dir', 'sum',
    'any', 'all', 'iter', 'next', 'type', 'super', 'apply', 'buffer',
    'slice', 'frozenset', 'reload', 'intern', 'coerce',
])

# Name contexts that *bind* a name instead of reading one.
BINDING_CTXS = ('Param', 'Store', 'Del')

_SCOPE_NODES = ('FunctionDef', 'Function', 'Lambda')


def handler_catches_nameerror(handler):
    """True when this except clause catches NameError (bare ``except:`` too)."""
    exc_type = getattr(handler, 'type', None)
    if exc_type is None:
        return True
    if isinstance(exc_type, ast.Name):
        return exc_type.id == 'NameError'
    if isinstance(exc_type, ast.Tuple):
        for element in exc_type.elts:
            if isinstance(element, ast.Name) and element.id == 'NameError':
                return True
    return False


def add_bound_names(scope, names):
    """Adds every name bound in ``scope``, without descending into nested scopes.

    Covers parameters (``ast.arg`` under Python 3, ``ast.Name(ctx=Param)`` or
    ``argnames`` under Python 2), assignment targets and the names of nested
    functions/classes.
    """
    if type(scope).__name__ in _SCOPE_NODES:
        args = getattr(scope, 'args', None)
        if args is not None:
            parameters = list(getattr(args, 'args', None) or [])
            for extra in ('vararg', 'kwarg'):
                node = getattr(args, extra, None)
                if node is not None:
                    parameters.append(node)
            for parameter in parameters:
                name = getattr(parameter, 'arg', None) or \
                    getattr(parameter, 'id', None)
                if isinstance(name, string_types):
                    names.add(name)
        for name in getattr(scope, 'argnames', None) or []:
            if isinstance(name, string_types):
                names.add(name)
    for child in ast.iter_child_nodes(scope):
        child_type = type(child).__name__
        if child_type in ('FunctionDef', 'Function', 'ClassDef', 'Class',
                          'Lambda'):
            name = getattr(child, 'name', None)
            if isinstance(name, string_types):
                names.add(name)
            continue
        if child_type == 'Name':
            if type(getattr(child, 'ctx', None)).__name__ in ('Store', 'Del'):
                names.add(child.id)
        elif child_type == 'AssName':
            names.add(child.name)
        add_bound_names(child, names)
    return names


def collect_builtin_uses(node, bound_stack, found, exempt):
    """Walks ``node`` collecting uses of sandbox-unavailable builtins."""
    node_type = type(node).__name__
    if node_type in ('FunctionDef', 'Function', 'ClassDef', 'Class', 'Lambda'):
        scope_names = add_bound_names(node, set())
        for child in ast.iter_child_nodes(node):
            collect_builtin_uses(
                child, bound_stack + [scope_names], found, exempt)
        return
    if node_type == 'Name':
        if type(getattr(node, 'ctx', None)).__name__ in BINDING_CTXS:
            return  # a binding, not a use
        name = getattr(node, 'id', None)
        if name in UNAVAILABLE_BUILTINS and not exempt:
            if not any(name in scope for scope in bound_stack):
                found.append((getattr(node, 'lineno', 0), name))
        return
    guards_nameerror = False
    if node_type in ('Try', 'TryExcept', 'TryFinally'):
        guards_nameerror = any(
            handler_catches_nameerror(handler)
            for handler in getattr(node, 'handlers', None) or [])
    for child in ast.iter_child_nodes(node):
        if guards_nameerror and any(child is item for item in node.body):
            continue
        collect_builtin_uses(child, bound_stack, found, exempt)
    if guards_nameerror:
        # Feature detection: ``try: X = bytes / except NameError: ...``
        for child in node.body:
            collect_builtin_uses(child, bound_stack, found, True)


def unavailable_builtin_uses(source):
    """Returns ``[(lineno, name), ...]`` for uses of missing builtins."""
    tree = parse_source(source)
    found = []
    collect_builtin_uses(tree, [add_bound_names(tree, set())], found, False)
    unique = []
    seen = set()
    for hit in found:
        if hit in seen:
            continue
        seen.add(hit)
        unique.append(hit)
    unique.sort()
    return unique


BAD_SOURCE = '\n'.join((
    'import urllib as _url',
    'from _version import version',
    '',
    '',
    'def _decode(body=_default):',
    '    return _helper(body._attr)',
    '',
    '',
    'class _Thing(object):',
    '    def _method(self):',
    '        self._slot = _decode()',
    '',
    '',
    'class Ok(object):',
    '    def __init__(self):',
    '        self.__repr__()',
    '',
    '',
    'def _():',
    '    return None',
))

BAD_NAMES = frozenset([
    '_url', '_decode', '_default', '_helper', '_attr',
    '_Thing', '_method', '_slot',
])

ALLOWED_SOURCE = '\n'.join((
    'class Ok(object):',
    '    def __init__(self):',
    '        self.__str__()',
    '        self.__repr__()',
    '        self.__call__()',
    '',
    '',
    'def _():',
    '    return _',
))

BUILTIN_SOURCE = '\n'.join((
    'import json',
    '',
    '',
    'def detect():',
    '    try:',
    '        probe = bytes',
    '    except NameError:',
    '        probe = str',
    '    try:',
    '        other = bytes',
    '    except:',
    '        other = str',
    '    return probe, other',
    '',
    '',
    'def shadow(input):',
    '    if input:',
    '        return input',
    '    return None',
    '',
    '',
    'def leaky():',
    '    value = getattr',
    '    return open(value)',
    '',
    '',
    'total = sum([1, 2, 3])',
))

BUILTIN_BAD_NAMES = frozenset(['getattr', 'open', 'sum'])


class SandboxComplianceTest(unittest.TestCase):

    def test_code_dir_is_present(self):
        self.assertTrue(
            os.path.isdir(CODE_DIR),
            'shipped code directory not found: %s' % CODE_DIR)
        self.assertIn('api_client.py', shipped_code_files())

    def test_checker_flags_banned_names(self):
        hits = banned_names(BAD_SOURCE)
        self.assertEqual(BAD_NAMES, frozenset(name for _, name in hits))
        # Module names are not checked by RestrictedPython.
        self.assertNotIn('_version', [name for _, name in hits])

    def test_checker_allows_underscore_and_dunders(self):
        self.assertEqual([], banned_names(ALLOWED_SOURCE))

    def test_shipped_code_has_no_banned_names(self):
        sources = list(shipped_sources())
        self.assertTrue(sources, 'no shipped modules found in %s' % CODE_DIR)
        problems = []
        for display, source in sources:
            for lineno, banned in banned_names(source):
                problems.append('%s:%d: %s' % (display, lineno, banned))
        if problems:
            self.fail(
                'identifiers the Plex plugin sandbox rejects '
                '(RestrictedPython checkName/checkAttrName) -- rename them:\n'
                + '\n'.join(problems))

    def test_builtin_checker_flags_unavailable_names(self):
        hits = unavailable_builtin_uses(BUILTIN_SOURCE)
        self.assertEqual(
            BUILTIN_BAD_NAMES, frozenset(name for _, name in hits))

    def test_builtin_checker_exempts_probe_and_shadowing(self):
        names = [name for _, name in unavailable_builtin_uses(BUILTIN_SOURCE)]
        # ``try: X = bytes / except NameError: ...`` is the sanctioned probe.
        self.assertNotIn('bytes', names)
        # ``input`` is a parameter of ``shadow``, not the builtin.
        self.assertNotIn('input', names)

    def test_shipped_code_uses_only_available_builtins(self):
        sources = list(shipped_sources())
        self.assertTrue(sources, 'no shipped modules found in %s' % CODE_DIR)
        problems = []
        for display, source in sources:
            for lineno, name in unavailable_builtin_uses(source):
                problems.append('%s:%d: %s' % (display, lineno, name))
        if problems:
            self.fail(
                'builtins the Plex plugin sandbox does NOT provide '
                '(StandardPolicy: RestrictedPython safe_builtins + the env '
                'dict in Framework/code/sandbox.py) -- rewrite them:\n'
                + '\n'.join(problems))


if __name__ == '__main__':
    unittest.main()
