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
        BASE + '/releases/RAffFyqchypK': (
            200, api_body(
                load_fixture('release_detail_RAffFyqchypK.json'))),
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
    Prefs['api_key'] = 'test-key'
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
    HTTP.transport = transport
    return transport


class FakeMedia(object):
    def __init__(self, **kw):
        self.title = kw.get('title')
        self.album = kw.get('album')
        self.artist = kw.get('artist')
        self.name = kw.get('name')
        self.filename = kw.get('filename')
        self.parent_metadata = type('PM', (), {'id': kw.get('parent_id', 'ASIN_pm')})()
        self.tree = kw.get('tree')
        self.children = kw.get('children', [])


def plex_track(track_id, index, title, duration, path, language='eng', disc=1):
    stream = type('Stream', (), {'type': 2, 'languageCode': language})()
    part = type('Part', (), {'file': path, 'streams': [stream]})()
    item = type('Item', (), {'parts': [part]})()
    return type('Track', (), {
        'id': track_id, 'index': str(index), 'parentIndex': str(disc),
        'title': title, 'duration': str(duration), 'items': [item],
    })()


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
        # The API key is attached per-request to the API origin only; it
        # must not be a global default that rides along on image fetches.
        self.assertNotIn('X-API-Key', HTTP.Headers)
        self.assertEqual(HTTP.CacheTime, CACHE_1WEEK)

    def test_start_uses_pref_key(self):
        _prefs()
        Prefs['api_key'] = 'test-key'
        agent.Start()
        # No global header: the pref key travels with api_client calls.
        self.assertNotIn('X-API-Key', HTTP.Headers)
        self.assertEqual(api_client.api_key(), 'test-key')
        Prefs['api_key'] = ''

    def test_agent_names(self):
        self.assertEqual(agent.AudiobookAlbum.name, 'AudiobookDB Agent')
        self.assertEqual(agent.AudiobookArtist.name, 'AudiobookDB Agent')

    def test_validate_prefs_noop(self):
        _prefs()
        self.assertIsNone(agent.ValidatePrefs())


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
        # The hit has no narrator role, so automatic search must not invent
        # one, must not leave a dangling separator, and must not fetch a
        # book detail to look for one.
        self.assertEqual(r.name, '"The Martian" by A.Weir')
        self.assertNotIn('w/', r.name)
        detail_reqs = [req for req in HTTP.requests
                       if 'include=releases' in req[0]]
        self.assertEqual(detail_reqs, [])

    def test_search_compacts_multiple_narrators_with_count(self):
        hits = [{
            'id': 'aaaaaaaaaaaa',
            'title': 'The Martian',
            'people': [
                {'role': {'name': 'Author'},
                 'person': {'id': 'p1', 'name': 'Andy Weir'}},
                {'role': {'name': 'Narrator'},
                 'person': {'id': 'n1', 'name': 'Wil Wheaton'}},
                {'role': {'name': 'Narrator'},
                 'person': {'id': 'n2', 'name': 'R.C. Bray'}},
                {'role': {'name': 'Narrator'},
                 'person': {'id': 'n3', 'name': 'Scott Brick'}},
                {'role': {'name': 'Narrator'},
                 'person': {'id': 'n4', 'name': 'Kate Reading'}},
            ],
            'originalLanguage': 'English',
        }]
        appended = self._search(hits, manual=True)
        self.assertEqual(len(appended), 1)
        name = appended[0].name
        # The display never silently drops narrators: the names that fit
        # are followed by the explicit remaining count.
        self.assertIn('W.Wheaton', name)
        self.assertIn('R.C.Bray', name)
        self.assertIn('+1', name)

    def test_authors_only_hit_has_no_narrator_separator(self):
        install_transport(load_fixture('search_books_martian.json'))
        results = _Results()
        agent.AudiobookAlbum().search(
            results, album_media(), plex_shim.Locale.Language.English,
            False)
        self.assertEqual(len(results.appended), 1)
        self.assertEqual(results.appended[0].name,
                         '"The Martian" by A.Weir')

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
        self.assertEqual(body['filters'], {'person': 'Andy Weir', 'role': 'Author'})
        self.assertIn('seriesWithId', body['includeFields'])
        self.assertNotIn('releaseCount', body['includeFields'])

    def test_title_only_retry_after_empty_author_filter(self):
        install_transport([])
        hits = self._two_hit_response()[:1]

        def transport(url, method='GET', headers=None, data=None):
            if url == BASE + '/search' and method == 'POST':
                body = json.loads(data)
                return _HTTPRequest(200, api_body([] if 'filters' in body else hits))
            return _HTTPRequest(404, '')

        HTTP.transport = transport
        results = _Results()
        agent.AudiobookAlbum().search(
            results, album_media(artist='Wrong Local Artist'),
            plex_shim.Locale.Language.English, True)
        queries = [json.loads(req[3]) for req in HTTP.requests
                   if req[1] == 'POST']
        self.assertEqual(len(queries), 2)
        self.assertEqual(queries[0]['filters']['role'], 'Author')
        self.assertNotIn('filters', queries[1])
        self.assertEqual(results.appended[0].id, 'book.aaaaaaaaaaaa')

    @staticmethod
    def _hit_without_narrator(book_id, title):
        return {
            'id': book_id,
            'title': title,
            'people': [
                {'role': {'name': 'Author'},
                 'person': {'id': 'p1', 'name': 'Andy Weir'}},
            ],
            'originalLanguage': 'English',
        }

    @staticmethod
    def _release_with_narrator(release_id, narrator):
        return {
            'id': release_id,
            'people': [
                {'role': {'name': 'Narrator'},
                 'person': {'id': 'n-' + release_id, 'name': narrator}},
            ],
        }

    def test_manual_search_reads_single_release_narrator(self):
        # A manual title search hit has authors but no narrator credit in
        # the search payload; the agent must read the one visible release
        # to show the narrator, while keeping ID and score work-only.
        book_id = 'aaaaaaaaaaaa'
        detail_url = BASE + '/books/' + book_id + '?include=releases'
        detail = {
            'id': book_id,
            'title': 'The Martian',
            'releases': [
                {
                    'id': 'rel1',
                    'people': [
                        # A blank credit must not win: use the first
                        # nonblank Narrator name.
                        {'role': {'name': 'Narrator'},
                         'person': {'id': 'n0', 'name': '   '}},
                        {'role': {'name': 'Narrator'},
                         'person': {'id': 'n1', 'name': ' R.C. Bray '}},
                    ],
                },
            ],
        }
        install_transport([self._hit_without_narrator(book_id, 'The Martian')],
                          {detail_url: (200, api_body(detail))})
        results = _Results()
        agent.AudiobookAlbum().search(
            results, album_media(), plex_shim.Locale.Language.English,
            True)
        self.assertEqual(len(results.appended), 1)
        r = results.appended[0]
        self.assertEqual(r.id, 'book.' + book_id)
        self.assertEqual(r.score, 100)
        # 'R.C. Bray' -> 'R.C.Bray' via name_to_initials.
        self.assertEqual(r.name, '"The Martian" by A.Weir w/ R.C.Bray')
        detail_reqs = [req for req in HTTP.requests if req[0] == detail_url]
        self.assertEqual(len(detail_reqs), 1)

    def test_manual_release_row_keeps_complete_narrator_list(self):
        book_id = 'cccccccccccc'
        detail_url = BASE + '/books/' + book_id + '?include=releases'
        detail = {
            'id': book_id,
            'title': 'The Martian',
            'releases': [{
                'id': 'rel1',
                'people': [
                    {'role': {'name': 'Narrator'},
                     'person': {'id': 'n1', 'name': 'Wil Wheaton'}},
                    {'role': {'name': 'Narrator'},
                     'person': {'id': 'n2', 'name': 'R.C. Bray'}},
                ],
            }],
        }
        install_transport([self._hit_without_narrator(book_id, 'The Martian')],
                          {detail_url: (200, api_body(detail))})
        results = _Results()
        agent.AudiobookAlbum().search(
            results, album_media(), plex_shim.Locale.Language.English,
            True)
        self.assertEqual(len(results.appended), 1)
        name = results.appended[0].name
        self.assertIn('W.Wheaton', name)
        self.assertIn('R.C.Bray', name)

    def test_manual_release_row_count_stays_within_budget(self):
        book_id = 'dddddddddddd'
        detail_url = BASE + '/books/' + book_id + '?include=releases'
        long_title = 'A Very Long Audiobook Title That Exceeds Display Limits'
        long_author = 'Alexandria Bartholomew Christopher Davidson'
        detail = {
            'id': book_id,
            'title': long_title,
            'releases': [{
                'id': 'rel1',
                'people': [
                    {'role': {'name': 'Narrator'},
                     'person': {'id': 'n1',
                                'name': 'Alexandria Verylongsurname'}},
                    {'role': {'name': 'Narrator'},
                     'person': {'id': 'n2',
                                'name': 'Bartholomew Verylongsurname'}},
                    {'role': {'name': 'Narrator'},
                     'person': {'id': 'n3',
                                'name': 'Christopher Verylongsurname'}},
                ],
            }],
        }
        hit = {
            'id': book_id,
            'title': long_title,
            'people': [
                {'role': {'name': 'Author'},
                 'person': {'id': 'p1', 'name': long_author}},
            ],
            'originalLanguage': 'English',
        }
        install_transport([hit], {detail_url: (200, api_body(detail))})
        results = _Results()
        agent.AudiobookAlbum().search(
            results, album_media(album=long_title, artist=long_author),
            plex_shim.Locale.Language.English, True)
        self.assertEqual(len(results.appended), 1)
        name = results.appended[0].name
        # The count alone fits the remaining budget; it is not pushed past
        # the 60-character description limit.
        self.assertTrue(name.endswith('+3'), name)
        self.assertLessEqual(len(name), 60)

    def test_multi_release_work_row_hides_book_narrator(self):
        book_id = 'eeeeeeeeeeee'
        detail_url = BASE + '/books/' + book_id + '?include=releases'
        detail = {
            'id': book_id,
            'title': 'The Martian',
            'releases': [
                {'id': 'rel1', 'people': [
                    {'role': {'name': 'Narrator'},
                     'person': {'id': 'n1', 'name': 'Release One'}},
                ]},
                {'id': 'rel2', 'people': [
                    {'role': {'name': 'Narrator'},
                     'person': {'id': 'n2', 'name': 'Release Two'}},
                ]},
            ],
        }
        hit = {
            'id': book_id,
            'title': 'The Martian',
            'people': [
                {'role': {'name': 'Author'},
                 'person': {'id': 'p1', 'name': 'Andy Weir'}},
                {'role': {'name': 'Narrator'},
                 'person': {'id': 'n0', 'name': 'Work Credit'}},
            ],
            'originalLanguage': 'English',
        }
        install_transport([hit], {detail_url: (200, api_body(detail))})
        results = _Results()
        agent.AudiobookAlbum().search(
            results, album_media(), plex_shim.Locale.Language.English,
            True)
        self.assertEqual(len(results.appended), 3)
        self.assertNotIn('W.Credit', results.appended[0].name)
        release_names = [r.name for r in results.appended[1:]]
        self.assertTrue(any('R.One' in name for name in release_names))
        self.assertTrue(any('R.Two' in name for name in release_names))

    def test_multi_release_rows_keep_edition_discriminator(self):
        book_id = 'gggggggggggg'
        detail_url = BASE + '/books/' + book_id + '?include=releases'
        title = 'A Fairly Long Audiobook Title'
        narrators = [
            {'role': {'name': 'Narrator'},
             'person': {'id': 'n1', 'name': 'Wil Wheaton'}},
            {'role': {'name': 'Narrator'},
             'person': {'id': 'n2', 'name': 'R.C. Bray'}},
        ]
        detail = {
            'id': book_id,
            'title': title,
            'releases': [
                {'id': 'rel1', 'disambiguation': 'Unabridged 2011',
                 'people': narrators},
                {'id': 'rel2', 'disambiguation': 'Unabridged 2018',
                 'people': narrators},
            ],
        }
        hit = {
            'id': book_id,
            'title': title,
            'people': [
                {'role': {'name': 'Author'},
                 'person': {'id': 'p1', 'name': 'A.Author'}},
            ],
            'originalLanguage': 'English',
        }
        install_transport([hit], {detail_url: (200, api_body(detail))})
        results = _Results()
        agent.AudiobookAlbum().search(
            results, album_media(album=title, artist='A.Author'),
            plex_shim.Locale.Language.English, True)
        by_id = dict((r.id, r) for r in results.appended)
        one = by_id['book.' + book_id + '.release.rel1']
        two = by_id['book.' + book_id + '.release.rel2']
        self.assertIn('[Unabridged 2011]', one.name)
        self.assertIn('[Unabridged 2018]', two.name)
        self.assertNotEqual(one.name, two.name)
        self.assertLessEqual(len(one.name), 60)
        self.assertLessEqual(len(two.name), 60)

    def test_plain_search_hit_keeps_book_narrator(self):
        hit = {
            'id': 'ffffffffffff',
            'title': 'The Martian',
            'people': [
                {'role': {'name': 'Author'},
                 'person': {'id': 'p1', 'name': 'Andy Weir'}},
                {'role': {'name': 'Narrator'},
                 'person': {'id': 'n0', 'name': 'Work Credit'}},
            ],
            'originalLanguage': 'English',
        }
        install_transport([hit])
        results = _Results()
        agent.AudiobookAlbum().search(
            results, album_media(), plex_shim.Locale.Language.English,
            False)
        self.assertEqual(len(results.appended), 1)
        self.assertIn('W.Credit', results.appended[0].name)

    def test_manual_multiple_recordings_keep_work_choice_and_rank_editions(self):
        book_id = 'bbbbbbbbbbbb'
        detail_url = BASE + '/books/' + book_id + '?include=releases'
        long = self._release_with_narrator('rel1', 'R.C. Bray')
        long.update(duration='10:00:00', releaseDate='2013-03-22T00:00:00Z',
                    language={'name': 'English'},
                    images=[{'url': 'https://example.invalid/untrusted'}])
        near = self._release_with_narrator('rel2', 'Wil Wheaton')
        near.update(duration='09:00:00', releaseDate='2020-01-01T00:00:00Z',
                    language={'name': 'English'},
                    images=[{'url': 'https://cdn.audiobookdb.org/release-cover'}])
        detail = {'id': book_id, 'releases': [long, near]}
        install_transport([self._hit_without_narrator(book_id, 'The Martian')],
                          {detail_url: (200, api_body(detail))})
        track = plex_track('101', 1, 'The Martian', 32400000, '/book.m4b')
        tree = type('Tree', (), {'tracks': {'1': track}, 'children': [track]})()
        results = _Results()
        agent.AudiobookAlbum().search(
            results, album_media(tree=tree), plex_shim.Locale.Language.English,
            True)
        work, closer, other = results.appended
        self.assertEqual(work.id, 'book.' + book_id)
        self.assertEqual(work.score, 100)
        self.assertEqual(work.name, '"The Martian" by A.Weir')
        self.assertIsNone(work.year)
        self.assertEqual(closer.id, work.id + '.release.rel2')
        self.assertGreater(closer.score, other.score)
        self.assertIn('W.Wheaton', closer.name)
        self.assertEqual(closer.year, 2020)
        self.assertEqual(closer.thumb,
                         'https://cdn.audiobookdb.org/release-cover/small.jpg')
        self.assertEqual(other.id, work.id + '.release.rel1')
        self.assertIsNone(other.thumb)
        detail_reqs = [req for req in HTTP.requests if req[0] == detail_url]
        self.assertEqual(len(detail_reqs), 1)

    def test_manual_series_hint_lifts_eligible_hit_into_a_gap(self):
        # An eligible hit in a score gap earns +1; a hit with no series
        # evidence stays at its base score.
        hits = [
            dict(self._hit_without_narrator('aaaaaaaaaaaa', 'Saga One'),
                 seriesWithId=[{'title': 'Unrelated Series'}]),
            dict(self._hit_without_narrator('bbbbbbbbbbbb', 'Saga One XY'),
                 seriesWithId=[{'title': 'Unrelated Series'}]),
        ]
        install_transport(hits)
        results = _Results()
        agent.AudiobookAlbum().search(
            results, album_media(album='Saga One'),
            plex_shim.Locale.Language.English, True)
        scores = {r.id: r.score for r in results.appended}
        # Base scores: 100 (perfect title) and 95 (two edits, index 1).
        self.assertEqual(scores['book.aaaaaaaaaaaa'], 100)
        self.assertEqual(scores['book.bbbbbbbbbbbb'], 95)

        # The lower hit's series name now matches the album name: the
        # gap at 96 is empty, so the hint lifts it 95 -> 96.
        hits[1]['seriesWithId'] = [{'title': 'Saga One'}]
        install_transport(hits)
        results = _Results()
        agent.AudiobookAlbum().search(
            results, album_media(album='Saga One'),
            plex_shim.Locale.Language.English, True)
        scores = {r.id: r.score for r in results.appended}
        self.assertEqual(scores['book.aaaaaaaaaaaa'], 100)
        self.assertEqual(scores['book.bbbbbbbbbbbb'], 96)

    def test_manual_series_hint_never_changes_title_ranking(self):
        # A worse-title hit at the same base score must not overtake a
        # better-title hit, even when only the worse hit is eligible.
        # A real base-score tie: the eligible one-edit hit at index 0
        # (100 - 2 = 98) and the exact hit at index 2 (100 - 0 - 2 = 98)
        # both score 98. The exact hit has the smaller title deduction,
        # so the tie-break withholds the boost. An unconditional bonus
        # would lift the eligible hit to 99 and let it overtake.
        hits = [
            dict(self._hit_without_narrator('aaaaaaaaaaaa', 'Saga One X'),
                 seriesWithId=[{'title': 'Saga One'}]),
            dict(self._hit_without_narrator('cccccccccccc', 'Saga One XYZ'),
                 seriesWithId=[{'title': 'Unrelated Series'}]),
            dict(self._hit_without_narrator('bbbbbbbbbbbb', 'Saga One'),
                 seriesWithId=[{'title': 'Unrelated Series'}]),
        ]
        install_transport(hits)
        results = _Results()
        agent.AudiobookAlbum().search(
            results, album_media(album='Saga One'),
            plex_shim.Locale.Language.English, True)
        scores = {r.id: r.score for r in results.appended}
        self.assertEqual(scores['book.aaaaaaaaaaaa'], 98)
        self.assertEqual(scores['book.bbbbbbbbbbbb'], 98)
        # The worse-title (eligible) hit stays at or below the exact hit.
        self.assertLessEqual(scores['book.aaaaaaaaaaaa'],
                             scores['book.bbbbbbbbbbbb'])

    def test_manual_series_hint_capped_at_100(self):
        # A perfect-title hit below 100 only because of index/author
        # headroom can use the hint; a base-100 hit cannot exceed 100.
        hits = [
            dict(self._hit_without_narrator('aaaaaaaaaaaa', 'Saga One'),
                 seriesWithId=[{'title': 'Saga One'}]),
        ]
        install_transport(hits)
        results = _Results()
        agent.AudiobookAlbum().search(
            results, album_media(album='Saga One'),
            plex_shim.Locale.Language.English, True)
        self.assertEqual(len(results.appended), 1)
        # Base 100 (title 0, author 0, index 0): the cap blocks the
        # boost, so the score stays exactly 100.
        self.assertEqual(results.appended[0].score, 100)

    def test_auto_search_ignores_series_hint(self):
        # Automatic matching keeps byte-identical scores: no hint pass.
        # A one-edit title scores 98 (one edit = 2 points). If the auto
        # path wrongly ran the hint pass, the base-98 eligible hit would
        # be boosted to 99.
        hits = [
            dict(self._hit_without_narrator('aaaaaaaaaaaa', 'Saga Ones'),
                 seriesWithId=[{'title': 'Saga One'}]),
        ]
        install_transport(hits)
        results = _Results()
        agent.AudiobookAlbum().search(
            results, album_media(album='Saga One'),
            plex_shim.Locale.Language.English, False)
        self.assertEqual(len(results.appended), 1)
        self.assertEqual(results.appended[0].score, 98)

    def test_manual_series_hint_uses_base_snapshot(self):
        # Three-hit base staircase (S, S-1, S-2), all eligible: only the
        # top hit may earn the point. A sequential implementation that
        # reads already-boosted scores would let the lower hits cascade
        # into the freed slots.
        hits = [
            dict(self._hit_without_narrator('aaaaaaaaaaaa', 'Saga One'),
                 seriesWithId=[{'title': 'Saga One'}]),
            dict(self._hit_without_narrator('bbbbbbbbbbbb', 'Saga One'),
                 seriesWithId=[{'title': 'Saga One'}]),
            dict(self._hit_without_narrator('cccccccccccc', 'Saga One'),
                 seriesWithId=[{'title': 'Saga One'}]),
        ]
        install_transport(hits)
        results = _Results()
        agent.AudiobookAlbum().search(
            results, album_media(album='Saga One', artist='Andy Wair'),
            plex_shim.Locale.Language.English, True)
        scores = {r.id: r.score for r in results.appended}
        # One-letter artist misspelling costs 10; bases are 90, 89, 88.
        # The top hits 90 -> 91; the others stay (occupied base above).
        self.assertEqual(scores['book.aaaaaaaaaaaa'], 91)
        self.assertEqual(scores['book.bbbbbbbbbbbb'], 89)
        self.assertEqual(scores['book.cccccccccccc'], 88)

    def test_authorized_search_failure_does_not_trigger_unfiltered_retry(self):
        install_transport(None, {BASE + '/search': (401, '')})
        results = _Results()
        agent.AudiobookAlbum().search(
            results, album_media(), plex_shim.Locale.Language.English, True)
        self.assertEqual(results.appended, [])
        search_reqs = [req for req in HTTP.requests
                       if req[1] == 'POST' and req[0] == BASE + '/search']
        self.assertTrue(search_reqs)
        for req in search_reqs:
            self.assertIn('filters', json.loads(req[3]))


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
            album_media(album='The Martian B0AAAAAAAA'),
            plex_shim.Locale.Language.English,
            True)
        # B0AAAAAAAA is a valid ten-character ASIN that 404s;
        # 'The Martian' (3+ chars) triggers a search,
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
        metadata = self._run_update('B0AAAAAAAA_us')
        self.assertEqual(metadata.id, 'B0AAAAAAAA_us')
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

    def test_empty_description_keeps_summary_and_completes_update(self):
        """An unavailable description is non-destructive on a forced update."""
        mapping = default_mapping()
        book = load_fixture(BOOK_DETAIL)
        book['description'] = ''
        mapping[BASE + '/books/WQQDcMBQ3qUT'] = (200, api_body(book))
        install_transport(None, mapping=mapping)
        metadata = FakeMetadata('book.WQQDcMBQ3qUT.release.dPL9fC7YnK8X')
        metadata.summary = 'Existing summary'
        agent.AudiobookAlbum().update(
            metadata, FakeMedia(title='The Martian'),
            plex_shim.Locale.Language.English, True)
        # The summary survives; every other setter still ran.
        self.assertEqual(metadata.summary, 'Existing summary')
        self.assertEqual(metadata.title, 'The Martian')
        self.assertEqual(metadata.studio, 'Podium Publishing')
        self.assertEqual(metadata.styles, {'R.C. Bray'})
        self.assertEqual(
            metadata.id, 'book.WQQDcMBQ3qUT.release.dPL9fC7YnK8X')

    def test_null_description_keeps_summary_and_completes_update(self):
        """A null description (API omitted the key) is non-destructive too."""
        mapping = default_mapping()
        book = load_fixture(BOOK_DETAIL)
        book['description'] = None
        mapping[BASE + '/books/WQQDcMBQ3qUT'] = (200, api_body(book))
        install_transport(None, mapping=mapping)
        metadata = FakeMetadata('book.WQQDcMBQ3qUT.release.dPL9fC7YnK8X')
        metadata.summary = 'Existing summary'
        agent.AudiobookAlbum().update(
            metadata, FakeMedia(title='The Martian'),
            plex_shim.Locale.Language.English, True)
        self.assertEqual(metadata.summary, 'Existing summary')
        self.assertEqual(metadata.title, 'The Martian')
        self.assertEqual(
            metadata.id, 'book.WQQDcMBQ3qUT.release.dPL9fC7YnK8X')

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

    def test_refresh_names_matching_tracks_and_preserves_custom_metadata(self):
        cases = [
            (True, 20000, False, 'Launch'),
            (False, 20000, False, 'Chapter 1'),
            (True, 30000, False, 'Chapter 1'),
            (True, 20000, True, 'Chapter 1'),
        ]
        for enabled, second_duration, single_file, expected_title in cases:
            mapping = default_mapping()
            book = load_fixture(BOOK_DETAIL)
            book['series'] = [{'series': {'title': 'Mars Stories'}}]
            release = load_fixture(RELEASE_DETAIL)
            release['chapterDetail'] = {'chapters': [
                {'ordinal': 1, 'startOffsetMs': 0, 'lengthMs': 10000, 'title': 'Launch'},
                {'ordinal': 2, 'startOffsetMs': 10000, 'lengthMs': 20000, 'title': 'Landing'},
            ]}
            mapping[BASE + '/books/WQQDcMBQ3qUT'] = (200, api_body(book))
            mapping[BASE + '/releases/dPL9fC7YnK8X'] = (200, api_body(release))
            install_transport(None, mapping=mapping)
            Prefs['use_chapter_titles'] = enabled
            Prefs['store_series_as_collection'] = enabled
            first = plex_track('201', 1, 'Chapter 1', 10000, '/one.m4b')
            second = plex_track('202', 1, 'Custom title', second_duration,
                                '/one.m4b' if single_file else '/two.mp3', disc=2)
            metadata = FakeMetadata('book.WQQDcMBQ3qUT.release.dPL9fC7YnK8X')
            metadata.tracks = {'201': first, '202': second}
            metadata.collections = {'Manual collection'}
            agent.AudiobookAlbum().update(
                metadata, album_media(children=[second, first]),
                plex_shim.Locale.Language.English, True)
            self.assertEqual(metadata.tracks['201'].title, expected_title)
            self.assertEqual(metadata.tracks['202'].title, 'Custom title')
            self.assertIn('Manual collection', metadata.collections)
            self.assertEqual('Mars Stories' in metadata.collections, enabled)
            self.assertIn('Series: Mars Stories', metadata.moods)
        Prefs['use_chapter_titles'] = False
        Prefs['store_series_as_collection'] = False

    def test_album_search_update_round_trip(self):
        # Search the book (the fixture hit carries no matched release,
        # so the ID is work-only).
        install_transport(load_fixture('search_books_martian.json'))
        results = _Results()
        agent.AudiobookAlbum().search(
            results, album_media(), plex_shim.Locale.Language.English,
            True)
        self.assertEqual(len(results.appended), 1)
        self.assertEqual(results.appended[0].id, 'book.WQQDcMBQ3qUT')

        # Update through the native ID (round trip): only detail
        # endpoints are hit, no ASIN resolve or search.
        install_transport(None)
        metadata = FakeMetadata('book.WQQDcMBQ3qUT')
        agent.AudiobookAlbum().update(
            metadata, album_media(), plex_shim.Locale.Language.English,
            False)
        self.assertEqual(metadata.title, 'The Martian')
        self.assertEqual(metadata.id, 'book.WQQDcMBQ3qUT')
        urls = [req[0] for req in HTTP.requests]
        for url in urls:
            self.assertNotIn('/audiobooks/external/', url)
            self.assertNotIn('/search', url)
            self.assertNotIn('/releases/', url)
        self.assertIn(BASE + '/books/WQQDcMBQ3qUT', urls)


class TestArtistSearchAndUpdate(unittest.TestCase):
    """New-behavior check 4: person migration + search round trip."""

    def test_non_latin_author_name_reaches_search(self):
        name = u'\u6751\u4e0a\u6625\u6a39'
        install_transport([{'id': 'aaaaaaaaaaaa', 'name': name}])
        results = _Results()
        agent.AudiobookArtist().search(results, artist_media(artist=name),
                                       'ja', False)
        self.assertEqual(results.appended[0].name, name)
        self.assertEqual(json.loads(HTTP.requests[0][3])['q'], name)
    def test_same_name_people_stay_distinct_with_disambiguation(self):
        hits = [
            {'id': 'p1', 'name': 'Alex Smith',
             'disambiguation': 'Narrator'},
            {'id': 'p2', 'name': 'Alex Smith',
             'disambiguation': 'Author'},
        ]
        install_transport(hits)
        results = _Results()
        agent.AudiobookArtist().search(
            results, artist_media(artist='Alex Smith'),
            plex_shim.Locale.Language.English, True)
        self.assertEqual([r.id for r in results.appended],
                         ['person.p1', 'person.p2'])
        self.assertEqual(results.appended[0].name,
                         'Alex Smith (Narrator)')
        self.assertEqual(results.appended[1].name,
                         'Alex Smith (Author)')

    def test_person_without_disambiguation_shows_bare_name(self):
        install_transport([{'id': 'p1', 'name': 'Alex Smith'}])
        results = _Results()
        agent.AudiobookArtist().search(
            results, artist_media(artist='Alex Smith'),
            plex_shim.Locale.Language.English, True)
        self.assertEqual(results.appended[0].name, 'Alex Smith')

    def test_empty_artist_search_noop(self):
        # None and '' artist values short-circuit: the search completes
        # without exception, appends nothing, and makes no API request.
        for artist in (None, ''):
            install_transport(load_fixture('search_people_andy_weir.json'))
            results = _Results()
            agent.AudiobookArtist().search(
                results, artist_media(artist=artist),
                plex_shim.Locale.Language.English, False)
            self.assertEqual(results.appended, [])
            self.assertEqual(HTTP.requests, [])

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
        metadata = FakeMetadata('B0AAAAAAAA')
        agent.AudiobookArtist().update(
            metadata, FakeMedia(title='Nobody'),
            plex_shim.Locale.Language.English, False)
        self.assertEqual(metadata.id, 'B0AAAAAAAA')
        self.assertIsNone(metadata.title)
        self.assertIsNone(metadata.summary)

    def test_empty_description_keeps_summary_and_completes_update(self):
        """An unavailable bio is non-destructive on a forced update."""
        mapping = default_mapping()
        person = load_fixture(PERSON_DETAIL)
        person['description'] = ''
        mapping[BASE + '/people/ypMPwXzWXaiX'] = (200, api_body(person))
        install_transport(None, mapping=mapping)
        metadata = FakeMetadata('person.ypMPwXzWXaiX')
        metadata.summary = 'Existing bio'
        agent.AudiobookArtist().update(
            metadata, FakeMedia(title='Andy Weir'),
            plex_shim.Locale.Language.English, True)
        # The bio survives; the rest of the update still ran.
        self.assertEqual(metadata.summary, 'Existing bio')
        self.assertEqual(metadata.title, 'Andy Weir')
        self.assertIn('Fantasy', metadata.genres)
        self.assertEqual(metadata.id, 'person.ypMPwXzWXaiX')

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
