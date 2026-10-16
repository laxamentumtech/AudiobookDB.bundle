# -*- coding: utf-8 -*-
"""Tests for Contents/Code/__init__.py (agent classes + module helpers)."""

import os
import sys
import json
import datetime
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import plex_shim  # noqa: F401,E402  (framework fakes must load first)

from plex_shim import (  # noqa: E402
    HTTP, Log, Prefs, _Results, _HTTPRequest, CACHE_1WEEK,
)

_CODE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                     'Contents', 'Code')
if sys.version_info[0] == 2:
    import imp
    agent = imp.load_source(
        'agent_init', os.path.join(_CODE, '__init__.py'))
else:
    import importlib.util
    _spec = importlib.util.spec_from_file_location(
        'agent_init', os.path.join(_CODE, '__init__.py'))
    agent = importlib.util.module_from_spec(_spec)
    sys.modules['agent_init'] = agent
    _spec.loader.exec_module(agent)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'fixtures', 'legacy')


def load_fixture(name):
    with open(os.path.join(FIXTURES, name), 'rb') as f:
        return json.loads(f.read().decode('utf-8'))


class FakeMedia(object):
    def __init__(self, **kw):
        self.title = kw.get('title')
        self.album = kw.get('album')
        self.artist = kw.get('artist')
        self.name = kw.get('name')
        self.filename = kw.get('filename')
        self.parent_metadata = type('PM', (), {'id': 'ASIN_pm'})()


class FakePosters(dict):
    def validate_keys(self, keys):
        pass


class FakeMetadata(object):
    def __init__(self, id):
        self.id = id
        self.title = None
        self.title_sort = None
        self.summary = None
        self.studio = None
        self.originally_available_at = None
        self.rating = None
        self.genres = set()
        self.moods = set()
        self.styles = set()
        self.similar = set()
        self.posters = FakePosters()

def _prefs():
    Prefs['region'] = 'us'
    Prefs['logging_level'] = 'INFO'
    Prefs['keep_existing_genres'] = False
    Prefs['store_author_as_mood'] = True
    Prefs['sort_author_by_last_name'] = True
    Prefs['simplify_title'] = False
    Prefs['api_key'] = ''
    return Prefs


def install_transport(mapping, default=''):
    """Map URL -> (status, body); records requests on HTTP.requests.

    Bodies are ASCII-escaped JSON so decoded strings are ``str`` under
    Python 2 (matching what the legacy bundle saw from real APIs).
    """
    def transport(url, method='GET', headers=None, data=None):
        if url in mapping:
            status, body = mapping[url]
        else:
            status, body = 404, default
        return _HTTPRequest(status, body)
    HTTP.Reset()
    HTTP.transport = transport
    return transport


def api_body(payload):
    """Serialize a fixture payload the way the legacy wire transport did."""
    return json.dumps(payload, ensure_ascii=True)


BOOK_DETAIL_URL = 'https://api.audnex.us/books/B00B5HZGUG?region=us'
ARTIST_DETAIL_URL = 'https://api.audnex.us/authors/B00G0WYW92?region=us'


class TestModuleHelpers(unittest.TestCase):
    def test_version(self):
        self.assertEqual(agent.VERSION_NO, '1.3.2')

    def test_json_decode_dict(self):
        self.assertEqual(agent.json_decode('{"a": 1}'), {'a': 1})

    def test_json_decode_garbage(self):
        # Legacy quirk: json_decode only catches AttributeError; on py3 a
        # JSONDecodeError (not an AttributeError) escapes for non-JSON
        # input.
        self.assertRaises(Exception, agent.json_decode, 'not json')

    def test_make_request_success(self):
        install_transport({'http://example.com/x': (200, 'body-bytes')})
        # make_request returns str(HTTP.Request(...)): the response body.
        self.assertEqual(str(agent.make_request('http://example.com/x')),
                         'body-bytes')

    def test_make_request_failure_raises_type_error(self):
        # Legacy defect (LEGACY_ISSUES #1): the retry loop is dead code --
        # the except body does "Failed http request attempt #" + x
        # (str + int) which raises TypeError on both py2 and py3.
        def raising(url, method='GET'):
            raise IOError('boom')
        HTTP.Reset()
        HTTP.transport = raising
        self.assertRaises(TypeError, agent.make_request, 'http://x')


class TestStartAndValidate(unittest.TestCase):
    def test_start(self):
        _prefs()
        HTTP.Reset()
        Log.Clear()
        agent.Start()
        self.assertEqual(HTTP.CacheTime, CACHE_1WEEK)
        self.assertIn('MSIE 8.0', HTTP.Headers['User-agent'])
        self.assertEqual(HTTP.Headers['Accept-Encoding'], 'gzip')
        msgs = [e[1] for e in Log.entries]
        self.assertTrue(any('Audnexus Audiobooks Agent v1.3.2' in m
                            for m in msgs))

    def test_validate_prefs(self):
        _prefs()
        Log.Clear()
        agent.ValidatePrefs()  # must not raise


class TestAgentClassAttrs(unittest.TestCase):
    def test_artist_attrs(self):
        self.assertEqual(agent.AudiobookArtist.name, 'Audnexus Agent')
        self.assertTrue(agent.AudiobookArtist.primary_provider)
        self.assertEqual(agent.AudiobookArtist.accepts_from,
                         ['com.plexapp.agents.localmedia'])

    def test_album_attrs(self):
        self.assertEqual(agent.AudiobookAlbum.name, 'Audnexus Agent')
        self.assertTrue(agent.AudiobookAlbum.primary_provider)
        self.assertEqual(agent.AudiobookAlbum.accepts_from,
                         ['com.plexapp.agents.localmedia'])


class TestArtistSearch(unittest.TestCase):
    def _run(self, media, manual=False):
        _prefs()
        mapping = {
            'https://api.audnex.us/authors?region=us&name=Andy%20Weir':
                (200, api_body(load_fixture('author_search.json'))),
        }
        install_transport(mapping)
        results = _Results()
        agent.AudiobookArtist().search(
            results, media, plex_shim.Locale.Language.English, manual)
        return results.appended

    def test_search_appends(self):
        appended = self._run(FakeMedia(artist='Andy Weir'))
        self.assertEqual(len(appended), 1)
        self.assertEqual(appended[0].id, 'B00G0WYW92')
        self.assertEqual(appended[0].name, 'Andy Weir')
        self.assertEqual(appended[0].score, 100)

    def test_quick_match_asin(self):
        appended = self._run(FakeMedia(artist='Andy Weir B00G0WYW92'))
        self.assertEqual(len(appended), 1)
        self.assertEqual(appended[0].id, 'B00G0WYW92_us')
        self.assertEqual(appended[0].name, 'B00G0WYW92_us')
        self.assertEqual(appended[0].score, 100)
        self.assertEqual(appended[0].year, 1969)
        self.assertEqual(HTTP.requests, [])  # no API call made

    def test_bad_artist_name_no_results(self):
        appended = self._run(FakeMedia(artist='[Unknown Artist]'))
        self.assertEqual(appended, [])
        self.assertEqual(HTTP.requests, [])


class TestAlbumSearch(unittest.TestCase):
    SEARCH_URL = ('https://api.audible.com/1.0/catalog/products'
                  '?response_groups=contributors,product_desc,'
                  'product_attrs&num_results=25&products_sort_by='
                  'Relevance&title=The%20Martian&author=Andy%20Weir')

    def _media(self):
        return FakeMedia(album='The Martian', artist='Andy Weir')

    def _synthetic_response(self):
        # Two English editions: top scores 100, second ~63 (>= IGNORE_SCORE
        # 45, < GOOD_SCORE 98) so manual vs auto behavior differs.
        return [
            {'asin': 'B082BHJMFF',
             'authors': [{'name': 'Andy Weir'}],
             'language': 'english',
             'narrators': [{'name': 'Wil Wheaton'}],
             'release_date': '2020-01-01',
             'title': 'The Martian'},
            {'asin': 'B079YDJ18Z',
             'authors': [{'name': 'Andy Weir'}],
             'language': 'english',
             'narrators': [{'name': 'Wil Wheaton'}],
             'release_date': '2018-02-22',
             'title': 'The Martian Unabridged Edition'},
        ]

    def _run(self, products, manual):
        _prefs()
        install_transport({
            self.SEARCH_URL: (200, api_body({'products': products})),
        })
        results = _Results()
        agent.AudiobookAlbum().search(
            results, self._media(), plex_shim.Locale.Language.English,
            manual)
        return results.appended

    def test_search_breaks_on_good_score(self):
        appended = self._run(self._synthetic_response(), manual=False)
        # Top result scores 100 >= GOOD_SCORE (98), so the loop breaks
        # after the first append.
        self.assertEqual(len(appended), 1)
        self.assertEqual(appended[0].id, 'B082BHJMFF_us')
        self.assertEqual(appended[0].score, 100)
        self.assertEqual(appended[0].year, 2020)

    def test_manual_keeps_below_good_score(self):
        appended = self._run(self._synthetic_response(), manual=True)
        self.assertEqual(len(appended), 2)
        self.assertEqual(appended[0].id, 'B082BHJMFF_us')
        self.assertEqual(appended[0].score, 100)
        self.assertEqual(appended[1].id, 'B079YDJ18Z_us')
        self.assertTrue(45 <= appended[1].score < 98)

    def test_result_name_display(self):
        appended = self._run(self._synthetic_response(), manual=True)
        self.assertEqual(
            appended[0].name, '"The Martian" by A.Weir w/ W.Wheaton'
        )

    def test_fixture_search(self):
        # Live-recorded fixture: the Spanish edition scores below
        # IGNORE_SCORE (45) and is skipped.
        _prefs()
        install_transport({
            self.SEARCH_URL:
                (200, api_body(load_fixture('book_search.json'))),
        })
        results = _Results()
        agent.AudiobookAlbum().search(
            results, self._media(), plex_shim.Locale.Language.English,
            True)
        self.assertEqual(len(results.appended), 1)
        self.assertEqual(results.appended[0].id, 'B082BHJMFF_us')
        self.assertEqual(
            results.appended[0].name, '"The Martian" by A.Weir w/ W.Wheaton'
        )

    def test_pre_search_unknown_album_bails(self):
        _prefs()
        install_transport({})
        results = _Results()
        agent.AudiobookAlbum().search(
            results, FakeMedia(album='[Unknown Album]'),
            plex_shim.Locale.Language.English, False)
        self.assertEqual(results.appended, [])

    def test_quick_match_asin(self):
        _prefs()
        install_transport({})
        results = _Results()
        agent.AudiobookAlbum().search(
            results, FakeMedia(album='The Martian B00B5HZGUG',
                               artist='Andy Weir'),
            plex_shim.Locale.Language.English, False)
        self.assertEqual(len(results.appended), 1)
        self.assertEqual(results.appended[0].id, 'B00B5HZGUG_us')
        self.assertEqual(results.appended[0].score, 100)
        self.assertEqual(HTTP.requests, [])

    def test_filename_asin_quick_match(self):
        _prefs()
        install_transport({})
        results = _Results()
        agent.AudiobookAlbum().search(
            results, FakeMedia(album='The Martian', artist='Andy Weir',
                               filename='The%20Martian%20B00B5HZGUG'),
            plex_shim.Locale.Language.English, False)
        self.assertEqual(len(results.appended), 1)
        self.assertEqual(results.appended[0].id, 'B00B5HZGUG_us')


class TestAlbumUpdate(unittest.TestCase):
    def _run(self, id, force=False):
        _prefs()
        mapping = {
            BOOK_DETAIL_URL: (200, api_body(
                load_fixture('book_detail.json'))),
        }
        install_transport(mapping)
        metadata = FakeMetadata(id)
        agent.AudiobookAlbum().update(
            metadata, FakeMedia(title='The Martian'),
            plex_shim.Locale.Language.English, force)
        return metadata

    def test_update_populates(self):
        metadata = self._run('B00B5HZGUG_us')
        fixture = load_fixture('book_detail.json')
        self.assertEqual(metadata.title, 'The Martian')
        self.assertEqual(metadata.studio, 'Podium Publishing')
        self.assertEqual(
            metadata.originally_available_at,
            datetime.date(2013, 3, 22)
        )
        self.assertEqual(
            metadata.genres, {g['name'] for g in fixture['genres']}
        )
        self.assertEqual(metadata.moods, {'Andy Weir'})
        self.assertEqual(metadata.styles, {'R. C. Bray'})
        self.assertEqual(metadata.rating, 9.6)
        self.assertEqual(metadata.title_sort, 'The Martian')
        self.assertIn('Mark Watney', metadata.summary)

    def test_update_stores_poster(self):
        # compile_metadata fetches helper.thumb via make_request (HTTP
        # transport); the detail map above has no image entry, so the
        # transport default 404 body is stored.
        metadata = self._run('B00B5HZGUG_us')
        fixture = load_fixture('book_detail.json')
        self.assertEqual(str(metadata.posters[fixture['image']][0]), '')

    def test_poster_not_refetched_without_force(self):
        fixture = load_fixture('book_detail.json')
        _prefs()
        install_transport({
            BOOK_DETAIL_URL: (200, api_body(fixture)),
            fixture['image']: (200, 'JPEGDATA'),
        })
        metadata = FakeMetadata('B00B5HZGUG_us')
        for _ in range(2):
            agent.AudiobookAlbum().update(
                metadata, FakeMedia(title='The Martian'),
                plex_shim.Locale.Language.English, False)
        poster_requests = [req[0] for req in HTTP.requests
                           if req[0] == fixture['image']]
        self.assertEqual(len(poster_requests), 1)
        self.assertEqual(
            str(metadata.posters[fixture['image']][0]),
            'JPEGDATA')

    def test_poster_refetched_on_force(self):
        fixture = load_fixture('book_detail.json')
        _prefs()
        install_transport({
            BOOK_DETAIL_URL: (200, api_body(fixture)),
            fixture['image']: (200, 'JPEGDATA'),
        })
        metadata = FakeMetadata('B00B5HZGUG_us')
        agent.AudiobookAlbum().update(
            metadata, FakeMedia(title='The Martian'),
            plex_shim.Locale.Language.English, False)
        agent.AudiobookAlbum().update(
            metadata, FakeMedia(title='The Martian'),
            plex_shim.Locale.Language.English, True)
        poster_requests = [req[0] for req in HTTP.requests
                           if req[0] == fixture['image']]
        self.assertEqual(len(poster_requests), 2)

    def test_update_only_requests_detail(self):
        self._run('B00B5HZGUG_us')
        detail_requests = [req[0] for req in HTTP.requests
                           if 'audnex' in req[0]]
        self.assertEqual(detail_requests, [BOOK_DETAIL_URL])


class TestArtistUpdate(unittest.TestCase):
    def _run(self, id, force=False):
        _prefs()
        mapping = {
            'https://api.audnex.us/authors/B00B5HZGUG?region=us':
                (200, api_body(load_fixture('author_detail.json'))),
        }
        install_transport(mapping)
        metadata = FakeMetadata(id)
        agent.AudiobookArtist().update(
            metadata, FakeMedia(title='Andy Weir'),
            plex_shim.Locale.Language.English, force)
        return metadata

    def test_update_populates(self):
        metadata = self._run('B00B5HZGUG_us')
        fixture = load_fixture('author_detail.json')
        self.assertEqual(metadata.title, 'Andy Weir')
        self.assertIn('software engineer', metadata.summary)
        self.assertEqual(metadata.title_sort, 'Weir, Andy')
        self.assertEqual(
            metadata.genres, {g['name'] for g in fixture['genres']}
        )
        self.assertEqual(
            metadata.similar, {a['name'] for a in fixture['similar']}
        )
        self.assertIn(fixture['image'], metadata.posters)

    def test_update_bare_asin_id(self):
        # extract_region_from_id appends the preferred region to bare IDs,
        # and build_url strips the region suffix again for the API URL.
        _prefs()
        mapping = {
            'https://api.audnex.us/authors/B00G0WYW92?region=us':
                (200, api_body(load_fixture('author_detail.json'))),
        }
        install_transport(mapping)
        metadata = FakeMetadata('B00G0WYW92')
        agent.AudiobookArtist().update(
            metadata, FakeMedia(title='Andy Weir'),
            plex_shim.Locale.Language.English, False)
        self.assertEqual(metadata.id, 'B00G0WYW92_us')
        self.assertEqual(metadata.title, 'Andy Weir')


class TestGetDateFromString(unittest.TestCase):
    def test_valid_iso(self):
        agent.AudiobookAlbum().getDateFromString('2013-03-22T00:00:00.000Z')
        d = agent.AudiobookAlbum().getDateFromString('2013-03-22T00:00:00Z')
        self.assertEqual(d, datetime.date(2013, 3, 22))

    def test_none(self):
        self.assertIsNone(agent.AudiobookAlbum().getDateFromString(None))

    def test_garbage(self):
        self.assertIsNone(agent.AudiobookAlbum().getDateFromString('nope'))
