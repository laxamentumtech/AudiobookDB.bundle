# -*- coding: utf-8 -*-
"""
Python 2 -> Python 3 compatibility shims for the legacy bundle code.

The bundle code (``Contents/Code/*.py``) is Python 2.7 and stays that way for
the life of the project. Local and CI runs on Python 3 need the following
patches, applied here BEFORE any bundle module is imported:

- ``builtins.reduce`` (``search_tools.py`` ``ScoreTool.sum_scores``).
- ``json.loads`` wrapped to drop the py2-only ``encoding=`` keyword while
  decoding objects into a ``dict`` subclass defining ``viewkeys()``
  (``api_client.py`` passes ``encoding='utf-8'``; ``search_tools.py`` uses
  the required-keys filter).

Under Python 2.7 this module is a no-op.
"""

import sys

if sys.version_info[0] >= 3:
    import builtins
    import functools
    import json as _json

    builtins.reduce = functools.reduce

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
