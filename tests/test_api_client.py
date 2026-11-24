# -*- coding: utf-8 -*-
"""
API client tests: URL construction, headers, JSON decoding, error
envelopes, 404 handling, 429 Retry-After within the 4-attempt budget, and
the ASIN/detail/ratings helpers against recorded fixtures. Search tests
cover the anonymous CSRF handshake (same-origin prime, double-submit
token, bounded retry on 403) and the keyed bypass path.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plex_shim  # noqa: F401  (framework globals; must stay first)
from plex_shim import _HTTPRequest

import api_client

# Zero the inter-attempt sleep so failure-path tests are fast.
api_client.DEFAULT_RETRY_AFTER = 0

BASE = 'https://api.audiobookdb.org/api'

FIXTURES = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'audiobookdb')


def load_fixture(name):
    with open(os.path.join(FIXTURES, name), 'rb') as f:
        return json.loads(f.read().decode('utf-8'))


def api_body(payload):
    """Serialize a fixture payload the way the legacy wire transport did."""
    return json.dumps(payload, ensure_ascii=True)


def install_transport(mapping, default='', lazy=False, jar_script=None):
    """Map URL -> (status, headers, body); records requests on HTTP.requests.

    The headers entry may be omitted for a bare (status, body) tuple.

    ``lazy=True`` switches the double to Plex's real HTTPRequest shape
    (no .status, headers-only reads issue a HEAD, str() raises
    HTTPError for non-2xx). ``jar_script`` (a list of tokens) makes
    ``HTTP.CookiesForURL`` return the next scripted token per call,
    mirroring a cookie jar that reissues the token.
    """
    lazy_default = lazy

    def transport(url, method='GET', headers=None, data=None, lazy=None):
        if url in mapping:
            spec = mapping[url]
        else:
            spec = (404, {}, default)
        if len(spec) == 2:
            status, body = spec
            resp_headers = {}
        else:
            status, resp_headers, body = spec
        if lazy is None:
            lazy = lazy_default
        return _HTTPRequest(status, body, resp_headers, lazy=lazy)
    HTTP.Reset()
    HTTP.Headers = {}
    HTTP.transport = transport
    if jar_script is not None:
        script = list(jar_script)
        state = {'i': 0}

        def scripted_jar(url=None):
            if state['i'] >= len(script):
                return []
            token = script[state['i']]
            state['i'] += 1
            if token is None:
                return []
            return [{'name': 'csrf_token', 'value': token,
                     'domain': '', 'path': '/'}]
        HTTP.CookiesForURL = scripted_jar
    elif 'CookiesForURL' in HTTP.__dict__:
        # A scripted jar from an earlier test shadows the class method;
        # drop the instance attribute so the default jar is restored.
        del HTTP.CookiesForURL
    Prefs['logging_level'] = 'ERROR'
    return transport


class TestMakeRequest(unittest.TestCase):
    def test_success(self):
        install_transport({BASE + '/x': (200, '{"a": 1}')})
        self.assertEqual(api_client.make_request(BASE + '/x'), {'a': 1})

    def test_404_returns_none(self):
        install_transport({})
        self.assertIsNone(api_client.make_request(BASE + '/missing'))

    def test_non_2xx_returns_none(self):
        install_transport({BASE + '/x': (500, 'server exploded')})
        self.assertIsNone(api_client.make_request(BASE + '/x'))

    def test_malformed_json_returns_none(self):
        install_transport({BASE + '/x': (200, 'not json')})
        self.assertIsNone(api_client.make_request(BASE + '/x'))

    def test_get_sends_only_configured_api_key(self):
        old = Prefs.get('api_key', '')
        try:
            for key, expected in (('test-key', {'X-API-Key': 'test-key'}), ('', {})):
                Prefs['api_key'] = key
                install_transport({BASE + '/x': (200, '{"a": 1}')})
                self.assertEqual(api_client.make_request(BASE + '/x'), {'a': 1})
                self.assertEqual(HTTP.requests[0][2], expected)
        finally:
            Prefs['api_key'] = old

    def test_error_envelope_returns_none(self):
        install_transport({BASE + '/x': (200, '{"errors": [{"status": "404"}]}')})
        self.assertIsNone(api_client.make_request(BASE + '/x'))

    def test_exhausted_attempts_returns_none(self):
        install_transport({})
        self.assertIsNone(api_client.make_request(BASE + '/missing'))
        # Exactly MAX_ATTEMPTS requests were made.
        self.assertEqual(len(HTTP.requests), api_client.MAX_ATTEMPTS)


class TestFetchBytes(unittest.TestCase):
    def test_returns_bytes(self):
        install_transport({'https://cdn.audiobookdb.org/img':
                           (200, 'JPEG-DATA')})
        self.assertEqual(
            api_client.fetch_bytes('https://cdn.audiobookdb.org/img'),
            b'JPEG-DATA')

    def test_raises_after_exhaustion(self):
        install_transport({})
        self.assertRaises(
            IOError, api_client.fetch_bytes,
            'https://cdn.audiobookdb.org/img')

    def test_redirect_to_trusted_host_succeeds(self):
        install_transport({
            'https://cdn.audiobookdb.org/img':
                (302, {'Location': 'https://cdn.audiobookdb.org/img/real'}, ''),
            'https://cdn.audiobookdb.org/img/real':
                (200, 'JPEG-DATA'),
        })
        self.assertEqual(
            api_client.fetch_bytes('https://cdn.audiobookdb.org/img'),
            b'JPEG-DATA')
        # Both the original and the followed hop were requested.
        self.assertEqual(
            [req[0] for req in HTTP.requests],
            ['https://cdn.audiobookdb.org/img',
             'https://cdn.audiobookdb.org/img/real'])

    def test_redirect_relative_within_host_succeeds(self):
        install_transport({
            'https://cdn.audiobookdb.org/img':
                (302, {'Location': '/img/real'}, ''),
            'https://cdn.audiobookdb.org/img/real':
                (200, 'JPEG-DATA'),
        })
        self.assertEqual(
            api_client.fetch_bytes('https://cdn.audiobookdb.org/img'),
            b'JPEG-DATA')

    def test_redirect_to_off_allowlist_host_blocked(self):
        install_transport({
            'https://cdn.audiobookdb.org/img':
                (302, {'Location': 'https://evil.example.com/img'}, ''),
            'https://evil.example.com/img':
                (200, 'EVIL'),
        })
        self.assertRaises(
            IOError, api_client.fetch_bytes, 'https://cdn.audiobookdb.org/img')
        # The off-allowlist target must never be requested.
        self.assertEqual(
            [req[0] for req in HTTP.requests],
            ['https://cdn.audiobookdb.org/img'])

    def test_redirect_to_http_scheme_blocked(self):
        install_transport({
            'https://cdn.audiobookdb.org/img':
                (302, {'Location': 'http://cdn.audiobookdb.org/img/plain'}, ''),
        })
        self.assertRaises(
            IOError, api_client.fetch_bytes, 'https://cdn.audiobookdb.org/img')

    def test_redirect_without_location_raises(self):
        # A 3xx hop with no usable Location header cannot be followed:
        # the hop-by-hop check raises IOError instead of looping.
        install_transport({
            'https://cdn.audiobookdb.org/img': (302, {}, ''),
        }, lazy=True)
        self.assertRaises(
            IOError, api_client.fetch_bytes, 'https://cdn.audiobookdb.org/img')
        # The hop was requested once and nothing was followed.
        self.assertEqual(
            [req[0] for req in HTTP.requests],
            ['https://cdn.audiobookdb.org/img'])

    def test_redirect_loop_exhausts_hops(self):
        # Two trusted hops that bounce back to the first URL: the hop limit
        # (MAX_IMAGE_REDIRECTS) stops the chain before it loops forever.
        install_transport({
            'https://cdn.audiobookdb.org/a':
                (302, {'Location': 'https://cdn.audiobookdb.org/b'}, ''),
            'https://cdn.audiobookdb.org/b':
                (302, {'Location': 'https://cdn.audiobookdb.org/a'}, ''),
        })
        self.assertRaises(
            IOError, api_client.fetch_bytes, 'https://cdn.audiobookdb.org/a')
        # 1 (start) + MAX_IMAGE_REDIRECTS hops were requested, no more.
        self.assertEqual(
            len(HTTP.requests), 1 + api_client.MAX_IMAGE_REDIRECTS)

    def test_non_https_url_rejected(self):
        install_transport({'http://cdn.audiobookdb.org/img':
                           (200, 'JPEG-DATA')})
        self.assertRaises(
            IOError, api_client.fetch_bytes,
            'http://cdn.audiobookdb.org/img')
        self.assertEqual(HTTP.requests, [])  # no request made

    def test_untrusted_host_rejected(self):
        install_transport({'https://example.com/img':
                           (200, 'JPEG-DATA')})
        self.assertRaises(
            IOError, api_client.fetch_bytes, 'https://example.com/img')
        self.assertEqual(HTTP.requests, [])  # no request made


class TestPostJson(unittest.TestCase):
    def test_headers_and_body(self):
        install_transport({BASE + '/search': (200, '[{"id": "x"}]')})
        Prefs['api_key'] = 'test-key'
        out = api_client.post_json('/search', {'q': 'martian', 'type': 'books'})
        self.assertEqual(out, [{'id': 'x'}])
        url, method, headers, data = HTTP.requests[0]
        self.assertEqual(url, BASE + '/search')
        self.assertEqual(method, 'POST')
        self.assertEqual(headers['Content-Type'], 'application/json')
        self.assertEqual(headers['User-Agent'], api_client.USER_AGENT)
        self.assertEqual(headers['X-API-Key'], 'test-key')
        self.assertEqual(
            json.loads(
                data.decode('utf-8') if isinstance(data, bytes) else data),
            {'q': 'martian', 'type': 'books'}
        )
        Prefs['api_key'] = ''

    def test_failure_returns_none(self):
        install_transport({})
        self.assertIsNone(api_client.post_json('/search', {'q': 'x',
                                                           'type': 'books'}))


class TestResolveAsinBook(unittest.TestCase):
    def test_hit(self):
        book = load_fixture('book_external_resolve_B00B5HZGUG.json')
        install_transport({
            BASE + '/audiobooks/external/audible/B00B5HZGUG':
                (200, api_body(book)),
        })
        resolved, matched = api_client.resolve_asin_book('B00B5HZGUG')
        self.assertEqual(resolved['id'], 'WQQDcMBQ3qUT')
        self.assertEqual(matched, 'dPL9fC7YnK8X')

    def test_404(self):
        err = load_fixture('error_404.json')
        install_transport({
            BASE + '/audiobooks/external/audible/BBBBBBBBBB':
                (404, api_body(err)),
        })
        self.assertEqual(api_client.resolve_asin_book('BBBBBBBBBB'),
                         (None, None))


class TestResolveAsinPerson(unittest.TestCase):
    def test_single_hit(self):
        hits = load_fixture('person_external_resolve_B00G0WYW92.json')
        install_transport({
            BASE + '/people?external=Audible%3AB00G0WYW92&take=2':
                (200, api_body(hits)),
        })
        out = api_client.resolve_asin_person('B00G0WYW92')
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['id'], 'ypMPwXzWXaiX')

    def test_failure_empty(self):
        install_transport({})
        self.assertEqual(api_client.resolve_asin_person('B00G0WYW92'), [])


class TestDetailAndGetters(unittest.TestCase):
    def test_get_book(self):
        book = load_fixture('book_detail_WQQDcMBQ3qUT.json')
        install_transport({BASE + '/books/WQQDcMBQ3qUT': (200, api_body(book))})
        self.assertEqual(api_client.get_book('WQQDcMBQ3qUT')['id'],
                         'WQQDcMBQ3qUT')

    def test_get_book_include(self):
        book = load_fixture('book_detail_WQQDcMBQ3qUT_includesExternal.json')
        url = BASE + '/books/WQQDcMBQ3qUT?include=releasesExternal'
        install_transport({url: (200, api_body(book))})
        out = api_client.get_book('WQQDcMBQ3qUT', include='releasesExternal')
        self.assertTrue(out['releases'][0].get('external'))
        self.assertEqual(HTTP.requests[0][0], url)

    def test_get_release(self):
        rel = load_fixture('release_detail_dPL9fC7YnK8X.json')
        install_transport({BASE + '/releases/dPL9fC7YnK8X':
                           (200, api_body(rel))})
        out = api_client.get_release('dPL9fC7YnK8X')
        self.assertEqual(out['book']['id'], 'WQQDcMBQ3qUT')
        self.assertEqual(out['external'][0]['itemId'], 'B00B5HZGUG')

    def test_get_person(self):
        person = load_fixture('person_detail_ypMPwXzWXaiX.json')
        install_transport({BASE + '/people/ypMPwXzWXaiX':
                           (200, api_body(person))})
        self.assertEqual(api_client.get_person('ypMPwXzWXaiX')['id'],
                         'ypMPwXzWXaiX')

    def test_get_ratings(self):
        ratings = load_fixture('ratings_book_WQQDcMBQ3qUT.json')
        install_transport({
            BASE + '/items/book/WQQDcMBQ3qUT/ratings':
                (200, api_body(ratings)),
        })
        chips = api_client.get_ratings('WQQDcMBQ3qUT')
        self.assertEqual(chips[0]['source'], 'openlibrary')  # not audible
        self.assertEqual(chips[1]['source'], 'audible')

    def test_search_fixtures_with_api_key(self):
        old = Prefs.get('api_key', '')
        Prefs['api_key'] = 'test-key'
        try:
            for kind, query, fixture, expected in (
                ('books', 'The Martian', 'search_books_martian.json', 'WQQDcMBQ3qUT'),
                ('people', 'Andy Weir', 'search_people_andy_weir.json', 'ypMPwXzWXaiX'),
            ):
                hits = load_fixture(fixture)
                install_transport({BASE + '/search': (200, api_body(hits))})
                out = api_client.search(query, kind)
                self.assertIn(expected, [hit['id'] for hit in out])
        finally:
            Prefs['api_key'] = old

    def test_search_short_q_no_filters_returns_empty(self):
        install_transport({BASE + '/search': (200, '[]')})
        self.assertEqual(api_client.search('ab', 'books'), [])
        self.assertEqual(HTTP.requests, [])  # no request made


class TestRetryAfter(unittest.TestCase):
    def test_429_positive_retry_after_waits_then_succeeds(self):
        # An ordinary delay-seconds value is slept as-is (no clamping) and
        # the next attempt succeeds.
        state = {'n': 0}
        Prefs['logging_level'] = 'ERROR'
        sleeps = []
        real_sleep = api_client.sleep

        def transport(url, method='GET', headers=None, data=None):
            state['n'] += 1
            if state['n'] == 1:
                return _HTTPRequest(429, '', {'Retry-After': '7'})
            return _HTTPRequest(200, '{"ok": true}')
        HTTP.Reset()
        HTTP.transport = transport
        api_client.sleep = sleeps.append
        try:
            self.assertEqual(api_client.make_request(BASE + '/x'),
                             {'ok': True})
        finally:
            api_client.sleep = real_sleep
        self.assertEqual(state['n'], 2)
        # The 7-second delay, verbatim: no default, no clamp.
        self.assertEqual(sleeps, [7])

    def test_429_then_success(self):
        state = {'n': 0}
        Prefs['logging_level'] = 'ERROR'

        def transport(url, method='GET', headers=None, data=None):
            state['n'] += 1
            if state['n'] == 1:
                return _HTTPRequest(429, '', {'retry-after': '0'})
            return _HTTPRequest(200, '{"ok": true}')
        HTTP.Reset()
        HTTP.transport = transport
        self.assertEqual(api_client.make_request(BASE + '/x'), {'ok': True})
        self.assertEqual(state['n'], 2)

    def test_429_exhausted_returns_none(self):
        Prefs['logging_level'] = 'ERROR'

        def transport(url, method='GET', headers=None, data=None):
            return _HTTPRequest(429, '', {'retry-after': '0'})
        HTTP.Reset()
        HTTP.transport = transport
        self.assertIsNone(api_client.make_request(BASE + '/x'))
        self.assertEqual(len(HTTP.requests), api_client.MAX_ATTEMPTS)

    def test_429_oversized_retry_after_clamped(self):
        Prefs['logging_level'] = 'ERROR'
        sleeps = []
        real_sleep = api_client.sleep

        def transport(url, method='GET', headers=None, data=None):
            return _HTTPRequest(429, '', {'retry-after': '99999'})
        HTTP.Reset()
        HTTP.transport = transport
        api_client.sleep = sleeps.append
        try:
            self.assertIsNone(api_client.make_request(BASE + '/x'))
        finally:
            api_client.sleep = real_sleep
        # Every 429 attempt except the final one sleeps the clamped bound,
        # never 99999; there is no attempt after the last, so no sleep.
        self.assertEqual(sleeps, [api_client.MAX_RETRY_AFTER] *
                         (api_client.MAX_ATTEMPTS - 1))

    def test_429_negative_retry_after_falls_back(self):
        Prefs['logging_level'] = 'ERROR'
        sleeps = []
        real_sleep = api_client.sleep

        def transport(url, method='GET', headers=None, data=None):
            return _HTTPRequest(429, '', {'retry-after': '-5'})
        HTTP.Reset()
        HTTP.transport = transport
        api_client.sleep = sleeps.append
        try:
            self.assertIsNone(api_client.make_request(BASE + '/x'))
        finally:
            api_client.sleep = real_sleep
        # A negative value must not raise; it falls back to the default.
        # No sleep after the final attempt.
        self.assertEqual(sleeps, [0] * (api_client.MAX_ATTEMPTS - 1))

    def test_future_http_date_waits_until_requested_time(self):
        # A future HTTP-date must yield a wait of ~now until that time,
        # not the 1s default the old time() - epoch computation produced.
        from email.utils import formatdate
        requested = int(api_client.time_mod.time()) + 45
        http_date = formatdate(timeval=requested, usegmt=True)
        delay = api_client.retry_after_seconds(
            _HTTPRequest(429, '', {'Retry-After': http_date}))
        # The clock may tick between request and check; allow +-1s.
        self.assertGreaterEqual(delay, 43)
        self.assertLessEqual(delay, 45)

    def test_past_http_date_falls_back(self):
        # An HTTP-date already in the past yields a negative interval and
        # falls back to the default.
        from email.utils import formatdate
        http_date = formatdate(
            timeval=int(api_client.time_mod.time()) - 3600, usegmt=True)
        self.assertEqual(
            api_client.retry_after_seconds(
                _HTTPRequest(429, '', {'Retry-After': http_date})),
            api_client.DEFAULT_RETRY_AFTER)


class TestSearchHandshake(unittest.TestCase):
    """Anonymous CSRF handshake and the keyed bypass path for search()."""

    def setUp(self):
        self._key = Prefs.get('api_key', '')
        Prefs['api_key'] = ''
        api_client.csrf_invalidate()
        api_client.csrf_prime_count = 0

    def tearDown(self):
        Prefs['api_key'] = self._key
        api_client.csrf_invalidate()

    def prime_url(self, nonce=1):
        # csrf_prime appends the one-off cache-bust params.
        return api_client.CSRF_PRIME_URL + '?csrf=1&nonce=%d' % nonce

    def _assert_double_submit(self):
        url, method, headers, data = HTTP.requests[1]
        self.assertEqual(url, BASE + '/search')
        self.assertEqual(method, 'POST')
        self.assertEqual(headers['X-CSRF-Token'], 'tok-abc')
        self.assertEqual(headers['Cookie'], 'csrf_token=tok-abc')
        self.assertNotIn('X-API-Key', headers)

    def test_anonymous_handshake_sends_double_submit(self):
        install_transport({
            self.prime_url():
                (200, {'Set-Cookie': 'csrf_token=tok-abc; Path=/'},
                      '{"books": 0}'),
            BASE + '/search': (200, '[]'),
        })
        self.assertEqual(api_client.search('martian', 'books'), [])
        self.assertEqual(len(HTTP.requests), 2)
        prime_url, prime_method = HTTP.requests[0][0], HTTP.requests[0][1]
        # Same-origin prime on the trusted API host, a GET.
        self.assertEqual(prime_method, 'GET')
        self.assertTrue(prime_url.startswith(BASE))
        self._assert_double_submit()

    def test_anonymous_keyed_bypass_skips_prime(self):
        Prefs['api_key'] = 'test-key'
        install_transport({BASE + '/search': (200, '[]')})
        self.assertEqual(api_client.search('martian', 'books'), [])
        self.assertEqual(len(HTTP.requests), 1)
        url, method, headers, data = HTTP.requests[0]
        self.assertEqual(method, 'POST')
        self.assertEqual(headers['X-API-Key'], 'test-key')
        self.assertNotIn('X-CSRF-Token', headers)
        self.assertNotIn('Cookie', headers)

    def test_token_cached_across_calls(self):
        install_transport({
            self.prime_url():
                (200, {'Set-Cookie': 'csrf_token=tok-abc; Path=/'},
                      '{"books": 0}'),
            BASE + '/search': (200, '[]'),
        })
        api_client.search('martian', 'books')
        api_client.search('weir', 'people')
        primes = [r for r in HTTP.requests
                  if r[1] == 'GET' and r[0].startswith(
                      api_client.CSRF_PRIME_URL)]
        # One prime for both searches; the token is cached per process.
        self.assertEqual(len(primes), 1)

    def test_stale_token_reprimes_with_cache_bust(self):
        # The transport serves GETs from a URL-keyed cache; the re-prime
        # must bust it with a fresh nonce, not re-read the stale cookie.
        # The re-prime carries the jar-held cookie, so upstream sets no
        # fresh Set-Cookie — the new token comes from the cookie jar.
        calls = {'prime': 0}

        def transport(url, method='GET', headers=None, data=None):
            if method == 'POST' or url == BASE + '/search':
                if calls['prime'] == 1:
                    return _HTTPRequest(
                        403, '{"error": "CSRF token validation failed"}')
                return _HTTPRequest(200, '[]')
            calls['prime'] += 1
            if calls['prime'] == 1:
                return _HTTPRequest(
                    200, '{"books": 0}',
                    {'Set-Cookie': 'csrf_token=tok1; Path=/'})
            return _HTTPRequest(200, '{"books": 0}')

        # The first prime reads tok1 from the Set-Cookie header (jar
        # not consulted). The re-prime carries the jar-held cookie, so
        # upstream sets no fresh header; the jar yields the reissued
        # token on its first (and only) consultation.
        install_transport({}, jar_script=['tok2'])
        HTTP.transport = transport
        self.assertEqual(api_client.search('martian', 'books'), [])
        # Prime, rejected POST, re-prime, accepted POST.
        self.assertEqual([r[1] for r in HTTP.requests],
                         ['GET', 'POST', 'GET', 'POST'])
        self.assertEqual(HTTP.requests[0][0], self.prime_url(1))
        self.assertNotEqual(HTTP.requests[2][0], self.prime_url(1))
        self.assertEqual(HTTP.requests[2][0], self.prime_url(2))
        self.assertEqual(HTTP.requests[3][2]['X-CSRF-Token'], 'tok2')
        self.assertEqual(HTTP.requests[3][2]['Cookie'], 'csrf_token=tok2')

    def test_403_twice_returns_none(self):
        install_transport({
            self.prime_url(1):
                (200, {'Set-Cookie': 'csrf_token=tok-a; Path=/'},
                      '{"books": 0}'),
            self.prime_url(2):
                (200, {'Set-Cookie': 'csrf_token=tok-b; Path=/'},
                      '{"books": 0}'),
            BASE + '/search':
                (403, '{"error": "CSRF token validation failed"}'),
        })
        self.assertIsNone(api_client.search('martian', 'books'))
        # The POST is made at most twice (one retry) — no loop.
        posts = [r for r in HTTP.requests if r[1] == 'POST']
        self.assertEqual(len(posts), 2)

    def test_prime_without_cookie_returns_none(self):
        install_transport({self.prime_url(): (200, {}, '{"books": 0}')})
        self.assertIsNone(api_client.search('martian', 'books'))
        self.assertEqual(len(HTTP.requests), 1)  # the prime, then stopped

    def test_lazy_double_submit_handshake(self):
        # Real-transport shape: no .status, HEAD-only headers, str()
        # loads the body. The prime must read the body (a GET) and the
        # cookie must be parsed from the proxy-style headers.
        install_transport({
            self.prime_url():
                (200, {'Set-Cookie': 'csrf_token=tok-lazy; Path=/'},
                      '{"books": 0}'),
            BASE + '/search': (200, '[]'),
        }, lazy=True)
        self.assertEqual(api_client.search('martian', 'books'), [])
        self.assertEqual(len(HTTP.requests), 2)
        self.assertEqual(HTTP.requests[0][1], 'GET')
        self.assertEqual(
            HTTP.requests[1][2]['X-CSRF-Token'], 'tok-lazy')
        self.assertEqual(
            HTTP.requests[1][2]['Cookie'], 'csrf_token=tok-lazy')

    def test_lazy_non_2xx_surfaces_as_none(self):
        # A rate-limited anonymous POST raises HTTPError on the lazy
        # body load; search() must return None, not propagate it.
        install_transport({
            self.prime_url():
                (200, {'Set-Cookie': 'csrf_token=tok-lazy; Path=/'},
                      '{"books": 0}'),
            BASE + '/search': (429, '{"error": "rate limited"}'),
        }, lazy=True)
        self.assertIsNone(api_client.search('martian', 'books'))

    def test_prime_transport_failure_returns_none(self):
        def transport(url, method='GET', headers=None, data=None):
            raise IOError('boom')
        Prefs['api_key'] = ''
        HTTP.Reset()
        HTTP.Headers = {}
        HTTP.transport = transport
        self.assertIsNone(api_client.search('martian', 'books'))
        self.assertEqual([r[1] for r in HTTP.requests], ['GET'])

    def test_anonymous_failure_returns_none(self):
        install_transport({
            self.prime_url():
                (200, {'Set-Cookie': 'csrf_token=tok-abc; Path=/'},
                      '{"books": 0}'),
        })  # /search falls through to the 404 default
        self.assertIsNone(api_client.search('martian', 'books'))

    def test_anonymous_malformed_body_returns_none(self):
        install_transport({
            self.prime_url():
                (200, {'Set-Cookie': 'csrf_token=tok-abc; Path=/'},
                      '{"books": 0}'),
            BASE + '/search': (200, 'not json'),
        })
        self.assertIsNone(api_client.search('martian', 'books'))

    def test_include_fields_list_in_body(self):
        Prefs['api_key'] = 'test-key'
        install_transport({BASE + '/search': (200, '[]')})
        api_client.search(
            'martian', 'books', None, ['title', 'people.person.name'])
        payload = json.loads(HTTP.requests[0][3])
        self.assertEqual(payload['includeFields'],
                         ['title', 'people.person.name'])

    def test_include_fields_string_split(self):
        Prefs['api_key'] = 'test-key'
        install_transport({BASE + '/search': (200, '[]')})
        api_client.search('martian', 'books', None,
                          'title, subtitle ,tags')
        payload = json.loads(HTTP.requests[0][3])
        self.assertEqual(payload['includeFields'],
                         ['title', 'subtitle', 'tags'])

    def test_no_include_fields_omitted(self):
        Prefs['api_key'] = 'test-key'
        install_transport({BASE + '/search': (200, '[]')})
        api_client.search('martian', 'books')
        payload = json.loads(HTTP.requests[0][3])
        self.assertNotIn('includeFields', payload)


class TestLazyStatuslessSuccess(unittest.TestCase):
    """A lazy 2xx (no .status, body loads cleanly) is a success, not 599."""

    def setUp(self):
        self._key = Prefs.get('api_key', '')
        Prefs['api_key'] = ''
        api_client.csrf_invalidate()

    def tearDown(self):
        Prefs['api_key'] = self._key
        api_client.csrf_invalidate()

    def test_lazy_detail_get_succeeds(self):
        install_transport(
            {BASE + '/books/WQQDcMBQ3qUT': (200, '{"id": "WQQDcMBQ3qUT"}')},
            lazy=True)
        self.assertEqual(api_client.make_request(BASE + '/books/WQQDcMBQ3qUT'),
                         {'id': 'WQQDcMBQ3qUT'})
        # One attempt: a lazy 2xx must not burn the retry budget.
        self.assertEqual(len(HTTP.requests), 1)

    def test_lazy_keyed_search_post_succeeds(self):
        Prefs['api_key'] = 'test-key'
        install_transport({BASE + '/search': (200, '[{"id": "x"}]')},
                          lazy=True)
        self.assertEqual(
            api_client.post_json('/search', {'q': 'martian', 'type': 'books'}),
            [{'id': 'x'}])
        self.assertEqual(len(HTTP.requests), 1)

    def test_lazy_fetch_bytes_succeeds(self):
        install_transport(
            {'https://cdn.audiobookdb.org/img': (200, 'JPEG-DATA')},
            lazy=True)
        self.assertEqual(
            api_client.fetch_bytes('https://cdn.audiobookdb.org/img'),
            b'JPEG-DATA')
        self.assertEqual(len(HTTP.requests), 1)


class TestLazyNon2xxHeaders(unittest.TestCase):
    """A lazy non-2xx (429, 3xx) must not escape a RuntimeError from a
    pre-body headers read: the body is loaded before the headers are
    read, so the retry / IOError contract holds."""

    def setUp(self):
        self._key = Prefs.get('api_key', '')
        Prefs['api_key'] = 'test-key'

    def tearDown(self):
        Prefs['api_key'] = self._key

    def test_lazy_429_retries_with_retry_after(self):
        # A lazy 429 raises a coded HTTPError on the body load; the
        # Retry-After header read must happen after that load, and the
        # request must exhaust its attempts and return None — no
        # RuntimeError, no uncoded 500.
        install_transport({
            BASE + '/books/WQQDcMBQ3qUT':
                (429, {'Retry-After': '0'}, '{"error": "rate limited"}')
        }, lazy=True)
        self.assertIsNone(
            api_client.make_request(BASE + '/books/WQQDcMBQ3qUT'))
        self.assertEqual(
            len(HTTP.requests), api_client.MAX_ATTEMPTS)

    def test_lazy_redirect_follows_location(self):
        # A lazy 3xx reads the Location header only after the body
        # load; the followed hop's 2xx body is returned, not an
        # exception.
        install_transport({
            'https://cdn.audiobookdb.org/img':
                (302, {'Location': 'https://cdn.audiobookdb.org/img/real'},
                      ''),
            'https://cdn.audiobookdb.org/img/real':
                (200, 'JPEG-DATA'),
        }, lazy=True)
        self.assertEqual(
            api_client.fetch_bytes('https://cdn.audiobookdb.org/img'),
            b'JPEG-DATA')
        self.assertEqual(
            [req[0] for req in HTTP.requests],
            ['https://cdn.audiobookdb.org/img',
             'https://cdn.audiobookdb.org/img/real'])

    def test_lazy_uncoded_body_failure_retries_to_none(self):
        # A lazy body load that raises an exception without a .code
        # (plain IOError / RuntimeError, not a coded HTTPError) leaves
        # the status unknown: the attempt is treated as a 599 transport
        # failure and the full retry budget is burned.
        class _Boom(object):
            def __str__(self):
                raise IOError('connection reset')

        def transport(url, method='GET', headers=None, data=None):
            resp = _HTTPRequest(500, '', {})
            resp._lazy = True
            resp._body_loaded = False
            resp._body = _Boom()
            return resp

        install_transport({BASE + '/books/WQQDcMBQ3qUT': (500, '')})
        HTTP.transport = transport
        self.assertIsNone(
            api_client.make_request(BASE + '/books/WQQDcMBQ3qUT'))
        self.assertEqual(len(HTTP.requests), api_client.MAX_ATTEMPTS)


class TestJarCsrfToken(unittest.TestCase):
    def test_attribute_only_cookie_value_read(self):
        # The framework's CookieObject exposes attributes, not .get().
        # The name read already had an attribute fallback; the value read
        # must use the same supported access pattern.
        class CookieObject(object):
            name = 'csrf_token'
            value = 'tok-attr'
        old = HTTP.CookiesForURL
        HTTP.CookiesForURL = lambda url=None: [CookieObject()]
        try:
            self.assertEqual(api_client.jar_csrf_token(), 'tok-attr')
        finally:
            HTTP.CookiesForURL = old

    def test_dict_cookie_value_read(self):
        old = HTTP.CookiesForURL
        HTTP.CookiesForURL = lambda url=None: [
            {'name': 'csrf_token', 'value': 'tok-dict'}]
        try:
            self.assertEqual(api_client.jar_csrf_token(), 'tok-dict')
        finally:
            HTTP.CookiesForURL = old

    def test_comma_joined_set_cookie_header_value(self):
        # Some transports join multiple Set-Cookie values into one header
        # line; the comma fallback must still extract the token.
        response = _HTTPRequest(
            200, '{"books": 0}',
            {'Set-Cookie': 'x=1, csrf_token=tok-c, y=2'})
        self.assertEqual(api_client.csrf_cookie_value(response), 'tok-c')


class TestAnonymousCoded403(unittest.TestCase):
    """A coded 403 HTTPError raised in flight must reach search()'s
    re-prime branch, not be swallowed by the blanket except."""

    def setUp(self):
        self._key = Prefs.get('api_key', '')
        Prefs['api_key'] = ''
        api_client.csrf_invalidate()
        api_client.csrf_prime_count = 0

    def tearDown(self):
        Prefs['api_key'] = self._key
        api_client.csrf_invalidate()

    def test_eager_403_reprimes_and_retries(self):
        from plex_shim import HTTPError
        calls = {'post': 0}

        def transport(url, method='GET', headers=None, data=None):
            if method == 'POST':
                calls['post'] += 1
                if calls['post'] == 1:
                    # An eager transport raises its coded HTTPError in
                    # flight, so there is no response object to return.
                    raise HTTPError(url, 403, 'Forbidden', None, None)
                return _HTTPRequest(200, '[]')
            return _HTTPRequest(200, '{"books": 0}',
                                {'Set-Cookie': 'csrf_token=tok1; Path=/'})

        install_transport({}, jar_script=['tok2'])
        HTTP.transport = transport
        self.assertEqual(api_client.search('martian', 'books'), [])
        # Prime, rejected POST, re-prime, accepted POST.
        self.assertEqual([r[1] for r in HTTP.requests],
                         ['GET', 'POST', 'GET', 'POST'])
        self.assertEqual(calls['post'], 2)


if __name__ == '__main__':
    unittest.main()
