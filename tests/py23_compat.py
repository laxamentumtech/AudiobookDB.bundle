# -*- coding: utf-8 -*-
"""
Python 2 -> Python 3 compatibility shims for the legacy bundle code.

The bundle code (``Contents/Code/*.py``) is Python 2.7 and stays that way for
the life of the project. Local and CI runs on Python 3 need the following
patches, applied here BEFORE any bundle module is imported:

- ``urllib.quote`` / ``urllib.unquote`` from ``urllib.parse``
  (``search_tools.py``); ``unquote`` is wrapped to return bytes because the
  legacy code calls ``urllib.unquote(x).decode('utf8')``.
- ``builtins.reduce`` (``search_tools.py`` ``ScoreTool.sum_scores``).
- ``os.tmpfile`` -> ``tempfile.TemporaryFile`` (``update_tools.py``
  ``get_square_image``).
- ``json.loads`` wrapped to drop the py2-only ``encoding=`` keyword while
  decoding objects into a ``dict`` subclass defining ``viewkeys()``
  (``search_tools.py`` required-keys filter).

Under Python 2.7 this module is a no-op.
"""

import sys

if sys.version_info[0] >= 3:
    import builtins
    import functools
    import json as _json
    import os as _os
    import tempfile as _tempfile
    import urllib as _urllib
    import urllib.parse as _urlparse

    _urllib.quote = _urlparse.quote

    def _unquote_bytes(s):
        # Legacy code: urllib.unquote(x).decode('utf8')
        return _urlparse.unquote(s).encode('utf-8')

    _urllib.unquote = _unquote_bytes

    builtins.reduce = functools.reduce
    _os.tmpfile = _tempfile.TemporaryFile

    class _LegacyDict(dict):
        """dict with a py2-style ``viewkeys()`` for legacy code."""

        def viewkeys(self):
            return self.keys()

    _raw_loads = _json.loads

    def _loads(s, *args, **kwargs):
        kwargs.pop('encoding', None)
        kwargs.setdefault('object_pairs_hook', _LegacyDict)
        return _raw_loads(s, *args, **kwargs)

    _json.loads = _loads
