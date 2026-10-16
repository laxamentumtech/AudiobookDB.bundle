# -*- coding: utf-8 -*-
"""
API client tests: URL construction, headers, JSON decoding, error
envelopes, 404 handling, 429 Retry-After within the 4-attempt budget, and
the ASIN/detail/ratings helpers against recorded fixtures.
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

BASE = 'https://audiobookdb.org/api'

FIXTURES = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'audiobookdb')


def load_fixture(name):
    with open(os.path.join(FIXTURES, name), 'rb') as f:
        return json.loads(f.read().decode('utf-8'))


def api_body(payload):
    """Serialize a fixture payload the way the legacy wire transport did."""
    return json.dumps(payload, ensure_ascii=True)


def install_transport(mapping, default=''):
    """Map URL -> (status, body); records requests on HTTP.requests."""
    def transport(url, method='GET', headers=None, data=None):
        if url in mapping:
            status, body = mapping[url]
        else:
            status, body = 404, default
        return _HTTPRequest(status, body)
    HTTP.Reset()
    HTTP.Headers = {}
    HTTP.Headers['X-API-Key'] = 'anonymous'
    HTTP.transport = transport
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
        install_transport({BASE + '/img': (200, 'JPEG-DATA')})
        self.assertEqual(
            api_client.fetch_bytes(BASE + '/img'), b'JPEG-DATA')

    def test_raises_after_exhaustion(self):
        install_transport({})
        self.assertRaises(IOError, api_client.fetch_bytes, BASE + '/img')


class TestPostJson(unittest.TestCase):
    def test_headers_and_body(self):
        install_transport({BASE + '/search': (200, '[{"id": "x"}]')})
        HTTP.Headers['X-API-Key'] = 'test-key'
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

    def test_search_books_fixture(self):
        hits = load_fixture('search_books_martian.json')
        install_transport({BASE + '/search': (200, api_body(hits))})
        out = api_client.search('The Martian', 'books')
        self.assertEqual(len(out), 10)
        self.assertEqual(out[1]['id'], 'WQQDcMBQ3qUT')

    def test_search_people_fixture(self):
        hits = load_fixture('search_people_andy_weir.json')
        install_transport({BASE + '/search': (200, api_body(hits))})
        out = api_client.search('Andy Weir', 'people')
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['id'], 'ypMPwXzWXaiX')

    def test_search_short_q_no_filters_returns_empty(self):
        install_transport({BASE + '/search': (200, '[]')})
        self.assertEqual(api_client.search('ab', 'books'), [])
        self.assertEqual(HTTP.requests, [])  # no request made


class TestRetryAfter(unittest.TestCase):
    def test_429_then_success(self):
        state = {'n': 0}
        Prefs['logging_level'] = 'ERROR'

        def transport(url, method='GET', headers=None, data=None):
            state['n'] += 1
            if state['n'] == 1:
                return _HTTPRequest(429, '', {'retry-after': '0'})
            return _HTTPRequest(200, '{"ok": true}')
        HTTP.Reset()
        HTTP.Headers = {'X-API-Key': 'anonymous'}
        HTTP.transport = transport
        self.assertEqual(api_client.make_request(BASE + '/x'), {'ok': True})
        self.assertEqual(state['n'], 2)

    def test_429_exhausted_returns_none(self):
        Prefs['logging_level'] = 'ERROR'

        def transport(url, method='GET', headers=None, data=None):
            return _HTTPRequest(429, '', {'retry-after': '0'})
        HTTP.Reset()
        HTTP.Headers = {'X-API-Key': 'anonymous'}
        HTTP.transport = transport
        self.assertIsNone(api_client.make_request(BASE + '/x'))
        self.assertEqual(len(HTTP.requests), api_client.MAX_ATTEMPTS)


if __name__ == '__main__':
    unittest.main()
