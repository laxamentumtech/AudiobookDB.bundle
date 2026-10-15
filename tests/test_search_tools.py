# -*- coding: utf-8 -*-
"""Tests for Contents/Code/search_tools.py against recorded legacy fixtures."""

import os
import sys
import json
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import plex_shim  # noqa: F401,E402  (framework fakes must load first)

from plex_shim import Log, Prefs, _Results  # noqa: E402

from search_tools import (  # noqa: E402
    SearchTool, AlbumSearchTool, ArtistSearchTool, ScoreTool,
)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')


def load_fixture(name):
    """Load a legacy fixture; json.loads is patched (viewkeys dicts)."""
    with open(os.path.join(FIXTURES, 'legacy', name), 'rb') as f:
        return json.loads(f.read().decode('utf-8'))


def as_legacy_dicts(obj):
    """Round-trip through patched json.loads so dicts get ``viewkeys()``."""
    return json.loads(json.dumps(obj))


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
    Prefs['region'] = 'us'
    Prefs['logging_level'] = 'INFO'
    return SearchTool(
        content_type, plex_shim.Locale.Language.English, manual,
        media if media is not None else FakeMedia(), Prefs, _Results())


def make_album(media=None, manual=False):
    Prefs['region'] = 'us'
    Prefs['logging_level'] = 'INFO'
    return AlbumSearchTool(
        'books', plex_shim.Locale.Language.English, manual,
        media if media is not None else FakeMedia(), Prefs, _Results())


def make_artist(media=None, manual=False):
    Prefs['region'] = 'us'
    Prefs['logging_level'] = 'INFO'
    return ArtistSearchTool(
        'authors', plex_shim.Locale.Language.English, manual,
        media if media is not None else FakeMedia(), Prefs, _Results())


class FakeScoreHelper(object):
    def __init__(self, media=None, lang=None):
        self.media = media
        self.lang = lang if lang is not None else plex_shim.Locale.Language.English


class TestSearchToolBuildUrl(unittest.TestCase):
    def test_books_build_url(self):
        tool = make_album(FakeMedia(album='The Martian', artist='Andy Weir'))
        tool.normalize_name()
        url = tool.build_url('title=The%20Martian')
        self.assertEqual(
            url,
            'https://api.audible.com/1.0/catalog/products'
            '?response_groups=contributors,product_desc,product_attrs'
            '&num_results=25&products_sort_by=Relevance&title=The%20Martian'
        )

    def test_authors_build_url(self):
        tool = make('authors', FakeMedia(artist='Andy Weir'))
        url = tool.build_url('name=Andy%20Weir')
        self.assertEqual(
            url, 'https://api.audnex.us/authors?region=us&name=Andy%20Weir'
        )

    def test_build_url_asin_override_books(self):
        tool = make_album(FakeMedia(
            album='The Martian B00B5HZGUG', artist='Andy Weir'))
        tool.normalize_name()
        url = tool.build_url('ignored')
        self.assertEqual(
            url,
            'https://api.audible.com/1.0/catalog/products'
            '?response_groups=contributors,product_desc,product_attrs'
            '&num_results=25&products_sort_by=Relevance'
            '&&keywords=B00B5HZGUG'
        )


class TestSearchToolCheckForAsin(unittest.TestCase):
    def test_books_from_filename(self):
        tool = make('books', FakeMedia(filename='the%20martian%20B00B5HZGUG'))
        self.assertEqual(tool.check_for_asin(), 'B00B5HZGUG_us')

    def test_books_from_manual(self):
        tool = make('books', FakeMedia(album='The Martian B00B5HZGUG'))
        self.assertEqual(tool.check_for_asin(), 'B00B5HZGUG_us')

    def test_artists_from_manual(self):
        # Legacy quirk (LEGACY_ISSUES #3): artist quick-match returns
        # ASIN_region even though artist result IDs are bare ASINs.
        tool = make('authors', FakeMedia(artist='Andy Weir B00G0WYW92'))
        self.assertEqual(tool.check_for_asin(), 'B00G0WYW92_us')

    def test_no_asin(self):
        tool = make('books', FakeMedia(album='The Martian'))
        self.assertIsNone(tool.check_for_asin())

    def test_artist_manual_falls_back_to_album_none(self):
        # No album, no artist -> search_asin(None) -> None
        tool = make('authors', FakeMedia())
        self.assertIsNone(tool.check_for_asin())


class TestSearchToolRegion(unittest.TestCase):
    def test_check_for_region_from_title(self):
        tool = make('books', FakeMedia(album='The Martian [uk]'))
        tool.check_for_region('The Martian [uk]')
        self.assertEqual(tool.region_override, 'uk')

    def test_check_for_region_default(self):
        tool = make('books', FakeMedia(album='The Martian'))
        tool.check_for_region('The Martian')
        self.assertEqual(tool.region_override, 'us')

    def test_search_region(self):
        tool = make('books', FakeMedia())
        self.assertEqual(tool.search_region('hello [uk] world').group(0), 'uk')
        self.assertIsNone(tool.search_region('hello world'))
        self.assertIsNone(tool.search_region(None))


class TestSearchToolHelpers(unittest.TestCase):
    def test_clear_contributor_text(self):
        tool = make('books', FakeMedia())
        self.assertEqual(tool.clear_contributor_text('A - B'), 'A')
        self.assertEqual(tool.clear_contributor_text('Plain'), 'Plain')

    def test_log_search_url(self):
        tool = make('books', FakeMedia())
        Prefs['logging_level'] = 'DEBUG'
        Log.Clear()
        tool.log_search_url('http://example.com/search')
        self.assertEqual(
            [e for e in Log.entries if e[0] == 'DEBUG'],
            [('DEBUG', 'Search URL: %s', ('http://example.com/search',))]
        )
        Prefs['logging_level'] = 'INFO'

    def test_override_with_asin_books(self):
        # Legacy URL quirk: query param starts with '&' while the region
        # params already end with '&', producing '&&keywords=' (pinned).
        tool = make_album(FakeMedia(album='x B00B5HZGUG'))
        match = tool.search_asin('B00B5HZGUG')
        url = tool.override_with_asin(match, 'uk')
        self.assertEqual(
            url,
            'https://api.audible.co.uk/1.0/catalog/products'
            '?response_groups=contributors,product_desc,product_attrs'
            '&num_results=25&products_sort_by=Relevance&&keywords=B00B5HZGUG'
        )

    def test_override_with_asin_authors(self):
        tool = make('authors', FakeMedia(artist='x B00G0WYW92'))
        match = tool.search_asin('B00G0WYW92')
        url = tool.override_with_asin(match)
        self.assertEqual(
            url, 'https://api.audnex.us/authors/B00G0WYW92?region=us'
        )

    def test_pre_process_title_returns_url_on_asin(self):
        tool = make_album(FakeMedia(
            album='The Martian B00B5HZGUG', artist='Andy Weir'))
        tool.normalize_name()
        url = tool.pre_process_title()
        self.assertIn('products_sort_by=Relevance&&keywords=B00B5HZGUG', url)
        self.assertTrue(url.startswith('https://api.audible.com/'))

    def test_pre_process_title_none_without_asin(self):
        tool = make_album(FakeMedia(album='The Martian', artist='Andy Weir'))
        tool.normalize_name()
        self.assertIsNone(tool.pre_process_title())

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


class TestAlbumSearchToolArgs(unittest.TestCase):
    def test_build_search_args_with_artist(self):
        tool = make_album(FakeMedia(album='The Martian', artist='Andy Weir'))
        self.assertEqual(
            tool.build_search_args(),
            'title=The%20Martian&author=Andy%20Weir'
        )

    def test_build_search_args_without_artist(self):
        tool = make_album(FakeMedia(album='The Martian'))
        self.assertEqual(tool.build_search_args(), 'keywords=The%20Martian')


class TestAlbumSearchToolPreorder(unittest.TestCase):
    def test_future_date_is_preorder(self):
        tool = make_album(FakeMedia())
        future = date(2099, 1, 1)
        self.assertTrue(tool.check_if_preorder(future))

    def test_past_date_not_preorder(self):
        tool = make_album(FakeMedia())
        past = date(2013, 3, 22)
        self.assertIsNone(tool.check_if_preorder(past))


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
    def test_fixture_products(self):
        tool = make_album(FakeMedia())
        tool.region_override = 'us'
        results = tool.parse_api_response(load_fixture('book_search.json'))
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['asin'], 'B082BHJMFF_us')
        self.assertEqual(results[0]['title'], 'The Martian')
        self.assertEqual(results[0]['author'],
                         [{'asin': 'B00G0WYW92', 'name': 'Andy Weir'}])
        self.assertEqual(results[0]['date'], '2020-01-01')
        self.assertEqual(results[0]['language'], 'english')
        self.assertEqual(results[0]['narrator'], [{'name': 'Wil Wheaton'}])
        self.assertEqual(results[0]['region'], 'us')

    def test_missing_required_keys_rejected(self):
        tool = make_album(FakeMedia())
        tool.region_override = 'us'
        response = as_legacy_dicts({'products': [
            {'asin': 'B000000000', 'title': 'Nope'},
        ]})
        self.assertEqual(tool.parse_api_response(response), [])

    def test_partial_keys_kept(self):
        tool = make_album(FakeMedia())
        tool.region_override = 'uk'
        response = as_legacy_dicts({'products': [
            {
                'asin': 'B000000001',
                'authors': [{'name': 'A'}],
                'language': 'english',
                'narrators': [{'name': 'N'}],
                'release_date': '2020-01-01',
                'title': 'Yes',
            },
        ]})
        results = tool.parse_api_response(response)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['asin'], 'B000000001_uk')


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


class TestArtistSearchToolArgs(unittest.TestCase):
    def test_build_search_args(self):
        tool = make_artist(FakeMedia(artist='Andy Weir'))
        self.assertEqual(tool.build_search_args(), 'name=Andy%20Weir')


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
        results = tool.parse_api_response(load_fixture('author_search.json'))
        self.assertEqual(len(results), 25)
        self.assertEqual(results[0], {'asin': 'B00G0WYW92',
                                      'name': 'Andy Weir'})

    def test_missing_keys_rejected(self):
        tool = make_artist(FakeMedia())
        self.assertEqual(
            tool.parse_api_response(as_legacy_dicts(
                [{'asin': 'B000000000'}])), [])


class TestScoreTool(unittest.TestCase):
    def _score(self, result_dict, index=0, year=None,
               media=None, lang=None):
        helper = FakeScoreHelper(
            media if media is not None else FakeMedia(),
            lang
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
            {'asin': 'B00G0WYW92_us', 'name': 'Andy Weir'}, media=media)
        tool.run_score_author()
        self.assertEqual(len(info), 1)
        self.assertEqual(info[0]['id'], 'B00G0WYW92_us')
        self.assertEqual(info[0]['author'], 'Andy Weir')
        self.assertEqual(info[0]['score'], 100)

    def test_run_score_book_perfect_match(self):
        media = FakeMedia(album='The Martian', artist='Andy Weir')
        result = {
            'asin': 'B00B5HZGUG_us',
            'author': [{'name': 'Andy Weir'}],
            'date': '2013-03-22',
            'language': 'english',
            'narrator': [{'name': 'R. C. Bray'}],
            'region': 'us',
            'title': 'The Martian',
        }
        tool, info = self._score(result, media=media, year=2013)
        tool.run_score_book()
        self.assertEqual(len(info), 1)
        self.assertEqual(info[0]['id'], 'B00B5HZGUG_us')
        self.assertEqual(info[0]['score'], 100)
        self.assertEqual(info[0]['date'], '2013-03-22')
        self.assertEqual(info[0]['narrator'], 'R. C. Bray')
        self.assertEqual(info[0]['region'], 'us')
        self.assertEqual(info[0]['title'], 'The Martian')
        self.assertEqual(info[0]['year'], 2013)

    def test_score_below_ignore_boundary_skipped(self):
        media = FakeMedia(album='The Martian', artist='Andy Weir')
        result = {
            'asin': 'B000000000_us',
            'author': [{'name': 'Frank Herbert'}],
            'date': '1965-01-01',
            'language': 'english',
            'narrator': [{'name': 'N'}],
            'region': 'us',
            'title': 'Dune Messiah The Golden',
        }
        tool, info = self._score(result, media=media)
        tool.run_score_book()
        self.assertEqual(info, [])

    def test_index_penalty(self):
        media = FakeMedia(album='The Martian', artist='Andy Weir')
        result = {
            'asin': 'B000000000_us',
            'author': [{'name': 'Andy Weir'}],
            'date': '2013-03-22',
            'language': 'english',
            'narrator': [{'name': 'N'}],
            'region': 'us',
            'title': 'The Martian',
        }
        _, info = self._score(result, index=3, media=media)
        info2 = []
        tool2 = ScoreTool(
            FakeScoreHelper(media), 3, info2,
            plex_shim.Locale.Language.English,
            plex_shim.Util.LevenshteinDistance, result, None)
        tool2.run_score_book()
        self.assertEqual(info2[0]['score'], 97)

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
            'asin': 'B000000000_us',
            'author': [{'name': 'Andy Weir'}],
            'date': '2013-03-22',
            'language': 'german',
            'narrator': [{'name': 'N'}],
            'region': 'us',
            'title': 'The Martian',
        }
        tool, info = self._score(result, media=media)
        tool.run_score_book()
        self.assertEqual(info[0]['score'], 98)
