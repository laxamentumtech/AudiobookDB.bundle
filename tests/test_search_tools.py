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
    image_thumb, release_year,
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


class FakeStream(object):
    def __init__(self, stream_type='2', language_code=None, language=None):
        self.type = stream_type
        if language_code is not None:
            self.languageCode = language_code
        if language is not None:
            self.language = language


class FakePart(object):
    def __init__(self, file_name, streams=None):
        self.file = file_name
        self.streams = streams or []


class FakeItem(object):
    def __init__(self, parts):
        self.parts = parts


class FakeTrack(object):
    def __init__(self, duration=None, parts=None):
        if duration is not None:
            self.duration = duration
        self.items = [FakeItem(parts or [])]


class FakeTree(object):
    def __init__(self, files=None, tracks=None, parts=None):
        if parts is None:
            parts = [FakePart(name) for name in files or []]
        self.items = [FakeItem(parts)]
        self.tracks = tracks or {}
        self.children = list(self.tracks.values())


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
        # The resolved matched release is explicitly identified: its date
        # wins over the work copyright.
        self.assertEqual(r.year, 2013)
        self.assertTrue(r.thumb.endswith('/small.jpg'))

    def test_books_from_manual_album(self):
        install_transport({
            BASE + '/audiobooks/external/audible/B00B5HZGUG':
                (200, api_body(load_fixture(
                    'book_external_resolve_B00B5HZGUG.json'))),
        })
        tool = make('books', FakeMedia(album='The Martian B00B5HZGUG'),
                    manual=True)
        self.assertTrue(tool.check_for_asin())
        self.assertEqual(tool.results.appended[0].id,
                         'book.WQQDcMBQ3qUT.release.dPL9fC7YnK8X')
        self.assertEqual(tool.results.appended[0].name, 'The Martian w/ R.C. Bray')

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
        self.assertTrue(r.thumb.endswith('/small.jpg'))

    def test_native_book_release_id_pair(self):
        install_transport({
            BASE + '/books/WQQDcMBQ3qUT': (
                200, api_body(load_fixture('book_detail_WQQDcMBQ3qUT.json'))),
            BASE + '/releases/dPL9fC7YnK8X': (
                200, api_body(load_fixture('release_detail_dPL9fC7YnK8X.json'))),
        })
        tool = make('books',
                    FakeMedia(album='book.WQQDcMBQ3qUT.release.dPL9fC7YnK8X'),
                    manual=True)
        self.assertTrue(tool.check_for_asin())
        self.assertEqual(tool.results.appended[0].id,
                         'book.WQQDcMBQ3qUT.release.dPL9fC7YnK8X')
        self.assertEqual(tool.results.appended[0].name, 'The Martian w/ R.C. Bray')
        self.assertEqual(tool.results.appended[0].year, 2013)
        self.assertTrue(
            tool.results.appended[0].thumb.endswith('/small.jpg'))

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

    def test_release_without_book_rejected(self):
        # A release detail that omits the book entirely (book: None)
        # cannot be tied to the book: the mismatch guard rejects it.
        other_release = load_fixture('release_detail_dPL9fC7YnK8X.json')
        other_release['book'] = None
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


class TestFileAsinHints(unittest.TestCase):
    """Automatic album ASIN hints from the scanner's local file parts."""

    def _mapping(self):
        return {
            BASE + '/audiobooks/external/audible/B00B5HZGUG':
                (200, api_body(load_fixture(
                    'book_external_resolve_B00B5HZGUG.json'))),
        }

    @staticmethod
    def _asin_requests():
        return [req for req in HTTP.requests
                if '/audiobooks/external/audible/' in req[0]]

    def test_all_parts_supply_the_asin(self):
        tree = FakeTree(files=['/lib/01 B00B5HZGUG.mp3',
                               '/lib/02 B00B5HZGUG.mp3'])
        install_transport(self._mapping())
        tool = make('books', FakeMedia(tree=tree))
        self.assertTrue(tool.check_for_asin())
        self.assertEqual(len(tool.results.appended), 1)
        self.assertEqual(len(self._asin_requests()), 1)

    def test_filename_and_parts_dedup_case_insensitively(self):
        tree = FakeTree(files=['/lib/part b00b5hzgug.mp3'])
        install_transport(self._mapping())
        tool = make('books', FakeMedia(filename='B00B5HZGUG', tree=tree))
        self.assertTrue(tool.check_for_asin())
        self.assertEqual(len(tool.results.appended), 1)
        requests = self._asin_requests()
        self.assertEqual(len(requests), 1)
        self.assertTrue(requests[0][0].endswith('/B00B5HZGUG'))

    def test_conflicting_parts_skip_lookup_and_fall_through(self):
        first = FakeTrack(1000, [FakePart('/lib/01 B00B5HZGUG.mp3')])
        second = FakeTrack(2500, [FakePart('/lib/02 B00G0WYW92.mp3')])
        tree = FakeTree(tracks={'1': second})
        tree.children = [first, second]
        install_transport(self._mapping())
        tool = make('books', FakeMedia(tree=tree))
        self.assertFalse(tool.check_for_asin())
        self.assertEqual(tool.results.appended, [])
        self.assertEqual(HTTP.requests, [])

    def test_manual_typed_query_ignores_file_asins(self):
        tree = FakeTree(files=['/lib/01 B00B5HZGUG.mp3'])
        install_transport(self._mapping())
        tool = make('books', FakeMedia(tree=tree, album='The Martian'),
                    manual=True)
        self.assertFalse(tool.check_for_asin())
        self.assertEqual(HTTP.requests, [])

    def test_bounded_token_does_not_match_longer_runs(self):
        install_transport(self._mapping())
        tool = make('books', FakeMedia(filename='XB00B5HZGUGX.mp3'))
        self.assertFalse(tool.check_for_asin())
        self.assertEqual(HTTP.requests, [])

    def test_tree_absent_still_uses_filename(self):
        install_transport(self._mapping())
        tool = make('books', FakeMedia(filename='B00B5HZGUG'))
        self.assertTrue(tool.check_for_asin())
        self.assertEqual(len(tool.results.appended), 1)

    def test_non_audible_token_is_not_a_file_hint(self):
        install_transport(self._mapping())
        tool = make('books', FakeMedia(filename='recording A000000001.mp3'))
        self.assertFalse(tool.check_for_asin())
        self.assertEqual(HTTP.requests, [])

    def test_typed_lookup_keeps_the_legacy_grammar(self):
        url = BASE + '/audiobooks/external/audible/A000000001'
        book = load_fixture('book_external_resolve_B00B5HZGUG.json')
        install_transport({url: (200, api_body(book))})
        tool = make('books', FakeMedia(album='Title A000000001'), manual=True)
        self.assertTrue(tool.check_for_asin())
        self.assertEqual(tool.results.appended[0].id,
                         'book.WQQDcMBQ3qUT.release.dPL9fC7YnK8X')


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
        self.assertEqual(body['filters'], {'person': 'Andy Weir', 'role': 'Author'})

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

    def test_short_title_and_author_search_for_the_title(self):
        tool = make_album(FakeMedia(album='It', artist='Stephen King'))
        self.assertEqual(tool.build_search_body(), {
            'q': 'It', 'type': 'books',
            'filters': {'person': 'Stephen King', 'role': 'Author'},
        })

    def test_author_alone_does_not_search_for_an_album(self):
        tool = make_album(FakeMedia(artist='Stephen King'))
        self.assertIsNone(tool.build_search_body())


class TestAlbumParentAuthor(unittest.TestCase):
    """Native parent person ID is authoritative author evidence."""

    @staticmethod
    def media(parent_id, **kw):
        kw.setdefault('album', 'The Martian')
        kw.setdefault('artist', 'Andy Weir')
        media = FakeMedia(**kw)
        media.parent_metadata = type('PM', (), {'id': parent_id})()
        return media

    def test_native_parent_author_searches_title_first(self):
        tool = make_album(self.media('person.ypMPwXzWXaiX'))
        self.assertEqual(tool.build_search_body(),
                         {'q': 'The Martian', 'type': 'books'})

    def test_native_parent_author_short_title_keeps_filter(self):
        tool = make_album(self.media('person.ypMPwXzWXaiX', album='It'))
        self.assertEqual(tool.build_search_body(), {
            'q': 'It', 'type': 'books',
            'filters': {'person': 'Andy Weir', 'role': 'Author'},
        })

    def test_native_parent_author_short_title_without_artist_is_skipped(self):
        tool = make_album(self.media('person.ypMPwXzWXaiX', album='It',
                                     artist=None))
        self.assertIsNone(tool.build_search_body())

    def test_legacy_parent_id_keeps_author_filter(self):
        tool = make_album(self.media('B00G0WYW92'))
        self.assertEqual(tool.build_search_body()['filters'],
                         {'person': 'Andy Weir', 'role': 'Author'})

    def test_missing_parent_metadata_keeps_author_filter(self):
        media = FakeMedia(album='The Martian', artist='Andy Weir')
        media.parent_metadata = None
        tool = make_album(media)
        self.assertEqual(tool.build_search_body()['filters'],
                         {'person': 'Andy Weir', 'role': 'Author'})

    def test_parent_author_id_validates_native_id(self):
        tool = make_album(self.media('person.ypMPwXzWXaiX'))
        self.assertEqual(tool.parent_author_id(), 'ypMPwXzWXaiX')
        self.assertIsNone(make_album(self.media('B00G0WYW92')).parent_author_id())


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

    def test_keeps_accents_punctuation_and_title_words(self):
        tool = make_album(FakeMedia(album=u'Caf\u00e9: An Official Story'))
        self.assertEqual(tool.normalize_name(), u'Caf\u00e9: An Official Story')

    def test_keeps_bracketed_book_number(self):
        # A bracketed book number is preserved (unbracketed) as scoring
        # evidence; a non-number tag like [2017] is still stripped.
        tool = make_album(FakeMedia(album='Saga [Book 2]'))
        self.assertEqual(tool.normalize_name(), 'Saga Book 2')
        tool2 = make_album(FakeMedia(album='Saga [2017]'))
        self.assertEqual(tool2.normalize_name(), 'Saga')

    def test_strips_non_numeric_book_bracket(self):
        # A 'book' bracket without a number (e.g. [Book Club]) carries no
        # book-number evidence and is stripped like any other tag.
        tool = make_album(FakeMedia(album='Saga [Book Club]'))
        self.assertEqual(tool.normalize_name(), 'Saga')
        tool2 = make_album(FakeMedia(album='Saga [Books 1\u20133]'))
        self.assertEqual(tool2.normalize_name(), 'Saga')

    def test_strips_mixed_book_bracket(self):
        # A bracket mixing a book number with other text
        # ([Book 2 - Unabridged]) is not a pure book-number tag: it is
        # stripped entirely, while a pure [Book 2] is still preserved.
        tool = make_album(FakeMedia(album='Saga [Book 2 - Unabridged]'))
        self.assertEqual(tool.normalize_name(), 'Saga')
        tool2 = make_album(FakeMedia(album='Saga [Book 2]'))
        self.assertEqual(tool2.normalize_name(), 'Saga Book 2')


class TestAlbumParseApiResponse(unittest.TestCase):
    def test_fixture_hits(self):
        tool = make_album(FakeMedia())
        results = tool.parse_api_response(load_fixture('search_books_martian.json'))
        # The decoy 'A Sidekick' hit comes first; WQQDcMBQ3qUT is index 1.
        self.assertEqual(len(results), 10)
        self.assertEqual(results[1]['book_id'], 'book.WQQDcMBQ3qUT')
        self.assertEqual(results[1]['title'], 'The Martian')
        self.assertEqual(results[1]['author'], [
            {'name': 'Andy Weir', 'id': 'ypMPwXzWXaiX'},
        ])
        self.assertEqual(results[1]['narrator'], [])
        self.assertIsNone(results[1]['subtitle'])
        self.assertTrue(results[1]['thumb'].endswith('/small.jpg'))

    def test_incomplete_credits_do_not_drop_the_hit(self):
        tool = make_album(FakeMedia())
        results = tool.parse_api_response([
            {'id': 'abc', 'title': 'No Credits'},
            {'id': 'def', 'title': 'Partial Credits', 'people': [
                {'role': {'name': 'Author'}, 'person': None},
                {'role': {'name': 'Author'}, 'person': {'name': 'Ada Doe'}},
            ]},
        ])
        self.assertEqual(results[0]['author'], [])
        self.assertEqual(results[1]['author'], [{'name': 'Ada Doe'}])

    def test_string_role_credit_is_skipped_without_dropping_the_hit(self):
        # A credit whose role is a bare string (not a mapping) is skipped;
        # the hit itself is kept, and a later valid credit is still read.
        tool = make_album(FakeMedia())
        results = tool.parse_api_response([
            {'id': 'abc', 'title': 'String Role', 'people': [
                {'role': 'Author', 'person': {'name': 'Bad Role'}},
                {'role': {'name': 'Author'}, 'person': {'name': 'Ada Doe'}},
            ]},
        ])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['author'], [{'name': 'Ada Doe'}])

    def test_missing_required_keys_rejected(self):
        tool = make_album(FakeMedia())
        self.assertEqual(
            tool.parse_api_response([
                {'id': '', 'title': 'No usable ID'},
                {'title': 'No ID'},
                {'id': 'abc', 'people': []},
            ]), [])

    def test_non_dict_items_rejected(self):
        tool = make_album(FakeMedia())
        self.assertEqual(tool.parse_api_response(['nope', None, 5]), [])

    def test_thumb_only_for_trusted_cdn_urls(self):
        tool = make_album(FakeMedia())
        results = tool.parse_api_response([
            {'id': 'a', 'title': 'Trusted', 'image': {
                'url': 'https://cdn.audiobookdb.org/abc'}},
            {'id': 'b', 'title': 'Plain HTTP', 'image': {
                'url': 'http://cdn.audiobookdb.org/abc'}},
            {'id': 'c', 'title': 'Other Host', 'image': {
                'url': 'https://example.org/abc'}},
            {'id': 'd', 'title': 'No Image'},
        ])
        self.assertEqual(results[0]['thumb'],
                         'https://cdn.audiobookdb.org/abc/small.jpg')
        self.assertIsNone(results[1]['thumb'])
        self.assertIsNone(results[2]['thumb'])
        self.assertIsNone(results[3]['thumb'])

    def test_no_narrator_role(self):
        tool = make_album(FakeMedia())
        results = tool.parse_api_response([
            {'id': 'abc', 'title': 'T', 'people': [
                {'role': {'name': 'Narrator'},
                 'person': {'id': 'p1', 'name': 'N N'}}]},
        ])
        self.assertEqual(results[0]['narrator'], [{'name': 'N N'}])


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


class TestAlbumReleasesForBook(unittest.TestCase):
    """One detail GET feeds manual release rows."""

    @staticmethod
    def detail_url(book_id):
        return BASE + '/books/' + book_id + '?include=releases'

    def test_returns_the_original_release_dict(self):
        book = load_fixture('book_detail_WQQDcMBQ3qUT.json')
        book_id = book['id']
        install_transport({self.detail_url(book_id): (200, api_body(book))})
        releases = make_album(FakeMedia()).releases_for_book(book_id)
        self.assertEqual(releases, book['releases'])
        release = releases[0]
        self.assertEqual(release, book['releases'][0])
        self.assertEqual(release['id'], 'dPL9fC7YnK8X')
        self.assertEqual(release['language'], {'name': 'English'})
        self.assertEqual(release['people'], book['releases'][0]['people'])
        self.assertEqual(release['images'], book['releases'][0]['images'])
        self.assertEqual(release_year(release), 2013)
        self.assertTrue(image_thumb(release['images'][0]).endswith(
            '/small.jpg'))

    def test_duplicate_release_ids_appear_once(self):
        book = load_fixture('book_detail_WQQDcMBQ3qUT.json')
        original = book['releases'][:]
        book['releases'].append(dict(original[0]))
        book_id = book['id']
        install_transport({self.detail_url(book_id): (200, api_body(book))})
        releases = make_album(FakeMedia()).releases_for_book(book_id)
        self.assertEqual(releases, original)

    def test_merged_book_301_to_winner_returns_winner_releases(self):
        # A merged book redirects to the canonical winner; the response
        # carries the winner's id and its releases reference that id, so
        # the stale stored loser ID must still resolve.
        book = load_fixture('book_detail_WQQDcMBQ3qUT.json')
        book['id'] = 'winnerBook123'
        for release in book['releases']:
            release['book'] = {'id': 'winnerBook123'}
        loser_id = 'WQQDcMBQ3qUT'
        install_transport({self.detail_url(loser_id): (200, api_body(book))})
        releases = make_album(FakeMedia()).releases_for_book(loser_id)
        self.assertEqual(releases, book['releases'])

    def test_release_for_another_book_is_filtered(self):
        book = load_fixture('book_detail_WQQDcMBQ3qUT.json')
        book['releases'][0]['book'] = {'id': 'otherBook123'}
        book_id = book['id']
        install_transport({self.detail_url(book_id): (200, api_body(book))})
        self.assertEqual(
            make_album(FakeMedia()).releases_for_book(book_id),
            book['releases'][1:])

    def test_failure_and_empty_id_return_empty(self):
        install_transport({})
        tool = make_album(FakeMedia())
        self.assertEqual(tool.releases_for_book(None), [])
        self.assertEqual(HTTP.requests, [])
        self.assertEqual(tool.releases_for_book('missingBook'), [])


class TestRecordingHints(unittest.TestCase):
    """Soft recording hints from the scanner's media tree."""

    def test_track_durations_sum(self):
        first = FakeTrack(1000)
        second = FakeTrack(2500)
        tree = FakeTree(tracks={'1': second})
        tree.children = [first, second]
        tool = make_album(FakeMedia(tree=tree))
        self.assertEqual(tool.recording_hints(), (3500, None))

    def test_any_missing_track_duration_gives_no_duration(self):
        tree = FakeTree(tracks={'0': FakeTrack(1000), '1': FakeTrack()})
        self.assertIsNone(
            make_album(FakeMedia(tree=tree)).recording_hints()[0])

    def test_no_tree_gives_no_hints(self):
        self.assertEqual(make_album(FakeMedia()).recording_hints(),
                         (None, None))

    def test_consistent_audio_language_is_normalized(self):
        parts = [FakePart('a.mp3', [FakeStream('2', 'eng')]),
                 FakePart('b.mp3', [FakeStream('2', 'EN')])]
        tree = FakeTree(parts=parts, tracks={'0': FakeTrack(1000)})
        self.assertEqual(make_album(FakeMedia(tree=tree)).recording_hints(),
                         (1000, 'English'))

    def test_stream_language_label_fallback(self):
        parts = [FakePart('a.mp3', [FakeStream('2', None, 'French')])]
        tree = FakeTree(parts=parts)
        self.assertEqual(make_album(FakeMedia(tree=tree)).recording_hints(),
                         (None, 'French'))

    def test_mixed_languages_give_no_language(self):
        parts = [FakePart('a.mp3', [FakeStream('2', 'eng')]),
                 FakePart('b.mp3', [FakeStream('2', 'deu')])]
        tree = FakeTree(parts=parts)
        self.assertIsNone(
            make_album(FakeMedia(tree=tree)).recording_hints()[1])

    def test_missing_stream_language_gives_no_language(self):
        parts = [FakePart('a.mp3', [FakeStream('2', 'eng')]),
                 FakePart('b.mp3', [FakeStream('2')])]
        tree = FakeTree(parts=parts)
        self.assertIsNone(
            make_album(FakeMedia(tree=tree)).recording_hints()[1])

    def test_part_without_stream_data_gives_no_language(self):
        parts = [FakePart('a.mp3', [FakeStream('2', 'eng')]),
                 FakePart('b.mp3')]
        tree = FakeTree(parts=parts)
        self.assertIsNone(
            make_album(FakeMedia(tree=tree)).recording_hints()[1])

    def test_non_audio_streams_are_ignored(self):
        parts = [FakePart('a.mp3', [FakeStream('2', 'eng'),
                                     FakeStream('3', 'deu')])]
        tree = FakeTree(parts=parts)
        self.assertEqual(
            make_album(FakeMedia(tree=tree)).recording_hints()[1], 'English')

    def test_unmapped_stream_code_without_label_gives_no_hint(self):
        # An unmapped code (e.g. 'und') with no usable display label must
        # not pass the code itself to the ranker.
        parts = [FakePart('a.mp3', [FakeStream('2', 'und')])]
        tree = FakeTree(parts=parts)
        self.assertIsNone(
            make_album(FakeMedia(tree=tree)).recording_hints()[1])

    def test_display_label_in_code_field_is_a_hint(self):
        # A display label carried in the code field is a usable hint.
        parts = [FakePart('a.mp3', [FakeStream('2', 'English')])]
        tree = FakeTree(parts=parts)
        self.assertEqual(
            make_album(FakeMedia(tree=tree)).recording_hints()[1], 'English')


class TestImageAndDateHelpers(unittest.TestCase):
    def test_image_thumb_uses_small_derivative(self):
        self.assertEqual(
            image_thumb({'url': 'https://cdn.audiobookdb.org/abc/'}),
            'https://cdn.audiobookdb.org/abc/small.jpg')

    def test_image_thumb_rejects_untrusted_urls(self):
        self.assertIsNone(image_thumb({'url': 'http://cdn.audiobookdb.org/a'}))
        self.assertIsNone(image_thumb({'url': 'https://example.org/a'}))
        self.assertIsNone(image_thumb({'url': ''}))
        self.assertIsNone(image_thumb(None))
        self.assertIsNone(image_thumb({'sourceUrl': 'https://x'}))

    def test_release_year_only_from_an_explicit_date(self):
        self.assertEqual(
            release_year({'releaseDate': '2013-03-22T00:00:00Z'}), 2013)
        self.assertIsNone(release_year({'releaseDate': ''}))
        self.assertIsNone(release_year({'releaseDate': 'March 2013'}))
        self.assertIsNone(release_year({}))
        self.assertIsNone(release_year(None))

    def test_release_year_non_text_date_is_missing(self):
        # A non-text releaseDate (e.g. a bare year number) has no year
        # prefix to match; it is treated as missing, not a TypeError.
        self.assertIsNone(release_year({'releaseDate': 2020}))
        self.assertIsNone(release_year({'releaseDate': None}))

    def test_first_image_thumb_skips_unusable_images(self):
        from search_tools import first_image_thumb
        # The first image is off-CDN (unusable); the second is a trusted
        # cover. The first usable image wins, matching the manual path's
        # "first usable" rule.
        self.assertEqual(first_image_thumb([
            {'url': 'https://example.org/a'},
            {'url': 'https://cdn.audiobookdb.org/b'},
        ]), 'https://cdn.audiobookdb.org/b/small.jpg')
        # No usable image at all: the fallback (None) is preserved.
        self.assertIsNone(first_image_thumb(
            [{'url': 'https://example.org/a'}, {}]))
        self.assertIsNone(first_image_thumb([]))


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
    def score_book(self, album, title, artist='Ada Doe', authors=None,
                   manual=False, parent_id=None, author_ids=None,
                   relaxed_author=False, **hit):
        media = FakeMedia(album=album, artist=artist)
        if parent_id:
            media.parent_metadata = type('PM', (), {'id': parent_id})()
        helper = make_album(media, manual)
        helper.build_search_body()
        authors = authors if authors is not None else ['Ada Doe']
        people = []
        for index, name in enumerate(authors):
            person = {'name': name}
            if author_ids and index < len(author_ids) and author_ids[index]:
                person['id'] = author_ids[index]
            people.append({'role': {'name': 'Author'}, 'person': person})
        hit.update(id='abc', title=title, people=people)
        result = helper.parse_api_response([hit])[0]
        info = []
        ScoreTool(helper, 0, info, plex_shim.Util.LevenshteinDistance,
                  result).run_score_book(relaxed_author)
        return info

    def test_subtitle_and_one_coauthor_are_full_match_evidence(self):
        result = self.score_book(
            u'Caf\u00e9: An Official Story (Unabridged)', u'Caf\u00e9',
            authors=['Someone Else', 'Ada Doe'], subtitle='An Official Story',
            originalLanguage='French')
        self.assertEqual(result[0]['score'], 100)

    def test_same_base_wrong_volume_is_only_available_in_fix_match(self):
        for album, title in [('Swing Shift Book 2', 'Swing Shift'),
                             ('Swing Shift Book 3', 'Swing Shift'),
                             ('Cultivating Chaos 2', 'Cultivating Chaos'),
                             ('Domestic Decay Book 4', 'Domestic Decay 2')]:
            self.assertEqual(self.score_book(album, title), [])
            self.assertEqual(self.score_book(album, title, manual=True)[0]['id'],
                             'book.abc')

    def test_bracketed_book_number_rejects_unnumbered_same_base(self):
        # A bracketed book number is preserved through normalization, so an
        # unnumbered same-base hit conflicts and is skipped (auto search).
        self.assertEqual(self.score_book('Saga [Book 2]', 'Saga'), [])
        self.assertEqual(
            self.score_book('Saga [Book 2]', 'Saga', manual=True)[0]['id'],
            'book.abc')

    def test_accent_folded_stem_rejects_number_conflict(self):
        # The comparison key folds accents: an unaccented query stem
        # (Cancion) matches an accented candidate stem (Canción), so a
        # differing book number is a conflict.
        self.assertEqual(self.score_book('Cancion 2', u'Canci\u00f3n 3'), [])
        # The same stem with the same number is not a conflict; the fold is
        # scoped to the comparison, so the title Levenshtein keeps its
        # distance (Cancion vs Canción), yielding 98, not 100.
        self.assertEqual(
            self.score_book('Cancion 2', u'Canci\u00f3n 2')[0]['score'], 98)

    def test_range_can_cover_query_even_when_first_ordinal_differs(self):
        series = [{'title': 'Saga', 'ordinal': '1', 'position': {
            'status': 'complete', 'spans': [{'start': 1, 'end': 3}],
        }}]
        self.assertEqual(self.score_book('Saga Book 2', 'Saga',
                                         seriesWithId=series)[0]['id'], 'book.abc')
        self.assertEqual(self.score_book('Saga Book 4', 'Saga',
                                         seriesWithId=series), [])

    def test_prefixed_series_title_resolves_book_number_conflict(self):
        # A series named by a prefixed title (The Saga) is the same series
        # as the bare query stem (Saga): the comparison must strip and
        # fold, not just fold, so the omnibus's span resolves the conflict
        # and the queried number is not skipped.
        series = [{'title': 'The Saga', 'ordinal': '1', 'position': {
            'status': 'complete', 'spans': [{'start': 1, 'end': 3}],
        }}]
        self.assertEqual(
            self.score_book('The Saga Book 2', 'The Saga',
                            seriesWithId=series)[0]['id'],
            'book.abc')
        self.assertEqual(self.score_book('The Saga Book 4', 'The Saga',
                                         seriesWithId=series), [])

    def test_accented_series_title_resolves_book_number_conflict(self):
        # The comparison key folds accents on both sides: an unaccented
        # query stem (Cafe) matches an accented series title (Café), so a
        # covered span resolves the conflict. The candidate title itself
        # does not carry the queried number, so only the series span can
        # save it: a fold-only key (no accent folding, no strip) misses
        # the accented series and lets the conflict stand.
        series = [{u'title': u'Caf\u00e9', 'ordinal': '1', 'position': {
            'status': 'complete', 'spans': [{'start': 1, 'end': 3}],
        }}]
        self.assertEqual(self.score_book('Cafe 2', u'Caf\u00e9 Stories',
                                         seriesWithId=series)[0]['id'],
                         'book.abc')
        self.assertEqual(self.score_book('Cafe 4', u'Caf\u00e9 Stories',
                                         seriesWithId=series), [])

    def test_literal_title_number_takes_precedence_over_series_position(self):
        series = [{'title': 'Dungeon Diving', 'position': {
            'status': 'complete', 'spans': [{'start': 5, 'end': 5}],
        }}]
        result = self.score_book('Dungeon Diving Book 201', 'Dungeon Diving 201',
                                 seriesWithId=series)
        self.assertEqual(result[0]['score'], 100)

    def test_unrelated_series_and_edition_numbers_do_not_veto_title(self):
        series = [{'title': 'Other Saga', 'position': {
            'status': 'complete', 'spans': [{'start': 1, 'end': 1}],
        }}]
        for title in ('Saga Volume 2', "Saga Publisher's Pack 2", 'Saga 1984',
                      'Saga Book 2', u'Saga Books 1\u20133'):
            self.assertEqual(self.score_book(title, title,
                                             seriesWithId=series)[0]['score'], 100)

    def test_set_position_membership_supports_covered_number(self):
        # A disjoint set ("1-2, 5") is reported as multiple spans; a
        # covered number is supported even when the hit's own title number
        # differs.
        series = [{'title': 'Saga', 'ordinal': '1', 'position': {
            'kind': 'set', 'status': 'complete', 'value': '1-2, 5',
            'label': '1-2, 5', 'sortKey': 1,
            'spans': [{'start': 1, 'end': 2}, {'start': 5, 'end': 5}],
        }}]
        result = self.score_book('Saga Book 2', 'Saga Book 1',
                                 seriesWithId=series)
        self.assertEqual(result[0]['id'], 'book.abc')
        self.assertEqual(
            self.score_book('Saga Book 2', 'Saga Book 1', manual=True,
                            seriesWithId=series)[0]['id'], 'book.abc')
        self.assertEqual(
            self.score_book('Saga Book 3', 'Saga Book 1',
                            seriesWithId=series), [])

    def test_legacy_ordinal_supplies_missing_position(self):
        # Position is authoritative; a numeric ordinal is used only when
        # the structured position is missing.
        for position in (None, {}):
            series = [{'title': 'Saga', 'ordinal': '2',
                       'position': position}]
            self.assertEqual(
                self.score_book('Saga Book 2', 'Saga',
                                seriesWithId=series)[0]['id'], 'book.abc')
            series = [{'title': 'Saga', 'ordinal': '1',
                       'position': position}]
            self.assertEqual(
                self.score_book('Saga Book 2', 'Saga',
                                seriesWithId=series), [])

    def test_explicit_unknown_position_abstains(self):
        absent = {'kind': 'unknown', 'status': 'absent', 'value': None,
                  'label': '', 'sortKey': None, 'spans': []}
        partial = {'kind': 'range', 'status': 'partial', 'value': None,
                   'label': '', 'sortKey': 3,
                   'spans': [{'start': 3, 'end': 4}]}
        for position in (absent, partial):
            series = [{'title': 'Saga', 'ordinal': '1',
                       'position': position}]
            self.assertEqual(
                self.score_book('Saga Book 2', 'Saga',
                                seriesWithId=series)[0]['id'], 'book.abc')

    def test_malformed_span_is_not_contradiction(self):
        for spans in ([{'start': 5, 'end': 2}],
                      [{'start': None, 'end': 5}],
                      [{'start': 'x', 'end': 5}]):
            series = [{'title': 'Saga', 'position': {
                'kind': 'range', 'status': 'complete', 'spans': spans,
            }}]
            self.assertEqual(
                self.score_book('Saga Book 2', 'Saga',
                                seriesWithId=series)[0]['id'], 'book.abc',
                spans)
        # A valid non-covering span alongside a malformed one still
        # conflicts.
        series = [{'title': 'Saga', 'position': {
            'kind': 'set', 'status': 'complete',
            'spans': [{'start': 3, 'end': 4}, {'start': 5, 'end': 2}],
        }}]
        self.assertEqual(
            self.score_book('Saga Book 2', 'Saga', seriesWithId=series), [])

    def test_unrelated_title_number_does_not_override_membership(self):
        series = [{'title': 'Saga', 'position': {
            'status': 'complete', 'spans': [{'start': 1, 'end': 1}],
        }}]
        self.assertEqual(
            self.score_book('Saga Book 2', 'Side Story 2',
                            seriesWithId=series), [])
        unknown = [{'title': 'Saga', 'position': {
            'kind': 'unknown', 'status': 'absent', 'value': None,
            'label': '', 'sortKey': None, 'spans': [],
        }}]
        self.assertEqual(
            self.score_book('Saga Book 2', 'Side Story 3',
                            seriesWithId=unknown)[0]['id'], 'book.abc')

    def test_bare_title_with_wrong_author_is_rejected(self):
        self.assertEqual(self.score_book('Saga', 'Saga', authors=['Unrelated']), [])

    def test_matching_parent_author_id_avoids_name_penalty(self):
        # Local and catalog spellings differ, but the person ID is the
        # album's parent: no author-distance penalty.
        result = self.score_book(
            'Saga', 'Saga', artist='Wrong Local Name',
            authors=['Another Spelling'], parent_id='person.p1',
            author_ids=['p1'])
        self.assertEqual(result[0]['score'], 100)

    def test_mismatched_parent_author_id_is_not_a_hard_reject(self):
        result = self.score_book(
            'Saga', 'Saga', artist='Ada Doe', authors=['Ada Doe'],
            parent_id='person.p1', author_ids=['p2'])
        self.assertEqual(result[0]['score'], 100)

    def test_missing_parent_author_id_is_not_a_hard_reject(self):
        result = self.score_book(
            'Saga', 'Saga', artist='Ada Doe', authors=['Ada Doe'],
            parent_id='person.p1')
        self.assertEqual(result[0]['score'], 100)

    def test_thumb_is_carried_without_changing_the_score(self):
        image = {'url': 'https://cdn.audiobookdb.org/abc'}
        result = self.score_book('Saga', 'Saga', image=image)
        self.assertEqual(result[0]['score'], 100)
        self.assertTrue(result[0]['thumb'].endswith('/small.jpg'))
        no_image = self.score_book('Saga', 'Saga')
        self.assertNotIn('thumb', no_image[0])

    def test_relaxed_author_caps_the_name_penalty_at_twenty(self):
        # The title-only retry re-scores with the author penalty capped at
        # 20 (manual + relaxed_author): the title is an exact match (0),
        # the name distance (14, x10) far exceeds the cap, so the capped
        # score is 100 - 20 - 0 = 80 — while uncapped, 100 - 140 = -40,
        # below IGNORE_SCORE, so the hit is dropped outright.
        self.assertEqual(self.score_book(
            'The Martian Chronicles', 'The Martian Chronicles',
            artist='Andy Weir', authors=['Xanthique Zephyrium']), [])
        self.assertEqual(self.score_book(
            'The Martian Chronicles', 'The Martian Chronicles',
            artist='Andy Weir', authors=['Xanthique Zephyrium'],
            manual=True, relaxed_author=True)[0]['score'], 80)


if __name__ == '__main__':
    unittest.main()
