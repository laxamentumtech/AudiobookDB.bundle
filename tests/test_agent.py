# -*- coding: utf-8 -*-
"""
Tests for Contents/Code/__init__.py (agent classes) against AudiobookDB
fixtures. Covers the Phase-3 new-behavior checks 1-7 from the plan.
"""

import os
import sys
import json
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import plex_shim  # noqa: F401,E402  (framework fails must load first)

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

import api_client  # noqa: E402

# Zero the inter-attempt sleep so failure-path tests are fast.
api_client.DEFAULT_RETRY_AFTER = 0

BASE = api_client.BASE_URL
FIXTURES = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'audiobookdb')


def load_fixture(name):
    with open(os.path.join(FIXTURES, name), 'rb') as f:
        return json.loads(f.read().decode('utf-8'))


def api_body(payload):
    """Serialize a fixture payload the way the wire transport does."""
    return json.dumps(payload, ensure_ascii=True)


# Fixture names
BOOK_DETAIL = 'book_detail_WQQDcMBQ3qUT.json'
RELEASE_DETAIL = 'release_detail_dPL9fC7YnK8X.json'
PERSON_DETAIL = 'person_detail_ypMPwXzWXaiX.json'
NO_RELEASES = 'book_detail_no_releases_WQQDcMBQ3qUT.json'


def default_mapping():
    """The full fixture-backed URL map for album + person flows."""
    return {
        BASE + '/search': None,  # overridden per test
        BASE + '/audiobooks/external/audible/B00B5HZGUG': (
            200, api_body(load_fixture('book_external_resolve_B00B5HZGUG.json'))),
        BASE + '/books/WQQDcMBQ3qUT': (
            200, api_body(load_fixture(BOOK_DETAIL))),
        BASE + '/releases/dPL9fC7YnK8X': (
            200, api_body(load_fixture(RELEASE_DETAIL))),
        BASE + '/items/book/WQQDcMBQ3qUT/ratings': (
            200, api_body(load_fixture('ratings_book_WQQDcMBQ3qUT.json'))),
        BASE + '/people?external=Audible%3AB00G0WYW92&take=2': (
            200, api_body(
                load_fixture('person_external_resolve_B00G0WYW92.json'))),
        BASE + '/people/ypMPwXzWXaiX': (
            200, api_body(load_fixture(PERSON_DETAIL))),
    }


def install_transport(search_hits, mapping=None, thumb_body=b'JPEGDATA'):
    """Fixture-backed transport; records requests on HTTP.requests."""
    _prefs()
    mapping = dict(default_mapping()) if mapping is None else mapping
    if search_hits is not None:
        mapping[BASE + '/search'] = (200, api_body(search_hits))

    def transport(url, method='GET', headers=None, data=None):
        if url.endswith('/large.jpg'):
            return _HTTPRequest(200, thumb_body)
        if url in mapping:
            status, body = mapping[url]
            return _HTTPRequest(status, body)
        return _HTTPRequest(404, '')

    HTTP.Reset()
    HTTP.Headers = {}
    HTTP.Headers['X-API-Key'] = 'anonymous'
    HTTP.transport = transport
    return transport


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
    Prefs['logging_level'] = 'ERROR'
    Prefs['keep_existing_genres'] = False
    Prefs['store_author_as_mood'] = True
    Prefs['sort_author_by_last_name'] = True
    Prefs['simplify_title'] = False
    Prefs['api_key'] = ''
    return Prefs


def album_media(**kw):
    kw.setdefault('title', 'The Martian')
    kw.setdefault('album', 'The Martian')
    kw.setdefault('artist', 'Andy Weir')
    return FakeMedia(**kw)


def artist_media(**kw):
    kw.setdefault('artist', 'Andy Weir')
    return FakeMedia(**kw)


class TestStartAndIdentity(unittest.TestCase):
    def test_start_headers(self):
        _prefs()
        agent.Start()
        self.assertEqual(HTTP.Headers['User-agent'], api_client.USER_AGENT)
        self.assertEqual(HTTP.Headers['X-API-Key'], 'anonymous')
        self.assertEqual(HTTP.CacheTime, CACHE_1WEEK)

    def test_start_uses_pref_key(self):
        _prefs()
        Prefs['api_key'] = 'test-key'
        agent.Start()
        self.assertEqual(HTTP.Headers['X-API-Key'], 'test-key')
        Prefs['api_key'] = ''

    def test_agent_names(self):
        self.assertEqual(agent.AudiobookAlbum.name, 'AudiobookDB Agent')
        self.assertEqual(agent.AudiobookArtist.name, 'AudiobookDB Agent')

    def test_validate_prefs_noop(self):
        _prefs()
        self.assertIsNone(agent.ValidatePrefs())

    def test_get_date_from_string(self):
        tool = agent.AudiobookAlbum()
        self.assertEqual(
            str(tool.getDateFromString('2013-03-22T00:00:00Z')),
            '2013-03-22')
        self.assertIsNone(tool.getDateFromString(None))
        self.assertIsNone(tool.getDateFromString('garbage'))


class TestAlbumSearch(unittest.TestCase):
    """New-behavior check 1: fixture-backed album search."""

    @staticmethod
    def _two_hit_response():
        return [
            {
                'id': 'aaaaaaaaaaaa',
                'title': 'The Martian',
                'people': [
                    {'role': {'name': 'Author'},
                     'person': {'id': 'p1', 'name': 'Andy Weir'}}
                ],
                'originalLanguage': 'English',
            },
            {
                'id': 'bbbbbbbbbbbb',
                'title': 'The Martians',
                'people': [
                    {'role': {'name': 'Author'},
                     'person': {'id': 'p1', 'name': 'Andy Weir'}}
                ],
                'originalLanguage': 'English',
            },
        ]

    def _search(self, hits, manual):
        install_transport(hits)
        results = _Results()
        agent.AudiobookAlbum().search(
            results, album_media(), plex_shim.Locale.Language.English,
            manual)
        return results.appended

    def test_search_breaks_on_good_score(self):
        appended = self._search(self._two_hit_response(), manual=False)
        # Top result scores 100 >= GOOD_SCORE (98), so the loop breaks
        # after the first append; the ~95-score hit is never appended.
        self.assertEqual(len(appended), 1)
        self.assertEqual(appended[0].id, 'book.aaaaaaaaaaaa')
        self.assertEqual(appended[0].score, 100)

    def test_manual_keeps_below_good_score(self):
        appended = self._search(self._two_hit_response(), manual=True)
        # Manual mode never short-circuits: both hits are appended.
        self.assertEqual(len(appended), 2)
        self.assertEqual(appended[0].id, 'book.aaaaaaaaaaaa')
        self.assertEqual(appended[0].score, 100)
        self.assertEqual(appended[1].id, 'book.bbbbbbbbbbbb')
        self.assertTrue(45 <= appended[1].score < 98)

    def test_fixture_search_appends_serialized_id(self):
        install_transport(load_fixture('search_books_martian.json'))
        results = _Results()
        agent.AudiobookAlbum().search(
            results, album_media(), plex_shim.Locale.Language.English,
            False)
        self.assertEqual(len(results.appended), 1)
        r = results.appended[0]
        self.assertEqual(r.id, 'book.WQQDcMBQ3qUT')
        # ScoreTool arithmetic: 100 - 0 (album) - 0 (author)
        # - 0 (language) - 1 (index) = 99
        self.assertEqual(r.score, 99)
        # Book search hits carry no date -> year is None (r.get('year')).
        self.assertIsNone(r.year)
        self.assertIn('The Martian', r.name)
        self.assertIn('A.Weir', r.name)

    def test_search_posts_search_body(self):
        install_transport(load_fixture('search_books_martian.json'))
        results = _Results()
        agent.AudiobookAlbum().search(
            results, album_media(), plex_shim.Locale.Language.English,
            True)
        search_reqs = [req for req in HTTP.requests if req[0] == BASE + '/search']
        self.assertEqual(len(search_reqs), 1)
        self.assertEqual(search_reqs[0][1], 'POST')
        body = json.loads(search_reqs[0][3])
        self.assertEqual(body['type'], 'books')
        self.assertEqual(body['q'], 'The Martian')
        self.assertEqual(body['filters'], {'person': 'Andy Weir'})


class TestAlbumQuickMatch(unittest.TestCase):
    """New-behavior check 2: ASIN quick match via the helper alone."""

    def test_asin_in_album_appends_single_score_100(self):
        install_transport(None)
        results = _Results()
        agent.AudiobookAlbum().search(
            results,
            album_media(album='The Martian B00B5HZGUG'),
            plex_shim.Locale.Language.English,
            False)
        self.assertEqual(len(results.appended), 1)
        r = results.appended[0]
        self.assertEqual(r.id, 'book.WQQDcMBQ3qUT.release.dPL9fC7YnK8X')
        self.assertEqual(r.score, 100)
        # The agent did not run the normal search path.
        search_reqs = [req for req in HTTP.requests
                       if req[0] == BASE + '/search']
        self.assertEqual(search_reqs, [])

    def test_asin_in_filename_appends_single_score_100(self):
        install_transport(None)
        results = _Results()
        agent.AudiobookAlbum().search(
            results,
            album_media(filename='The%20Martian%20B00B5HZGUG'),
            plex_shim.Locale.Language.English,
            False)
        self.assertEqual(len(results.appended), 1)
        self.assertEqual(
            results.appended[0].id, 'book.WQQDcMBQ3qUT.release.dPL9fC7YnK8X')
        self.assertEqual(results.appended[0].score, 100)

    def test_unresolvable_asin_falls_through(self):
        install_transport(None)
        results = _Results()
        agent.AudiobookAlbum().search(
            results,
            album_media(album='The Martian B0AAAAAAAAA'),
            plex_shim.Locale.Language.English,
            True)
        # B0AAAAAAAAA 404s; 'The Martian' (3+ chars) triggers a search,
        # which 404s too -> no results.
        self.assertEqual(results.appended, [])


class TestAlbumUpdate(unittest.TestCase):
    """New-behavior checks 3, 5, 6, 7: album update migration."""

    def _run_update(self, metadata_id, mapping=None):
        install_transport(None, mapping=mapping)
        media = FakeMedia(title='The Martian')
        metadata = FakeMetadata(metadata_id)
        agent.AudiobookAlbum().update(
            metadata, media, plex_shim.Locale.Language.English, False)
        return metadata

    def test_legacy_asin_migration(self):
        """Check 3: legacy ASIN -> populated + native ID rewrite."""
        metadata = self._run_update('B00B5HZGUG_us')
        self.assertEqual(metadata.title, 'The Martian')
        self.assertEqual(metadata.studio, 'Podium Publishing')
        self.assertEqual(
            str(metadata.originally_available_at), '2013-03-22')
        self.assertEqual(metadata.styles, {'R.C. Bray'})
        self.assertIn('Science Fiction', metadata.genres)
        self.assertEqual(metadata.moods, {'Andy Weir'})
        self.assertEqual(metadata.id, 'book.WQQDcMBQ3qUT.release.dPL9fC7YnK8X')
        # Check 7: audible chip (not first) x 2.
        self.assertEqual(metadata.rating, 4.8 * 2)
        # Poster fetched (sized derivative) and stored.
        cover = load_fixture(BOOK_DETAIL)['coverImage']['url'] + '/large.jpg'
        self.assertIn(cover, metadata.posters)
        poster, sort_order = metadata.posters[cover]
        self.assertEqual(sort_order, 0)
        self.assertEqual(poster, b'JPEGDATA')

    def test_second_update_native_only_detail_endpoints(self):
        """Check 3b: native ID update hits only detail endpoints."""
        self._run_update('book.WQQDcMBQ3qUT.release.dPL9fC7YnK8X')
        urls = [req[0] for req in HTTP.requests]
        self.assertIn(BASE + '/books/WQQDcMBQ3qUT', urls)
        self.assertIn(BASE + '/releases/dPL9fC7YnK8X', urls)
        self.assertIn(BASE + '/items/book/WQQDcMBQ3qUT/ratings', urls)
        for url in urls:
            self.assertNotIn('/audiobooks/external/', url)
            self.assertNotIn('/search', url)

    def test_404_leaves_untouched(self):
        """Check 5: unresolvable legacy ASIN -> metadata untouched."""
        metadata = self._run_update('B0AAAAAAAAA_us')
        self.assertEqual(metadata.id, 'B0AAAAAAAAA_us')
        self.assertIsNone(metadata.title)
        self.assertIsNone(metadata.summary)
        self.assertIsNone(metadata.studio)
        self.assertIsNone(metadata.originally_available_at)
        self.assertIsNone(metadata.rating)
        self.assertEqual(metadata.genres, set())
        self.assertEqual(metadata.styles, set())
        self.assertEqual(metadata.moods, set())

    def test_no_release_work_only_path(self):
        """Check 6: work-only book -> book-level fields, no release writes."""
        mapping = default_mapping()
        mapping[BASE + '/books/WQQDcMBQ3qUT'] = (
            200, api_body(load_fixture(NO_RELEASES)))
        mapping[BASE + '/items/book/WQQDcMBQ3qUT/ratings'] = (
            200, api_body({'chips': []}))
        no_releases_book = load_fixture(NO_RELEASES)
        metadata = self._run_update('book.WQQDcMBQ3qUT', mapping=mapping)
        self.assertEqual(metadata.id, 'book.WQQDcMBQ3qUT')
        self.assertEqual(metadata.title, 'The Martian')
        self.assertEqual(metadata.summary, no_releases_book.get('description'))
        self.assertIn('Science Fiction', metadata.genres)
        # No release: no date, no studio, no narrators in styles.
        self.assertIsNone(metadata.originally_available_at)
        self.assertIsNone(metadata.studio)
        self.assertEqual(metadata.styles, set())

    def test_pinned_release_404_preserved(self):
        mapping = default_mapping()
        del mapping[BASE + '/releases/dPL9fC7YnK8X']
        install_transport(None, mapping=mapping)
        metadata = FakeMetadata('book.WQQDcMBQ3qUT.release.dPL9fC7YnK8X')
        agent.AudiobookAlbum().update(
            metadata, FakeMedia(title='The Martian'),
            plex_shim.Locale.Language.English, False)
        self.assertEqual(
            metadata.id, 'book.WQQDcMBQ3qUT.release.dPL9fC7YnK8X')
        self.assertIsNone(metadata.title)


class TestArtistSearchAndUpdate(unittest.TestCase):
    """New-behavior check 4: person migration + search round trip."""

    def test_legacy_asin_migration(self):
        install_transport(None)
        media = FakeMedia(title='Andy Weir')
        metadata = FakeMetadata('B00G0WYW92')
        agent.AudiobookArtist().update(
            metadata, media, plex_shim.Locale.Language.English, False)
        self.assertEqual(metadata.id, 'person.ypMPwXzWXaiX')
        self.assertEqual(metadata.title, 'Andy Weir')
        self.assertIsNotNone(metadata.summary)
        self.assertIn('Fantasy', metadata.genres)

    def test_404_leaves_untouched(self):
        install_transport(None)
        metadata = FakeMetadata('B0AAAAAAAAA')
        agent.AudiobookArtist().update(
            metadata, FakeMedia(title='Nobody'),
            plex_shim.Locale.Language.English, False)
        self.assertEqual(metadata.id, 'B0AAAAAAAAA')
        self.assertIsNone(metadata.title)
        self.assertIsNone(metadata.summary)

    def test_search_update_round_trip(self):
        # Search the author.
        install_transport(load_fixture('search_people_andy_weir.json'))
        results = _Results()
        agent.AudiobookArtist().search(
            results, artist_media(), plex_shim.Locale.Language.English,
            True)
        self.assertEqual(len(results.appended), 1)
        self.assertEqual(results.appended[0].id, 'person.ypMPwXzWXaiX')

        # Update through the native ID (round trip).
        install_transport(None)
        metadata = FakeMetadata('person.ypMPwXzWXaiX')
        agent.AudiobookArtist().update(
            metadata, FakeMedia(title='Andy Weir'),
            plex_shim.Locale.Language.English,
            False)
        self.assertEqual(metadata.title, 'Andy Weir')
        self.assertIn('Fantasy', metadata.genres)
        # Native branch: only the person detail endpoint was hit.
        urls = [req[0] for req in HTTP.requests]
        self.assertEqual(urls, [BASE + '/people/ypMPwXzWXaiX'])


if __name__ == '__main__':
    unittest.main()
