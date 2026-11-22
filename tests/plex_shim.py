# -*- coding: utf-8 -*-
"""
Minimal Plex Framework 2 shim for testing the legacy bundle code.

Fakes the exact framework surface the bundle code touches (verified by grep):
``Agent.Artist`` / ``Agent.Album``, ``MetadataSearchResult``, ``HTTP`` (with a
settable test transport + cache), ``Prefs``, ``Proxy.Media``,
``Locale.Language.English``, ``String.StripDiacritics``,
``Util.LevenshteinDistance``, ``Datetime.ParseDate``, ``Log`` (plus
``Log.Debug`` / ``Log.Error``), ``CACHE_1WEEK`` and ``SSLError``.

Py2/3 compatible, stdlib only. ``tests/`` is never shipped with the bundle.
"""

import os
import sys
import unittest  # noqa: F401  (re-exported for test modules)

# Apply py2 -> py3 patches to the stdlib BEFORE bundle modules import it.
import py23_compat  # noqa: F401  (must stay first)
from py23_compat import HTTPError  # noqa: E402

# Make ``from search_tools import ...`` etc. resolve to the bundle code.
_CODE_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'Contents', 'Code')
if _CODE_DIR not in sys.path:
    sys.path.insert(0, _CODE_DIR)

import search_tools as _search_tools  # noqa: E402


class English(object):
    """Identity token for Locale.Language.English (equal by ==)."""

    def __repr__(self):
        return 'English'

    def __str__(self):
        return 'English'


Locale = type('Locale', (), {})
Language = type('Language', (), {})
Locale.Language = Language
Language.English = English()


class AgentBase(object):
    """Base for Agent.Artist / Agent.Album; records class attrs."""
    name = 'ShimAgent'
    languages = []
    primary_provider = False
    accepts_from = []


Agent = type('Agent', (), {})
Agent.Artist = type('Artist', (AgentBase,), {})
Agent.Album = type('Album', (AgentBase,), {})


class MetadataSearchResult(object):
    def __init__(self, id, lang, name, score, year=None, thumb=None):
        self.id = id
        self.lang = lang
        self.name = name
        self.score = score
        self.year = year
        self.thumb = thumb


class _Results(object):
    """Stand-in for the ``results`` object (records Appends)."""

    def __init__(self):
        self.appended = []

    def Append(self, r):
        self.appended.append(r)

    def Clear(self):
        self.appended = []


class _HTTPHeaderProxy(object):
    """Mirror of the framework's HTTPHeaderProxy: lower-cased keys,
    indexing and iteration only, no .get()."""

    def __init__(self, headers):
        self._headers = dict((str(k).lower(), v)
                             for k, v in (headers or {}).items())

    def __getitem__(self, name):
        return self._headers[str(name).lower()]

    def __iter__(self):
        return self._headers.__iter__()

    def __repr__(self):
        return repr(self._headers)


class _HTTPRequest(object):
    """Transport double.

    ``lazy=False`` (default): the test-contract shape with a plain
    ``.status`` and dict ``.headers``.

    ``lazy=True``: mirrors Plex's real HTTPRequest — no ``.status``
    attribute, ``headers`` is an ``_HTTPHeaderProxy`` (a headers-only
    read issues a HEAD), and ``str()`` loads the body, raising
    ``HTTPError`` (with ``.code``) for non-2xx statuses.
    """

    def __init__(self, status=200, body=None, headers=None, lazy=False):
        self._status = status
        self._headers = headers or {}
        self._lazy = lazy
        self._url = None
        if isinstance(body, bytes):
            body = body.decode('utf-8')
        self._body = body
        self._proxy = _HTTPHeaderProxy(self._headers)
        if not lazy:
            self.status = status
            self.headers = self._headers

    @property
    def headers(self):
        # The real transport answers a headers-only read with a HEAD.
        return self._proxy

    @headers.setter
    def headers(self, value):
        self._headers = value

    def __str__(self):
        if self._lazy and self._status is not None \
                and not 200 <= self._status < 300:
            raise HTTPError(self._url or '', self._status,
                            'HTTP %s' % self._status, self._proxy, None)
        return self._body or ''


class _HTTPModule(object):
    """Fake ``HTTP`` module: a settable transport + a dict-based cache.

    ``transport(url, method='GET', headers=None, data=None)`` must return an
    ``_HTTPRequest``. Requests are Plex-style: GETs are cached by URL;
    ``str(response)`` yields the body (legacy contract); ``.status`` and
    ``.headers`` are available for api_client retries.
    """

    def __init__(self):
        self.transport = lambda url, method='GET', **kw: _HTTPRequest(200, '')
        self.Headers = {}
        self.CacheTime = 0
        self._cache = {}
        self.requests = []  # (url, method, headers, data) call log
        # Mirror of Plex's global cookie jar: Set-Cookie headers on a
        # response land here and are presented on later requests.
        self.cookies = {}

    def Request(self, url, method='GET', headers=None, data=None,
                timeout=None, sleep=None, lazy=None):
        self.requests.append((url, method, headers, data))
        cacheable = method == 'GET'
        if cacheable and url in self._cache:
            return self._cache[url]
        if lazy is not None:
            resp = self.transport(url, method=method, headers=headers,
                                  data=data, lazy=lazy)
        else:
            resp = self.transport(url, method=method, headers=headers,
                                  data=data)
        if not isinstance(resp, _HTTPRequest):
            resp = _HTTPRequest(200, resp)
        resp._url = url
        self._apply_set_cookies(resp)
        if cacheable:
            self._cache[url] = resp
        return resp

    def _apply_set_cookies(self, resp):
        """Apply the response's Set-Cookie values to the jar (the real
        transport does this while loading the body)."""
        raw = None
        headers = resp._headers
        if hasattr(headers, 'get'):
            raw = headers.get('set-cookie')
        else:
            for key in headers:
                if str(key).lower() == 'set-cookie':
                    raw = headers[key]
                    break
        if not raw:
            return
        for part in str(raw).replace(',', ';').split(';'):
            part = part.strip()
            if '=' in part:
                name, value = part.split('=', 1)
                self.cookies[name.strip()] = value.strip()

    def CookiesForURL(self, url=None):
        return [
            {'name': name, 'value': value, 'domain': '', 'path': '/'}
            for name, value in sorted(self.cookies.items())
        ]

    def ClearCache(self):
        self._cache = {}
        self.requests = []

    def Reset(self):
        self._cache = {}
        self.requests = []
        self.cookies = {}


class Prefs(dict):
    pass


class _Proxy(object):
    @staticmethod
    def Media(data, sort_order=None):
        return (data, sort_order)


class _String(object):
    @staticmethod
    def StripDiacritics(s):
        import unicodedata
        if s is None:
            return None
        if isinstance(s, bytes):
            s = s.decode('utf-8')
        normalized = unicodedata.normalize('NFD', s)
        stripped = normalized.encode('ascii', 'ignore').decode('ascii')
        if isinstance(s, bytes):
            return stripped.encode('utf-8')
        return stripped


class _Util(object):
    @staticmethod
    def LevenshteinDistance(s1, s2):
        # Plain DP implementation.
        s1 = s1.decode('utf-8') if isinstance(s1, bytes) else s1
        s2 = s2.decode('utf-8') if isinstance(s2, bytes) else s2
        if len(s1) < len(s2):
            s1, s2 = s2, s1
        previous_row = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(
                    min(insertions, deletions, substitutions))
            previous_row = current_row
        return previous_row[-1]


class _Datetime(object):
    @staticmethod
    def ParseDate(string):
        import datetime
        if string is None:
            return None
        if isinstance(string, datetime.datetime):
            return string
        if isinstance(string, datetime.date):
            return datetime.datetime(string.year, string.month, string.day)
        s = string
        if isinstance(s, bytes):
            s = s.decode('utf-8')
        s = s.strip()
        # ISO 8601; normalize trailing Z for py2.7 (fromisoformat is py3.7+).
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        if '+' in s[1:]:
            main, offset = s.rsplit('+', 1)
        elif '-' in s[10:]:
            main, offset = s.rsplit('-', 1)
            offset = '-' + offset
        else:
            main, offset = s, None
        # Strip fractional seconds from main (keep HH:MM:SS).
        main = main.split('.')[0]
        import re as _re
        m = _re.match(
            r'(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})', main)
        if m:
            return datetime.datetime(*[int(g) for g in m.groups()])
        m = _re.match(r'(\d{4})-(\d{2})-(\d{2})', main)
        if m:
            return datetime.datetime(*[int(g) for g in m.groups()])
        return None


class _Log(object):
    """Recordable Log: Log(msg, *args), Log.Debug, Log.Error."""

    def __init__(self):
        self.entries = []
        self.Debug = self._make('DEBUG')
        self.Error = self._make('ERROR')

    def _make(self, level):
        def _log(message, *args):
            self.entries.append((level, message, args))
        return _log

    def __call__(self, message, *args):
        self.entries.append(('INFO', message, args))

    def Clear(self):
        self.entries = []


class _SSLError(Exception):
    pass


CACHE_1WEEK = 7 * 24 * 60 * 60

# Install framework globals used (unqualified) by the bundle code.
HTTP = _HTTPModule()
Log = _Log()
Prefs = Prefs()
Proxy = _Proxy()
String = _String()
Util = _Util()
Datetime = _Datetime()
SSLError = _SSLError

FRAMEWORK_GLOBALS = (
    'Agent', 'MetadataSearchResult', 'HTTP', 'Log', 'Prefs', 'Proxy',
    'String', 'Util', 'Datetime', 'Locale', 'SSLError', 'CACHE_1WEEK',
)

if sys.version_info[0] >= 3:
    import builtins as _builtins
else:
    import __builtin__ as _builtins

for _name in FRAMEWORK_GLOBALS:
    setattr(_builtins, _name, globals()[_name])
