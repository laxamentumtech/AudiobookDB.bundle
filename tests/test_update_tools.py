# -*- coding: utf-8 -*-
"""Tests for Contents/Code/update_tools.py against AudiobookDB fixtures."""

import os
import sys
import json
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import plex_shim  # noqa: F401,E402  (framework fakes must load first)

from plex_shim import Prefs, _HTTPRequest  # noqa: E402

import api_client  # noqa: E402
from update_tools import (  # noqa: E402
    UpdateTool, AlbumUpdateTool, ArtistUpdateTool, TagTool,
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
    plex_shim.HTTP.Headers['X-API-Key'] = 'anonymous'
    plex_shim.HTTP.transport = transport
    Prefs['logging_level'] = 'ERROR'
    return transport


class FakeMedia(object):
    def __init__(self, **kw):
        self.title = None
        self.filename = None
        for key, val in kw.items():
            setattr(self, key, val)


class FakeMetadata(object):
    def __init__(self, id='book.WQQDcMBQ3qUT'):
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
        self.posters = {}

    def validate_keys(self, keys):
        pass


def _prefs():
    Prefs['logging_level'] = 'ERROR'
    Prefs['store_author_as_mood'] = True
    Prefs['simplify_title'] = False
    Prefs['sort_author_by_last_name'] = True
    Prefs['keep_existing_genres'] = False
    return Prefs


def make_album(metadata_id='book.WQQDcMBQ3qUT', force=False,
               media=None, metadata=None):
    return AlbumUpdateTool(
        'books', force, plex_shim.Locale.Language.English,
        media if media is not None else FakeMedia(),
        metadata if metadata is not None else FakeMetadata(metadata_id),
        _prefs())


def make_artist(metadata_id='person.ypMPwXzWXaiX', force=False,
                media=None, metadata=None):
    return ArtistUpdateTool(
        'authors', force, plex_shim.Locale.Language.English,
        media if media is not None else FakeMedia(),
        metadata if metadata is not None else FakeMetadata(metadata_id),
        _prefs())


BOOK_DETAIL = 'book_detail_WQQDcMBQ3qUT.json'
RELEASE_DETAIL = 'release_detail_dPL9fC7YnK8X.json'
PERSON_DETAIL = 'person_detail_ypMPwXzWXaiX.json'


class TestAlbumResolveLegacyAsin(unittest.TestCase):
    def _transport(self):
        return {
            BASE + '/audiobooks/external/audible/B00B5HZGUG': (
                200, api_body(load_fixture('book_external_resolve_B00B5HZGUG.json'))),
            BASE + '/books/WQQDcMBQ3qUT': (
                200, api_body(load_fixture(BOOK_DETAIL))),
            BASE + '/releases/dPL9fC7YnK8X': (
                200, api_body(load_fixture(RELEASE_DETAIL))),
            BASE + '/items/book/WQQDcMBQ3qUT/ratings': (
                200, api_body(load_fixture('ratings_book_WQQDcMBQ3qUT.json'))),
        }

    def test_migration_populates_and_stashes_native_ids(self):
        install_transport(self._transport())
        tool = make_album('B00B5HZGUG_us')
        self.assertTrue(tool.resolve_item())
        self.assertEqual(tool.native_book_id, 'WQQDcMBQ3qUT')
        self.assertEqual(tool.native_release_id, 'dPL9fC7YnK8X')
        self.assertEqual(tool.title, 'The Martian')
        self.assertEqual(tool.studio, 'Podium Publishing')
        self.assertEqual(tool.narrator, [{'name': 'R.C. Bray'}])
        self.assertEqual(tool.author, [{'name': 'Andy Weir'}])
        self.assertEqual(str(tool.date), '2013-03-22')
        # audible chip selected (not the first openlibrary chip)
        self.assertEqual(tool.rating, 4.8)
        self.assertTrue(tool.thumb.endswith('/large.jpg'))
        self.assertEqual(tool.similar, None)

    def test_404_leaves_untouched(self):
        install_transport({})
        meta = FakeMetadata('B0AAAAAAAAA_us')
        before = (meta.title, meta.summary, meta.studio, meta.id)
        tool = make_album('B0AAAAAAAAA_us', metadata=meta)
        self.assertFalse(tool.resolve_item())
        self.assertEqual((meta.title, meta.summary, meta.studio, meta.id),
                         before)
        self.assertEqual(tool.native_book_id, None)
        self.assertEqual(tool.native_release_id, None)


class TestAlbumResolveNative(unittest.TestCase):
    def _transport(self):
        return {
            BASE + '/books/WQQDcMBQ3qUT': (
                200, api_body(load_fixture(BOOK_DETAIL))),
            BASE + '/releases/dPL9fC7YnK8X': (
                200, api_body(load_fixture(RELEASE_DETAIL))),
            BASE + '/items/book/WQQDcMBQ3qUT/ratings': (
                200, api_body(load_fixture('ratings_book_WQQDcMBQ3qUT.json'))),
        }

    def test_book_release_pinned(self):
        install_transport(self._transport())
        tool = make_album('book.WQQDcMBQ3qUT.release.dPL9fC7YnK8X')
        self.assertTrue(tool.resolve_item())
        self.assertEqual(tool.native_release_id, 'dPL9fC7YnK8X')
        # release detail book.id is authoritative
        self.assertEqual(tool.native_book_id, 'WQQDcMBQ3qUT')

    def test_book_only_selects_lowest_id(self):
        install_transport(self._transport())
        # Plain book detail carries no matchedReleaseId; the two-release
        # list falls back to the lexicographically lowest id.
        tool = make_album('book.WQQDcMBQ3qUT')
        self.assertTrue(tool.resolve_item())
        self.assertEqual(tool.native_release_id, 'RAffFyqchypK')

    def test_pinned_release_404_preserved(self):
        install_transport(self._transport())
        meta = FakeMetadata('book.WQQDcMBQ3qUT.release.missing123')
        tool = make_album('book.WQQDcMBQ3qUT.release.missing123',
                          metadata=meta)
        self.assertFalse(tool.resolve_item())
        self.assertEqual(meta.id, 'book.WQQDcMBQ3qUT.release.missing123')
        self.assertEqual(meta.title, None)

    def test_book_404_preserved(self):
        install_transport({})
        meta = FakeMetadata('book.WQQDcMBQ3qUT')
        tool = make_album('book.WQQDcMBQ3qUT', metadata=meta)
        self.assertFalse(tool.resolve_item())
        self.assertEqual(meta.id, 'book.WQQDcMBQ3qUT')
        self.assertEqual(meta.title, None)

    def test_wrong_type_id_invalid(self):
        install_transport({})
        tool = make_album('person.ypMPwXzWXaiX')
        self.assertFalse(tool.resolve_item())


class TestAlbumParseApiResponse(unittest.TestCase):
    def test_series_from_fixture(self):
        install_transport({})
        book = load_fixture('book_series_xKHHTwjQLrC7.json')
        book['id'] = 'xKHHTwjQLrC7'
        tool = make_album()
        tool.parse_api_response(book, None)
        self.assertEqual(tool.series, 'The Dune Sequence')
        self.assertEqual(tool.volume, 'Book 12')
        self.assertEqual(tool.series2, 'Dune')
        self.assertEqual(tool.volume2, 'Book 1')
        # work-only path: no release fields
        self.assertIsNone(tool.date)
        self.assertEqual(tool.studio, '')
        self.assertEqual(tool.narrator, [])
        self.assertEqual(tool.title, 'Dune')

    def test_no_releases_fixture_work_only(self):
        install_transport({})
        book = load_fixture('book_detail_no_releases_WQQDcMBQ3qUT.json')
        tool = make_album()
        tool.parse_api_response(book, None)
        self.assertIsNone(tool.date)
        self.assertEqual(tool.studio, '')
        self.assertEqual(tool.narrator, [])
        self.assertEqual(tool.author, [{'name': 'Andy Weir'}])

    def test_no_audible_chip_rating_none(self):
        book = load_fixture(BOOK_DETAIL)
        chips = {'chips': [
            {'source': 'openlibrary', 'average': 4.3, 'count': 10},
        ]}
        install_transport({
            BASE + '/items/book/WQQDcMBQ3qUT/ratings': (200, api_body(chips)),
        })
        tool = make_album()
        tool.parse_api_response(book, None)
        self.assertIsNone(tool.rating)

    def test_audible_chip_not_first(self):
        book = load_fixture(BOOK_DETAIL)
        install_transport({
            BASE + '/items/book/WQQDcMBQ3qUT/ratings': (
                200, api_body(load_fixture('ratings_book_WQQDcMBQ3qUT.json'))),
        })
        tool = make_album()
        tool.parse_api_response(book, None)
        self.assertEqual(tool.rating, 4.8)

    def test_cover_image_missing_thumb_empty(self):
        book = load_fixture(BOOK_DETAIL)
        del book['coverImage']
        install_transport({})
        tool = make_album()
        tool.parse_api_response(book, None)
        self.assertEqual(tool.thumb, '')


class TestReleaseSelection(unittest.TestCase):
    def _book(self, ids):
        return {'releases': [{'id': i} for i in ids]}

    def test_pinned_wins(self):
        tool = make_album()
        self.assertEqual(
            tool.select_release(self._book(['b', 'a']),
                                pinned_release_id='b',
                                matched_release_id='a'),
            'b')

    def test_matched_wins_over_only_and_lowest(self):
        tool = make_album()
        self.assertEqual(
            tool.select_release(self._book(['z', 'a']),
                                matched_release_id='z'),
            'z')

    def test_only_release(self):
        tool = make_album()
        self.assertEqual(
            tool.select_release(self._book(['only'])), 'only')

    def test_lowest_id_default(self):
        tool = make_album()
        self.assertEqual(
            tool.select_release(self._book(['zzz', 'aaa', 'mmm'])), 'aaa')

    def test_no_releases_none(self):
        tool = make_album()
        self.assertIsNone(tool.select_release(self._book([])))

    def test_matched_not_in_releases_falls_through(self):
        tool = make_album()
        self.assertEqual(
            tool.select_release(self._book(['only']),
                                matched_release_id='ghost'),
            'only')


class TestArtistResolve(unittest.TestCase):
    def test_legacy_asin_migration(self):
        install_transport({
            BASE + '/people?external=Audible%3AB00G0WYW92&take=2': (
                200, api_body(
                    load_fixture('person_external_resolve_B00G0WYW92.json'))),
            BASE + '/people/ypMPwXzWXaiX': (
                200, api_body(load_fixture(PERSON_DETAIL))),
        })
        meta = FakeMetadata('B00G0WYW92')
        tool = make_artist('B00G0WYW92', metadata=meta)
        self.assertTrue(tool.resolve_item())
        self.assertEqual(tool.native_person_id, 'ypMPwXzWXaiX')
        # The ID is committed by the agent's compile_metadata, not here:
        # a failed setter must leave the old ID in place.
        self.assertEqual(meta.id, 'B00G0WYW92')
        self.assertEqual(tool.name, 'Andy Weir')
        self.assertEqual(
            tool.genres,
            [{'name': g['title']} for g in
             load_fixture(PERSON_DETAIL)['genres']])
        # Person detail carries no images key.
        self.assertEqual(tool.thumb, '')
        self.assertEqual(tool.similar, None)

    def test_native_person(self):
        install_transport({
            BASE + '/people/ypMPwXzWXaiX': (
                200, api_body(load_fixture(PERSON_DETAIL))),
        })
        meta = FakeMetadata('person.ypMPwXzWXaiX')
        tool = make_artist('person.ypMPwXzWXaiX', metadata=meta)
        self.assertTrue(tool.resolve_item())
        self.assertEqual(meta.id, 'person.ypMPwXzWXaiX')
        self.assertEqual(tool.name, 'Andy Weir')

    def test_404_leaves_untouched(self):
        install_transport({})
        meta = FakeMetadata('person.ypMPwXzWXaiX')
        tool = make_artist('person.ypMPwXzWXaiX', metadata=meta)
        self.assertFalse(tool.resolve_item())
        self.assertEqual(meta.title, None)
        self.assertEqual(meta.summary, None)

    def test_ambiguous_asin_leaves_untouched(self):
        hits = load_fixture('person_external_resolve_B00G0WYW92.json')
        hit2 = dict(hits[0])
        hit2['id'] = 'otherPerson123'
        hit2['name'] = 'Other Person'
        install_transport({
            BASE + '/people?external=Audible%3AB00G0WYW92&take=2': (
                200, api_body(hits + [hit2])),
            BASE + '/people/ypMPwXzWXaiX': (
                200, api_body(load_fixture(PERSON_DETAIL))),
        })
        meta = FakeMetadata('B00G0WYW92')
        tool = make_artist('B00G0WYW92', metadata=meta)
        self.assertFalse(tool.resolve_item())
        self.assertEqual(meta.id, 'B00G0WYW92')
        self.assertEqual(meta.title, None)

    def test_wrong_type_id_invalid(self):
        install_transport({})
        tool = make_artist('book.WQQDcMBQ3qUT')
        self.assertFalse(tool.resolve_item())


class TestUpdateToolHelpers(unittest.TestCase):
    def test_cleanup_html_books(self):
        tool = make_album()
        tool.synopsis = '<p>Line one</p><br /><p>Line two</p>'
        tool.cleanup_html()
        self.assertEqual(tool.synopsis, 'Line one\nLine two')

    def test_cleanup_html_authors(self):
        tool = make_artist()
        tool.description = '<ul><li>One</li></ul><p>Rest</p>'
        tool.cleanup_html()
        self.assertEqual(tool.description, '\u2022 One\n\nRest')

    def test_replace_html_special(self):
        tool = make_album()
        out = tool.replace_html_special(
            '<ul><li>a</li><li>b</li></ul>')
        self.assertEqual(out, '\u2022 a\n \u2022 b')

    def test_collect_metadata_to_log_books(self):
        tool = make_album()
        tool.thumb = 'http://x/large.jpg'
        data = tool.collect_metadata_to_log()
        self.assertEqual(data[0], {'ID': 'book.WQQDcMBQ3qUT'})
        self.assertIn({'Book publisher': None}, data)

    def test_collect_metadata_arrs_legacy_typo(self):
        # Legacy quirk (LEGACY_ISSUES #2): the book branch is gated on the
        # singular 'book', so it never fires for 'books'.
        tool = make_album()
        self.assertEqual(tool.collect_metadata_arrs_to_log(),
                         [{'Genres': set()}])

    def test_get_date_from_string(self):
        tool = make_album()
        self.assertEqual(str(tool.getDateFromString('2013-03-22T00:00:00Z')),
                         '2013-03-22')
        self.assertIsNone(tool.getDateFromString(None))
        self.assertIsNone(tool.getDateFromString('garbage'))

    def test_volume_prefix(self):
        tool = make_album()
        self.assertEqual(tool.volume_prefix('12'), 'Book 12')
        self.assertEqual(tool.volume_prefix('Book 12'), 'Book 12')


class TestAlbumSetters(unittest.TestCase):
    def test_set_metadata_title_and_subtitle(self):
        tool = make_album()
        tool.title = 'The Martian'
        tool.subtitle = ''
        meta = tool.metadata
        tool.set_metadata_title()
        self.assertEqual(meta.title, 'The Martian')

        tool.subtitle = 'A Novel'
        meta.title = None
        tool.set_metadata_title()
        self.assertEqual(meta.title, 'The Martian: A Novel')

    def test_simplify_title(self):
        tool = make_album()
        tool.title = 'Dune, Book 1'
        self.assertEqual(tool.simplify_title(), 'Dune')
        tool.title = 'The Martian (Unabridged)'
        self.assertEqual(tool.simplify_title(), 'The Martian')

    def test_set_metadata_rating_x2(self):
        tool = make_album()
        tool.rating = 4.8
        tool.set_metadata_rating()
        self.assertEqual(tool.metadata.rating, 4.8 * 2)

    def test_set_metadata_rating_none_noop(self):
        tool = make_album()
        tool.rating = None
        tool.set_metadata_rating()
        self.assertIsNone(tool.metadata.rating)

    def test_set_metadata_date_guard(self):
        tool = make_album()
        tool.date = None
        tool.set_metadata_date()
        self.assertIsNone(tool.metadata.originally_available_at)

    def test_set_metadata_studio(self):
        tool = make_album()
        tool.studio = 'Podium Publishing'
        tool.set_metadata_studio()
        self.assertEqual(tool.metadata.studio, 'Podium Publishing')

    def test_set_metadata_summary(self):
        tool = make_album()
        tool.synopsis = '<p>Desc</p>'
        tool.set_metadata_summary()
        self.assertEqual(tool.metadata.summary, 'Desc')

    def test_set_metadata_sort_title_series(self):
        tool = make_album()
        tool.series = 'The Dune Sequence'
        tool.volume = 'Book 12'
        tool.title = 'Dune'
        tool.set_metadata_sort_title()
        self.assertEqual(tool.metadata.title_sort,
                         'The Dune Sequence, Book 12 - Dune')

    def test_set_metadata_tags(self):
        tool = make_album()
        tool.genres = [{'name': 'Science Fiction'}, {'name': 'Thriller'}]
        tool.narrator = [{'name': 'R.C. Bray'}]
        tool.author = [{'name': 'Andy Weir'}]
        tool.series = 'The Dune Sequence'
        tool.series2 = ''
        tool.similar = None
        tool.set_metadata_tags()
        self.assertEqual(tool.metadata.genres,
                         {'Science Fiction', 'Thriller'})
        self.assertEqual(tool.metadata.styles, {'R.C. Bray'})
        self.assertEqual(tool.metadata.moods, {'Andy Weir',
                                               'Series: The Dune Sequence'})

    def test_set_metadata_tags_keep_existing_genres(self):
        Prefs['keep_existing_genres'] = True
        try:
            tool = make_album()
            tool.set_empty_variables()
            tool.metadata.genres.add('Existing')
            tool.genres = [{'name': 'Science Fiction'}]
            tool.set_metadata_tags()
            self.assertIn('Existing', tool.metadata.genres)
        finally:
            Prefs['keep_existing_genres'] = False


class TestArtistSetters(unittest.TestCase):
    def test_set_metadata_title(self):
        tool = make_artist()
        tool.name = 'Andy Weir'
        tool.set_metadata_title()
        self.assertEqual(tool.metadata.title, 'Andy Weir')

    def test_set_metadata_description(self):
        tool = make_artist()
        tool.description = '<p>Bio</p>'
        tool.set_metadata_description()
        self.assertEqual(tool.metadata.summary, 'Bio')

    def test_set_metadata_sort_title_last_name(self):
        tool = make_artist()
        tool.name = 'Andy Weir'
        tool.set_metadata_sort_title()
        self.assertEqual(tool.metadata.title_sort, 'Weir, Andy')

    def test_set_metadata_sort_title_jr(self):
        tool = make_artist()
        tool.name = 'Andy Weir Jr.'
        tool.set_metadata_sort_title()
        # Legacy quirk (kept byte-identical): the captured suffix keeps its
        # leading space, so the join produces 'Weir, Andy,  Jr.'
        self.assertEqual(tool.metadata.title_sort, 'Weir, Andy,  Jr.')

    def test_set_metadata_sort_title_single_word(self):
        tool = make_artist()
        tool.name = 'Asimov'
        tool.metadata.title = 'Asimov'
        tool.set_metadata_sort_title()
        self.assertEqual(tool.metadata.title_sort, 'Asimov')

    def test_set_metadata_tags(self):
        tool = make_artist()
        tool.genres = [{'name': 'Fantasy'}]
        tool.similar = None
        tool.set_metadata_tags()
        self.assertEqual(tool.metadata.genres, {'Fantasy'})

    def test_set_empty_variables(self):
        tool = make_artist()
        tool.set_empty_variables()
        self.assertEqual(tool.name, '')
        self.assertEqual(tool.thumb, '')
        self.assertEqual(tool.genres, None)
        self.assertEqual(tool.similar, None)


class TestTagTool(unittest.TestCase):
    def _album_tool(self, force=False):
        tool = make_album(force=force)
        return tool

    def test_add_narrators_force_clears(self):
        tool = self._album_tool(force=True)
        tool.set_empty_variables()
        tool.metadata.styles.add('Old Style')
        tool.narrator = [{'name': 'R.C. Bray'}]
        tagger = TagTool(tool, Prefs)
        tagger.add_narrators_to_styles()
        self.assertEqual(tool.metadata.styles, {'R.C. Bray'})

    def test_add_narrators_no_force_keeps_existing(self):
        tool = self._album_tool()
        tool.set_empty_variables()
        tool.metadata.styles.add('Old Style')
        tool.narrator = [{'name': 'R.C. Bray'}]
        tagger = TagTool(tool, Prefs)
        tagger.add_narrators_to_styles()
        self.assertEqual(tool.metadata.styles, {'Old Style'})

    def test_add_authors_contributor_skipped(self):
        tool = self._album_tool()
        tool.author = [{'name': 'Andy Weir'},
                       {'name': 'Bob - Narrator'}]
        tagger = TagTool(tool, Prefs)
        tagger.add_authors_to_moods()
        self.assertEqual(tool.metadata.moods, {'Andy Weir'})

    def test_add_similar_none_noop(self):
        tool = self._album_tool()
        tool.similar = None
        tagger = TagTool(tool, Prefs)
        tagger.add_similar()
        self.assertEqual(tool.metadata.similar, set())


if __name__ == '__main__':
    unittest.main()
