# -*- coding: utf-8 -*-
"""Tests for Contents/Code/search_tools.py against AudiobookDB fixtures."""

import os
import sys
import json
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import plex_shim  # noqa: F401,E402  (framework fakes must load first)

from plex_shim import Prefs, _Results, _HTTPRequest  # noqa: E402

import api_client  # noqa: E402
from search_tools import (  # noqa: E402
    SearchTool, AlbumSearchTool, ArtistSearchTool, ScoreTool,
)

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


def install_transport(mapping, default=''):
    """Map URL -> (status, body); records requests on HTTP.requests."""
    def transport(url, method='GET', headers=None, data=None):
        if url in mapping:
            status, body = mapping[url]
        else:
            status, body = 404, default
        return _HTTPRequest(status, body)
    plex_shim.HTTP.Reset()
    plex_shim.HTTP.Headers = {}
    plex_shim.HTTP.transport = transport
    Prefs['logging_level'] = 'ERROR'
    return transport


class FakeMedia(object):
    def __init__(self, **kw):
        self.filename = None
        self.album = None
        self.artist = None
        self.title = None
        self.name = None
        self.parent_metadata = type('PM', (), {'id': 'ASIN_parent'})()
        for key, val in kw.items():
            setattr(self, key, val)


def make(content_type, media=None, manual=False):
    Prefs['logging_level'] = 'INFO'
    return SearchTool(
        content_type, plex_shim.Locale.Language.English, manual,
        media if media is not None else FakeMedia(), Prefs, _Results())


def make_album(media=None, manual=False):
    Prefs['logging_level'] = 'INFO'
    return AlbumSearchTool(
        'books', plex_shim.Locale.Language.English, manual,
        media if media is not None else FakeMedia(), Prefs, _Results())


def make_artist(media=None, manual=False):
    Prefs['logging_level'] = 'INFO'
    return ArtistSearchTool(
        'authors', plex_shim.Locale.Language.English, manual,
        media if media is not None else FakeMedia(), Prefs, _Results())


class FakeScoreHelper(object):
    def __init__(self, media=None, lang=None, manual=False):
        self.media = media
        self.lang = lang if lang is not None else plex_shim.Locale.Language.English
        self.manual = manual


class TestCheckForAsinBooks(unittest.TestCase):
    """Quick-match book appends (legacy ASIN and native IDs)."""

    def test_books_from_filename_appends_score_100(self):
        install_transport({
            BASE + '/audiobooks/external/audible/B00B5HZGUG':
                (200, api_body(load_fixture(
                    'book_external_resolve_B00B5HZGUG.json'))),
        })
        tool = make('books', FakeMedia(filename='the%20martian%20B00B5HZGUG'))
        self.assertTrue(tool.check_for_asin())
        self.assertEqual(len(tool.results.appended), 1)
        r = tool.results.appended[0]
        self.assertEqual(r.id, 'book.WQQDcMBQ3qUT.release.dPL9fC7YnK8X')
        self.assertEqual(r.name, 'The Martian')
        self.assertEqual(r.score, 100)
        self.assertEqual(r.year, 2011)

    def test_books_from_manual_album(self):
        install_transport({
            BASE + '/audiobooks/external/audible/B00B5HZGUG':
                (200, api_body(load_fixture(
                    'book_external_resolve_B00B5HZGUG.json'))),
        })
        tool = make('books', FakeMedia(album='The Martian B00B5HZGUG'))
        self.assertTrue(tool.check_for_asin())
        self.assertEqual(tool.results.appended[0].id,
                         'book.WQQDcMBQ3qUT.release.dPL9fC7YnK8X')

    def test_native_book_id(self):
        install_transport({
            BASE + '/books/WQQDcMBQ3qUT': (
                200, api_body(load_fixture('book_detail_WQQDcMBQ3qUT.json'))),
        })
        tool = make('books', FakeMedia(album='book.WQQDcMBQ3qUT'))
        self.assertTrue(tool.check_for_asin())
        r = tool.results.appended[0]
        self.assertEqual(r.id, 'book.WQQDcMBQ3qUT')
        self.assertEqual(r.name, 'The Martian')
        self.assertEqual(r.year, 2011)

    def test_native_book_release_id_pair(self):
        install_transport({
            BASE + '/books/WQQDcMBQ3qUT': (
                200, api_body(load_fixture('book_detail_WQQDcMBQ3qUT.json'))),
            BASE + '/releases/dPL9fC7YnK8X': (
                200, api_body(load_fixture('release_detail_dPL9fC7YnK8X.json'))),
        })
        tool = make('books',
                    FakeMedia(album='book.WQQDcMBQ3qUT.release.dPL9fC7YnK8X'))
        self.assertTrue(tool.check_for_asin())
        self.assertEqual(tool.results.appended[0].id,
                         'book.WQQDcMBQ3qUT.release.dPL9fC7YnK8X')

    def test_release_mismatch_rejected(self):
        other_release = load_fixture('release_detail_dPL9fC7YnK8X.json')
        other_release['book'] = {'id': 'other'}
        install_transport({
            BASE + '/books/WQQDcMBQ3qUT': (
                200, api_body(load_fixture('book_detail_WQQDcMBQ3qUT.json'))),
            BASE + '/releases/dPL9fC7YnK8X': (200, api_body(other_release)),
        })
        tool = make('books',
                    FakeMedia(album='book.WQQDcMBQ3qUT.release.dPL9fC7YnK8X'))
        self.assertFalse(tool.check_for_asin())
        self.assertEqual(tool.results.appended, [])

    def test_book_404_returns_false(self):
        install_transport({})
        tool = make('books', FakeMedia(album='book.WQQDcMBQ3qUT'))
        self.assertFalse(tool.check_for_asin())
        self.assertEqual(tool.results.appended, [])

    def test_asin_404_returns_false(self):
        install_transport({})
        tool = make('books', FakeMedia(album='Nope B000000000'))
        self.assertFalse(tool.check_for_asin())
        self.assertEqual(tool.results.appended, [])

    def test_manual_query_beats_filename_asin(self):
        # A manual (Fix Match) query takes precedence over the scanner's
        # filename hint: the filename ASIN is neither resolved nor
        # quick-matched, and no API request is made for it.
        install_transport({
            BASE + '/audiobooks/external/audible/B00B5HZGUG':
                (200, api_body(load_fixture(
                    'book_external_resolve_B00B5HZGUG.json'))),
        })
        tool = make('books', FakeMedia(
            filename='the%20martian%20B00B5HZGUG', album='The Martian'),
            manual=True)
        self.assertFalse(tool.check_for_asin())
        self.assertEqual(tool.results.appended, [])
        # The manual query 'The Martian' carries no ID: nothing requested.
        self.assertEqual(HTTP.requests, [])

    def test_no_id_returns_false(self):
        install_transport({})
        tool = make('books', FakeMedia(album='The Martian'))
        self.assertFalse(tool.check_for_asin())
        self.assertEqual(tool.results.appended, [])
        tool2 = make('books', FakeMedia())
        self.assertFalse(tool2.check_for_asin())


class TestCheckForAsinPeople(unittest.TestCase):
    """Quick-match person appends (legacy ASIN and native IDs)."""

    def test_artist_asin_manual_appends_person(self):
        install_transport({
            BASE + '/people?external=Audible%3AB00G0WYW92&take=2': (
                200, api_body(
                    load_fixture('person_external_resolve_B00G0WYW92.json'))),
            BASE + '/people/ypMPwXzWXaiX': (
                200, api_body(load_fixture('person_detail_ypMPwXzWXaiX.json'))),
        })
        tool = make('authors', FakeMedia(artist='Andy Weir B00G0WYW92'),
                    manual=True)
        self.assertTrue(tool.check_for_asin())
        self.assertEqual(len(tool.results.appended), 1)
        r = tool.results.appended[0]
        self.assertEqual(r.id, 'person.ypMPwXzWXaiX')
        self.assertEqual(r.name, 'Andy Weir')
        self.assertEqual(r.score, 100)

    def test_artist_asin_not_manual_skips(self):
        install_transport({
            BASE + '/people?external=Audible%3AB00G0WYW92&take=2': (
                200, api_body(
                    load_fixture('person_external_resolve_B00G0WYW92.json'))),
            BASE + '/people/ypMPwXzWXaiX': (
                200, api_body(load_fixture('person_detail_ypMPwXzWXaiX.json'))),
        })
        tool = make('authors', FakeMedia(artist='Andy Weir B00G0WYW92'))
        self.assertFalse(tool.check_for_asin())
        self.assertEqual(tool.results.appended, [])

    def test_artist_404_returns_false(self):
        install_transport({})
        tool = make('authors', FakeMedia(artist='Nobody B000000000'),
                    manual=True)
        self.assertFalse(tool.check_for_asin())

    def test_multi_hit_only_confirmed_detail_appended(self):
        # Two candidates share the ASIN in the resolve listing; only the
        # detail that confirms the queried Audible ASIN is appended.
        hits = load_fixture('person_external_resolve_B00G0WYW92.json')
        hit2 = dict(hits[0])
        hit2['id'] = 'otherPerson123'
        hit2['name'] = 'Other Person'
        # The unconfirmed detail: no Audible external entry.
        unconfirmed = load_fixture('person_detail_ypMPwXzWXaiX.json')
        del unconfirmed['external']
        install_transport({
            BASE + '/people?external=Audible%3AB00G0WYW92&take=2': (
                200, api_body(hits + [hit2])),
            BASE + '/people/ypMPwXzWXaiX': (
                200, api_body(load_fixture('person_detail_ypMPwXzWXaiX.json'))),
            BASE + '/people/otherPerson123': (
                200, api_body(unconfirmed)),
        })
        tool = make('authors', FakeMedia(artist='Andy Weir B00G0WYW92'),
                    manual=True)
        self.assertTrue(tool.check_for_asin())
        self.assertEqual(len(tool.results.appended), 1)
        r = tool.results.appended[0]
        self.assertEqual(r.id, 'person.ypMPwXzWXaiX')
        self.assertEqual(r.name, 'Andy Weir')

    def test_native_person_id(self):
        install_transport({
            BASE + '/people/ypMPwXzWXaiX': (
                200, api_body(load_fixture('person_detail_ypMPwXzWXaiX.json'))),
        })
        tool = make('authors', FakeMedia(artist='person.ypMPwXzWXaiX'),
                    manual=True)
        self.assertTrue(tool.check_for_asin())
        self.assertEqual(tool.results.appended[0].id, 'person.ypMPwXzWXaiX')

    def test_native_person_id_404(self):
        install_transport({})
        tool = make('authors', FakeMedia(artist='person.ypMPwXzWXaiX'),
                    manual=True)
        self.assertFalse(tool.check_for_asin())

    def test_book_id_rejected_for_authors(self):
        install_transport({})
        tool = make('authors', FakeMedia(artist='book.WQQDcMBQ3qUT'),
                    manual=True)
        self.assertFalse(tool.check_for_asin())

    def test_person_id_rejected_for_books(self):
        install_transport({})
        tool = make('books', FakeMedia(album='person.ypMPwXzWXaiX'))
        self.assertFalse(tool.check_for_asin())


class TestSearchToolHelpers(unittest.TestCase):
    def test_clear_contributor_text(self):
        tool = make('books', FakeMedia())
        self.assertEqual(tool.clear_contributor_text('A - B'), 'A')
        self.assertEqual(tool.clear_contributor_text('Plain'), 'Plain')

    def test_search_asin(self):
        tool = make('books', FakeMedia())
        self.assertEqual(tool.search_asin('has B00B5HZGUG in it').group(0),
                         'B00B5HZGUG')
        self.assertIsNone(tool.search_asin('no asin here'))
        self.assertIsNone(tool.search_asin(None))

    def test_validate_author_name_clears_bad(self):
        tool = make('books', FakeMedia(artist='[Unknown Artist]'))
        tool.validate_author_name()
        self.assertIsNone(tool.media.artist)

    def test_validate_author_name_keeps_good(self):
        tool = make('books', FakeMedia(artist='Andy Weir'))
        tool.validate_author_name()
        self.assertEqual(tool.media.artist, 'Andy Weir')

    def test_validate_author_name_authors_sets_primary(self):
        tool = make_artist(FakeMedia(title='Some Title'))
        tool.validate_author_name()
        self.assertEqual(tool.media.artist, 'Some Title')


class TestAlbumSearchToolBody(unittest.TestCase):
    def test_body_with_artist(self):
        tool = make_album(FakeMedia(album='The Martian', artist='Andy Weir'))
        body = tool.build_search_body()
        self.assertEqual(body['type'], 'books')
        self.assertEqual(body['q'], 'The Martian')
        self.assertEqual(body['filters'], {'person': 'Andy Weir'})

    def test_body_without_artist_no_filters(self):
        tool = make_album(FakeMedia(album='The Martian'))
        body = tool.build_search_body()
        self.assertEqual(body, {'q': 'The Martian', 'type': 'books'})

    def test_body_too_short_returns_none(self):
        tool = make_album(FakeMedia(album='ab'))
        self.assertIsNone(tool.build_search_body())

    def test_body_nothing_to_search_returns_none(self):
        tool = make_album(FakeMedia())
        self.assertIsNone(tool.build_search_body())

    def test_body_filters_only_when_title_short(self):
        # Title below the 3-char floor, but an artist is present: the
        # body carries the person filter without a 'q'.
        tool = make_album(FakeMedia(album='ab', artist='Andy Weir'))
        body = tool.build_search_body()
        self.assertEqual(body, {'type': 'books',
                                'filters': {'person': 'Andy Weir'}})


class TestNameToInitials(unittest.TestCase):
    def _t(self, name):
        return make_album(FakeMedia()).name_to_initials(name)

    def test_three_part_name(self):
        self.assertEqual(self._t('Arthur Conan Doyle'), 'A.C.Doyle')

    def test_initials_only_names(self):
        self.assertEqual(self._t('J K Rowling'), 'J.K.Rowling')

    def test_dotted_initials(self):
        self.assertEqual(self._t('J. R. R. Tolkien'), 'J.R.R.Tolkien')

    def test_single_name_unchanged(self):
        self.assertEqual(self._t('Doyle'), 'Doyle')

    def test_quotes_stripped(self):
        self.assertEqual(self._t('"Andy Weir"'), 'A.Weir')


class TestNormalizeName(unittest.TestCase):
    def test_strips_brackets_chars_and_words(self):
        tool = make_album(FakeMedia(album='The Martian (Unabridged) [2013]'))
        self.assertEqual(tool.normalize_name(), 'The Martian')
        self.assertEqual(tool.normalizedName, 'The Martian')

    def test_uses_title_when_album_missing(self):
        tool = make_album(FakeMedia(title='Fallout [2017] audiobook'))
        self.assertEqual(tool.normalize_name(), 'Fallout')

    def test_diacritics(self):
        tool = make_album(FakeMedia(album=u'Caf\u00e9 Stories'))
        self.assertEqual(tool.normalize_name(), 'Cafe Stories')


class TestAlbumParseApiResponse(unittest.TestCase):
    def test_fixture_hits(self):
        tool = make_album(FakeMedia())
        results = tool.parse_api_response(load_fixture('search_books_martian.json'))
        # The decoy 'A Sidekick' hit comes first; WQQDcMBQ3qUT is index 1.
        self.assertEqual(len(results), 10)
        self.assertEqual(results[1]['book_id'], 'book.WQQDcMBQ3qUT')
        self.assertEqual(results[1]['title'], 'The Martian')
        self.assertEqual(results[1]['author'], [{'name': 'Andy Weir'}])
        self.assertEqual(results[1]['narrator'], [])
        self.assertIsNone(results[1]['date'])
        self.assertEqual(results[1]['language'], 'English')
        self.assertIsNone(results[1]['subtitle'])

    def test_missing_required_keys_rejected(self):
        tool = make_album(FakeMedia())
        self.assertEqual(
            tool.parse_api_response([
                {'id': 'abc', 'title': 'Nope'},
                {'title': 'No ID'},
                {'id': 'abc', 'people': []},
            ]), [])

    def test_non_dict_items_rejected(self):
        tool = make_album(FakeMedia())
        self.assertEqual(tool.parse_api_response(['nope', None, 5]), [])

    def test_no_narrator_role(self):
        tool = make_album(FakeMedia())
        results = tool.parse_api_response([
            {'id': 'abc', 'title': 'T', 'people': [
                {'role': {'name': 'Narrator'},
                 'person': {'id': 'p1', 'name': 'N N'}}]},
        ])
        self.assertEqual(results[0]['narrator'], [{'name': 'N N'}])

    def test_series_with_id_preserved(self):
        tool = make_album(FakeMedia())
        results = tool.parse_api_response(
            load_fixture('search_books_ordering_gaps.json'))
        series = results[0]['seriesWithId']
        self.assertEqual(len(series), 1)
        self.assertEqual(series[0]['title'], 'Swing Shift')
        self.assertEqual(series[0]['ordinal'], '1')
        self.assertEqual(
            series[0]['position']['spans'], [{'start': 1, 'end': 1}])

    def test_missing_series_defaults_empty(self):
        tool = make_album(FakeMedia())
        results = tool.parse_api_response([
            {'id': 'abc', 'title': 'T', 'people': []},
        ])
        self.assertEqual(results[0]['seriesWithId'], [])

    def test_non_dict_series_entries_skipped(self):
        tool = make_album(FakeMedia())
        results = tool.parse_api_response([
            {'id': 'abc', 'title': 'T', 'people': [],
             'seriesWithId': [None, 'nope', {'title': 'Series'}]},
        ])
        self.assertEqual(results[0]['seriesWithId'],
                         [{'title': 'Series',
                           'ordinal': None,
                           'position': None}])


class TestPreSearchLogging(unittest.TestCase):
    def test_album_missing_uses_track_title(self):
        tool = make_album(FakeMedia(title='Track One'))
        self.assertTrue(tool.pre_search_logging())
        self.assertEqual(tool.media.album, 'Track One')

    def test_album_missing_no_title_returns_none(self):
        tool = make_album(FakeMedia())
        self.assertIsNone(tool.pre_search_logging())

    def test_unknown_album_returns_none(self):
        tool = make_album(FakeMedia(album='[Unknown Album]'))
        self.assertIsNone(tool.pre_search_logging())

    def test_manual_uses_user_name(self):
        tool = make_album(FakeMedia(album='Scanner Album', name='My Pick'),
                          manual=True)
        self.assertTrue(tool.pre_search_logging())
        self.assertEqual(tool.media.album, 'My Pick')

    def test_normal_passes(self):
        tool = make_album(FakeMedia(album='The Martian'))
        self.assertTrue(tool.pre_search_logging())


class TestArtistSearchToolBody(unittest.TestCase):
    def test_build_search_body(self):
        tool = make_artist(FakeMedia(artist='Andy Weir'))
        self.assertEqual(
            tool.build_search_body(), {'q': 'Andy Weir', 'type': 'people'})

    def test_build_search_body_too_short_none(self):
        tool = make_artist(FakeMedia(artist='Jo'))
        self.assertIsNone(tool.build_search_body())


class TestCleanupAuthorName(unittest.TestCase):
    def _t(self, name):
        return make_artist(FakeMedia()).cleanup_author_name(name)

    def test_plain_name(self):
        self.assertEqual(self._t('Andy Weir'), 'Andy Weir')

    def test_title_dr_removed(self):
        self.assertEqual(self._t('Dr. John Doe'), ' John Doe')

    def test_initials_collapsing(self):
        # Legacy collapses 'J. K.' to 'J K ' then adds a second space.
        self.assertEqual(self._t('J. K. Rowling'), 'J K  Rowling')

    def test_brackets_removed(self):
        self.assertEqual(self._t('Name [2020]'), 'Name ')


class TestArtistMultiArtist(unittest.TestCase):
    def test_find_non_contributor(self):
        tool = make_artist(FakeMedia(artist='A, B'))
        tool.find_non_contributor(['A - Contributor', 'B'])
        self.assertEqual(tool.media.artist, 'B')

    def test_all_contributors_uses_first(self):
        tool = make_artist(FakeMedia(artist='A - X, B - Y'))
        tool.find_non_contributor(['A - X', 'B - Y'])
        self.assertEqual(tool.media.artist, 'A')

    def test_handle_multi_artist(self):
        tool = make_artist(FakeMedia(artist='Alpha, Beta'))
        tool.handle_multi_artist()
        self.assertEqual(tool.media.artist, 'Alpha')

    def test_single_contributor_stripped(self):
        tool = make_artist(FakeMedia(artist='Alpha - X'))
        tool.handle_multi_artist()
        self.assertEqual(tool.media.artist, 'Alpha')

    def test_get_primary_author_from_title(self):
        tool = make_artist(FakeMedia(title='From Title'))
        tool.get_primary_author()
        self.assertEqual(tool.media.artist, 'From Title')


class TestArtistParseApiResponse(unittest.TestCase):
    def test_fixture(self):
        tool = make_artist(FakeMedia())
        results = tool.parse_api_response(
            load_fixture('search_people_andy_weir.json'))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], 'person.ypMPwXzWXaiX')
        self.assertEqual(results[0]['name'], 'Andy Weir')

    def test_missing_keys_rejected(self):
        tool = make_artist(FakeMedia())
        self.assertEqual(
            tool.parse_api_response([{'name': 'No ID'}]), [])


class TestScoreTool(unittest.TestCase):
    def _score(self, result_dict, index=0, year=None,
               media=None, lang=None, manual=False):
        helper = FakeScoreHelper(
            media if media is not None else FakeMedia(),
            lang,
            manual
        )
        info = []
        tool = ScoreTool(
            helper, index, info, plex_shim.Locale.Language.English,
            plex_shim.Util.LevenshteinDistance, result_dict, year
        )
        return tool, info

    def test_reduce_string(self):
        tool, _ = self._score({})
        self.assertEqual(
            tool.reduce_string('The, Martian - A Story'),
            'themartianastory'
        )

    def test_sum_scores(self):
        tool, _ = self._score({})
        self.assertEqual(tool.sum_scores([1, 2, 3]), 6)
        self.assertEqual(tool.sum_scores([]), 0)

    def test_run_score_author_perfect_match(self):
        media = FakeMedia(artist='Andy Weir')
        tool, info = self._score(
            {'id': 'person.ypMPwXzWXaiX', 'name': 'Andy Weir'}, media=media)
        tool.run_score_author()
        self.assertEqual(len(info), 1)
        self.assertEqual(info[0]['id'], 'person.ypMPwXzWXaiX')
        self.assertEqual(info[0]['author'], 'Andy Weir')
        self.assertEqual(info[0]['score'], 100)

    def test_run_score_book_perfect_match(self):
        media = FakeMedia(album='The Martian', artist='Andy Weir')
        result = {
            'book_id': 'book.WQQDcMBQ3qUT',
            'author': [{'name': 'Andy Weir'}],
            'date': None,
            'language': 'English',
            'narrator': [{'name': 'R. C. Bray'}],
            'title': 'The Martian',
        }
        tool, info = self._score(result, media=media, year=2011)
        tool.run_score_book()
        self.assertEqual(len(info), 1)
        self.assertEqual(info[0]['id'], 'book.WQQDcMBQ3qUT')
        self.assertEqual(info[0]['score'], 100)
        self.assertEqual(info[0]['narrator'], 'R. C. Bray')
        self.assertEqual(info[0]['title'], 'The Martian')
        self.assertEqual(info[0]['year'], 2011)
        self.assertNotIn('date', info[0])
        self.assertNotIn('region', info[0])

    def test_run_score_book_empty_people(self):
        media = FakeMedia(album='The Martian')
        result = {
            'book_id': 'book.WQQDcMBQ3qUT',
            'author': [],
            'date': None,
            'language': 'English',
            'narrator': [],
            'title': 'The Martian',
        }
        tool, info = self._score(result, media=media)
        tool.run_score_book()
        self.assertEqual(len(info), 1)
        # Empty author list skips author scoring entirely.
        self.assertEqual(info[0]['score'], 100)

    def test_score_below_ignore_boundary_skipped(self):
        media = FakeMedia(album='The Martian', artist='Andy Weir')
        result = {
            'book_id': 'book.hPaWwDcciGQE',
            'author': [{'name': 'Frank Herbert'}],
            'date': None,
            'language': 'English',
            'narrator': [{'name': 'N'}],
            'title': 'Dune Messiah The Golden',
        }
        tool, info = self._score(result, media=media)
        tool.run_score_book()
        self.assertEqual(info, [])

    def test_index_penalty(self):
        media = FakeMedia(album='The Martian', artist='Andy Weir')
        result = {
            'book_id': 'book.WQQDcMBQ3qUT',
            'author': [{'name': 'Andy Weir'}],
            'date': None,
            'language': 'English',
            'narrator': [{'name': 'N'}],
            'title': 'The Martian',
        }
        _, info = self._score(result, index=3, media=media)
        tool = ScoreTool(
            FakeScoreHelper(media), 3, info,
            plex_shim.Locale.Language.English,
            plex_shim.Util.LevenshteinDistance, result, None)
        tool.run_score_book()
        self.assertEqual(info[0]['score'], 97)

    def test_score_album_no_album(self):
        media = FakeMedia()
        tool, _ = self._score({}, media=media)
        self.assertEqual(tool.score_album('The Martian'), 50)

    def test_score_author_no_artist(self):
        media = FakeMedia()
        tool, _ = self._score({}, media=media)
        self.assertEqual(tool.score_author('Andy Weir'), 20)

    def test_score_language_mismatch(self):
        tool, _ = self._score({})
        self.assertEqual(tool.score_language('Spanish'), 2)
        self.assertEqual(tool.score_language('English'), 0)

    def test_language_deduction(self):
        media = FakeMedia(album='The Martian', artist='Andy Weir')
        result = {
            'book_id': 'book.WQQDcMBQ3qUT',
            'author': [{'name': 'Andy Weir'}],
            'date': None,
            'language': 'German',
            'narrator': [{'name': 'N'}],
            'title': 'The Martian',
        }
        tool, info = self._score(result, media=media)
        tool.run_score_book()
        self.assertEqual(info[0]['score'], 98)


class TestScoreOrdering(unittest.TestCase):
    """Automatic series-ordinal disambiguation."""

    def _entry(self, title, ordinal=None, position=None):
        return {'title': title, 'ordinal': ordinal, 'position': position}

    def _point(self, value):
        return {
            'kind': 'point', 'status': 'complete',
            'value': str(value), 'label': str(value), 'sortKey': value,
            'spans': [{'start': value, 'end': value}],
        }

    def _range(self, start, end):
        return {
            'kind': 'range', 'status': 'complete',
            'value': None, 'label': '%s-%s' % (start, end),
            'sortKey': start,
            'spans': [{'start': start, 'end': end}],
        }

    def _absent(self):
        return {
            'kind': 'unknown', 'status': 'absent',
            'value': None, 'label': '', 'sortKey': 5, 'spans': [],
        }

    def _score(self, album, title, series=None, manual=False,
               artist='Andy Weir'):
        media = FakeMedia(album=album, artist=artist)
        result = {
            'book_id': 'book.ordering',
            'author': [{'name': artist}] if artist else [],
            'date': None,
            'language': 'English',
            'narrator': [],
            'title': title,
            'seriesWithId': series if series is not None else [],
        }
        info = []
        tool = ScoreTool(
            FakeScoreHelper(media, manual=manual), 0, info,
            plex_shim.Locale.Language.English,
            plex_shim.Util.LevenshteinDistance, result, None)
        tool.run_score_book()
        return tool, info

    def test_targets_deduct_60_automatically_and_0_manually(self):
        targets = [
            ('Domestic Decay Book 4', 'Domestic Decay 2', '2', 30),
            ('Cultivating Chaos 2', 'Cultivating Chaos', '1', 38),
            ('Swing Shift Book 3', 'Swing Shift', '1', 30),
            ('Swing Shift Book 2', 'Swing Shift', '1', 30),
        ]
        for album, title, ordinal, automatic in targets:
            series = [
                self._entry(title, ordinal, self._point(int(ordinal)))
            ]
            tool, info = self._score(album, title, series)
            self.assertEqual(tool.score_ordering(), 60)
            self.assertEqual(info, [])
            self.assertEqual(
                tool.INITIAL_SCORE - tool.score_album(title)
                - tool.ORDERING_PENALTY,
                automatic)

            tool_manual, info_manual = self._score(
                album, title, series, manual=True)
            self.assertEqual(tool_manual.score_ordering(), 0)
            self.assertEqual(len(info_manual), 1)
            self.assertEqual(info_manual[0]['score'], automatic + 60)

    def test_matching_ordinal_unnumbered_candidate_not_penalised(self):
        series = [self._entry('Swing Shift', '2', self._point(2))]
        tool, info = self._score('Swing Shift Book 2', 'Swing Shift', series)
        self.assertEqual(tool.score_ordering(), 0)
        self.assertEqual(info[0]['score'], 90)

    def test_missing_signal_rejects_book_two_keeps_book_one(self):
        self.assertEqual(
            self._score('Swing Shift Book 2', 'Swing Shift')[0]
            .score_ordering(), 60)
        self.assertEqual(
            self._score('Swing Shift Book 1', 'Swing Shift')[0]
            .score_ordering(), 0)

    def test_title_number_overrides_different_ordinal(self):
        series = [self._entry('Dungeon Diving', '5', self._point(5))]
        tool, _ = self._score(
            'Dungeon Diving 201', 'Dungeon Diving 201', series)
        self.assertEqual(tool.score_ordering(), 0)

    def test_matching_relevant_ordinal_supports_course_number(self):
        series = [self._entry('Dungeon Diving', '1', self._point(1))]
        tool, _ = self._score(
            'Dungeon Diving 101', 'Dungeon Diving 101', series)
        self.assertEqual(tool.score_ordering(), 0)

    def test_unrelated_series_ordinal_cannot_support(self):
        series = [self._entry('Other Series', '4', self._point(4))]
        tool, _ = self._score('Swing Shift Book 4', 'Swing Shift Book 3',
                              series)
        self.assertEqual(tool.score_ordering(), 60)

    def test_multiple_relevant_memberships_order_independent(self):
        first = self._entry('Swing Shift', '2', self._point(2))
        second = self._entry('Swing Shift', '9', self._point(9))
        for series in ([first, second], [second, first]):
            tool, _ = self._score('Swing Shift Book 2', 'Swing Shift',
                                  series)
            self.assertEqual(tool.score_ordering(), 0)

    def test_numeric_ordinal_supplies_missing_position(self):
        for position in (None, {}):
            entry = {'title': 'Swing Shift', 'ordinal': '2',
                     'position': position}
            tool, _ = self._score('Swing Shift Book 2', 'Swing Shift',
                                  [entry])
            self.assertEqual(tool.score_ordering(), 0)
            entry = {'title': 'Swing Shift', 'ordinal': '1',
                     'position': position}
            tool, _ = self._score('Swing Shift Book 2', 'Swing Shift',
                                  [entry])
            self.assertEqual(tool.score_ordering(), 60)

    def test_disjoint_spans_use_containment(self):
        position = {
            'kind': 'range', 'status': 'complete', 'value': None,
            'label': '1-2,5-6', 'sortKey': 1,
            'spans': [{'start': 1, 'end': 2}, {'start': 5, 'end': 6}],
        }
        series = [self._entry('Swing Shift', None, position)]
        self.assertEqual(
            self._score('Swing Shift Book 2', 'Swing Shift', series)[0]
            .score_ordering(), 0)
        self.assertEqual(
            self._score('Swing Shift Book 3', 'Swing Shift', series)[0]
            .score_ordering(), 60)

    def test_unknown_and_fractional_positions_abstain(self):
        fractional = {
            'kind': 'point', 'status': 'complete',
            'value': '1.5', 'label': '1.5', 'sortKey': 1.5, 'spans': [],
        }
        fractional_label = {
            'kind': 'point', 'status': 'complete',
            'value': '1.5', 'label': '1', 'sortKey': 1.5, 'spans': [],
        }
        for position in (self._absent(), fractional, fractional_label, None):
            tool, _ = self._score(
                'Swing Shift Book 2', 'Swing Shift',
                [self._entry('Swing Shift', None, position)])
            self.assertEqual(tool.score_ordering(), 0)

    def test_range_endpoints_inclusive(self):
        series = [self._entry('Swing Shift', None, self._range(1, 3))]
        self.assertEqual(
            self._score('Swing Shift Book 1', 'Swing Shift', series)[0]
            .score_ordering(), 0)
        self.assertEqual(
            self._score('Swing Shift Book 3', 'Swing Shift', series)[0]
            .score_ordering(), 0)
        self.assertEqual(
            self._score('Swing Shift Book 4', 'Swing Shift', series)[0]
            .score_ordering(), 60)

    def test_ordering_suffix_extraction(self):
        tool, _ = self._score('Swing Shift', 'Swing Shift')
        self.assertEqual(
            tool.ordering_suffix('Swing Shift Book 2'), ('Swing Shift', 2))
        self.assertEqual(
            tool.ordering_suffix('Swing Shift Book #2'), ('Swing Shift', 2))
        self.assertEqual(
            tool.ordering_suffix('Swing Shift #2'), ('Swing Shift', 2))
        self.assertEqual(
            tool.ordering_suffix('Swing Shift - 2'), ('Swing Shift', 2))
        self.assertIsNone(tool.ordering_suffix('Swing Shift Books 1-3'))
        self.assertIsNone(
            tool.ordering_suffix(u'Swing Shift Books 1\u20133'))
        self.assertIsNone(tool.ordering_suffix('Swing Shift 1 to 3'))
        self.assertIsNone(tool.ordering_suffix('Swing Shift 1.5'))
        self.assertIsNone(tool.ordering_suffix('Swing Shift 2020'))
        self.assertIsNone(tool.ordering_suffix('Swing Shift Book IV'))
        self.assertIsNone(tool.ordering_suffix('Swing Shift Book Two'))
        self.assertIsNone(
            tool.ordering_suffix("Swing Shift Publisher's Pack 2"))
        self.assertIsNone(tool.ordering_suffix('Swing Shift Volume 2'))
        self.assertIsNone(tool.ordering_suffix('Swing Shift Vol. 2'))
        self.assertIsNone(tool.ordering_suffix('1984'))

    def test_non_ordinal_titles_abstain(self):
        controls = [
            ("The Valens Legacy Publisher's Pack 2",
             "The Valens Legacy Publisher's Pack 2"),
            ('My Ninja Girl Volume 2', 'My Ninja Girl Volume 2'),
            ('Swing Shift Books 1-3', 'Swing Shift'),
            (u'Swing Shift Books 1\u20133', 'Swing Shift'),
            ('Swing Shift 1 to 3', 'Swing Shift'),
            ('Swing Shift 1.5', 'Swing Shift'),
            ('Super Sales on Super Heroes', 'Super Sales on Super Heroes 5'),
            ('1984', '1984'),
            ('Series 2020', 'Series'),
            ('World War II', 'World War II'),
            ('Series Book IV', 'Series'),
        ]
        for album, title in controls:
            tool, _ = self._score(album, title)
            self.assertEqual(tool.score_ordering(), 0,
                             '%s / %s' % (album, title))


if __name__ == '__main__':
    unittest.main()
