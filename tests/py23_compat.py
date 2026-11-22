# -*- coding: utf-8 -*-
"""
Python 2 -> Python 3 compatibility shims for the legacy bundle code.

The bundle code (``Contents/Code/*.py``) is Python 2.7 and stays that way for
the life of the project. Local and CI runs on Python 3 need the following
patches, applied here BEFORE any bundle module is imported:

``api_client.py`` uses the Python 2-only ``encoding`` argument to
``json.loads``. Drop it under Python 3 before loading the bundle.

Under Python 2.7 this module is a no-op.
"""

import sys

if sys.version_info[0] >= 3:
    import json as _json

    _raw_loads = _json.loads

    def _loads(s, *args, **kwargs):
        kwargs.pop('encoding', None)
        return _raw_loads(s, *args, **kwargs)

    _json.loads = _loads

    from urllib.error import HTTPError  # noqa: F401
else:
    from urllib2 import HTTPError  # noqa: F401
