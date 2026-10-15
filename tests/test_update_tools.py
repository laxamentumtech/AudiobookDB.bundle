# -*- coding: utf-8 -*-
"""Tests for Contents/Code/update_tools.py against recorded legacy fixtures."""

import os
import sys
import json
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import plex_shim  # noqa: F401,E402  (framework fakes must load first)

from plex_shim import Log, Prefs  # noqa: E402

import update_tools  # noqa: E402
from update_tools import (  # noqa: E402
    UpdateTool, AlbumUpdateTool, ArtistUpdateTool, TagTool,
)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')


def load_fixture(name):
    with open(os.path.join(FIXTURES, 'legacy', name), 'rb') as f:
        return json.loads(f.read().decode('utf-8'))


class FakeMedia(object):
    def __init__(self, **kw):
        self.title = kw.get('title', 'Some Title')
        for key, val in kw.items():
            setattr(self, key, val)


class FakeMetadata(object):
    def __init__(self, id='B00B5HZGUG_us'):
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
    Prefs['region'] = 'us'
    Prefs['logging_level'] = 'INFO'
    Prefs['keep_existing_genres'] = False
    Prefs['store_author_as_mood'] = True
    Prefs['sort_author_by_last_name'] = True
    Prefs['simplify_title'] = False
    return Prefs


def make_album(metadata=None, force=False):
    return AlbumUpdateTool(
        'books', force, plex_shim.Locale.Language.English, FakeMedia(),
        metadata if metadata is not None else FakeMetadata(), _prefs())


def make_artist(metadata=None, force=False):
    return ArtistUpdateTool(
        'authors', force, plex_shim.Locale.Language.English, FakeMedia(),
        metadata if metadata is not None else FakeMetadata(), _prefs())


class TestUpdateToolBuildUrl(unittest.TestCase):
    def test_books_url_with_region(self):
        helper = make_album()
        self.assertEqual(
            helper.build_url(),
            'https://api.audnex.us/books/B00B5HZGUG?region=us'
        )

    def test_authors_url_region_appended_to_id(self):
        metadata = FakeMetadata(id='B00G0WYW92')
        helper = make_artist(metadata)
        self.assertEqual(
            helper.build_url(),
            'https://api.audnex.us/authors/B00G0WYW92?region=us'
        )
        self.assertEqual(metadata.id, 'B00G0WYW92_us')

    def test_region_override_pref(self):
        helper = make_album()
        del helper.region
        Prefs['region'] = 'uk'
        try:
            self.assertEqual(
                helper.build_url(),
                'https://api.audnex.us/books/B00B5HZGUG?region=uk'
            )
        finally:
            Prefs['region'] = 'us'


class TestCleanupHtml(unittest.TestCase):
    def test_books_synopsis(self):
        helper = make_album()
        helper.synopsis = '<p>Para one</p>\n<br />\n<ul><li>item</li></ul>'
        helper.cleanup_html()
        self.assertEqual(helper.synopsis, 'Para one\n\n\n \u2022 item')

    def test_authors_description(self):
        helper = make_artist()
        helper.description = '<p>Bio text</p>'
        helper.cleanup_html()
        self.assertEqual(helper.description, 'Bio text')


class TestReplaceHtmlSpecial(unittest.TestCase):
    def test_lists_and_paragraphs(self):
        helper = make_album()
        out = helper.replace_html_special('<ul><li>a</li><li>b</li></ul>')
        self.assertEqual(out, '\u2022 a\n \u2022 b')

    def test_no_markup(self):
        helper = make_album()
        self.assertEqual(helper.replace_html_special('plain'), 'plain')


class TestCollectMetadataToLog(unittest.TestCase):
    def test_books(self):
        helper = make_album()
        helper.parse_api_response(load_fixture('book_detail.json'))
        data = helper.collect_metadata_to_log()
        self.assertEqual(data[0], {'ASIN': 'B00B5HZGUG_us'})
        keys = [list(d.keys())[0] for d in data[1:]]
        self.assertEqual(
            keys,
            ['Book poster URL', 'Book publisher', 'Book release date',
             'Book sort title', 'Book summary', 'Book title']
        )
        self.assertEqual(data[1]['Book poster URL'],
                         load_fixture('book_detail.json')['image'])

    def test_authors(self):
        helper = make_artist()
        helper.parse_api_response(load_fixture('author_detail.json'))
        data = helper.collect_metadata_to_log()
        self.assertEqual(data[0], {'ASIN': 'B00B5HZGUG_us'})
        keys = [list(d.keys())[0] for d in data[1:]]
        self.assertEqual(
            keys,
            ['Author bio', 'Author name', 'Author poster URL',
             'Author sort name', 'Similar Authors']
        )
        self.assertEqual(
            data[5]['Similar Authors'],
            ', '.join(a['name'] for a in
                      load_fixture('author_detail.json')['similar'])
        )


class TestCollectMetadataArrsToLog(unittest.TestCase):
    def test_books_typo_branch(self):
        # Legacy quirk (LEGACY_ISSUES #2): books compare against the
        # singular 'book', so book arrays are never logged.
        helper = make_album()
        helper.parse_api_response(load_fixture('book_detail.json'))
        arrs = helper.collect_metadata_arrs_to_log()
        self.assertEqual(len(arrs), 1)
        self.assertEqual(list(arrs[0].keys()), ['Genres'])

    def test_singular_book_includes_arrays(self):
        helper = make_album()
        helper.content_type = 'book'
        helper.parse_api_response(load_fixture('book_detail.json'))
        arrs = helper.collect_metadata_arrs_to_log()
        self.assertEqual(len(arrs), 3)
        self.assertEqual(
            [list(a.keys())[0] for a in arrs],
            ['Genres', 'Moods (Authors)', 'Styles (Narrators)']
        )


class TestExtractFromId(unittest.TestCase):
    def test_extract_asin_with_region(self):
        helper = make_album()
        self.assertEqual(helper.extract_asin_from_id(), 'B00B5HZGUG')

    def test_extract_asin_bare(self):
        helper = make_artist(FakeMetadata(id='B00G0WYW92'))
        self.assertEqual(helper.extract_asin_from_id(), 'B00G0WYW92')

    def test_extract_region_from_id(self):
        helper = make_album()
        self.assertEqual(helper.extract_region_from_id(), 'us')

    def test_extract_region_bare_id_appends_pref(self):
        metadata = FakeMetadata(id='B00G0WYW92')
        helper = make_artist(metadata)
        self.assertEqual(helper.extract_region_from_id(), 'us')
        self.assertEqual(metadata.id, 'B00G0WYW92_us')

    def test_get_preferred_region_class_attr(self):
        helper = make_album()
        self.assertEqual(helper.get_preferred_region(), 'us')

    def test_get_preferred_region_fallback_pref(self):
        helper = make_album()
        del helper.region
        self.assertEqual(helper.get_preferred_region(), 'us')


class TestLogUpdateMetadata(unittest.TestCase):
    def test_books_smoke(self):
        helper = make_album()
        helper.parse_api_response(load_fixture('book_detail.json'))
        helper.metadata.title = 'The Martian'
        Log.Clear()
        helper.log_update_metadata()
        messages = [e[1] for e in Log.entries]
        self.assertIn(
            '-' * 35 + 'FINALIZED: The Martian, ID: B00B5HZGUG_us' + '-' * 35,
            messages
        )
        self.assertGreater(len(Log.entries), 2)

    def test_authors_smoke(self):
        helper = make_artist()
        helper.parse_api_response(load_fixture('author_detail.json'))
        helper.metadata.title = 'Andy Weir'
        Log.Clear()
        helper.log_update_metadata()
        self.assertIn(
            '-' * 35 + 'FINALIZED: Andy Weir, ID: B00B5HZGUG_us' + '-' * 35,
            [e[1] for e in Log.entries]
        )


class TestAlbumParseApiResponse(unittest.TestCase):
    def test_book_detail(self):
        helper = make_album()
        helper.parse_api_response(load_fixture('book_detail.json'))
        fixture = load_fixture('book_detail.json')
        self.assertEqual(helper.title, 'The Martian')
        self.assertEqual(helper.subtitle, '')
        self.assertEqual(helper.synopsis, fixture['summary'])
        self.assertEqual(helper.author, fixture['authors'])
        self.assertEqual(helper.narrator, fixture['narrators'])
        self.assertEqual(helper.genres, fixture['genres'])
        self.assertEqual(helper.rating, fixture['rating'])
        self.assertEqual(helper.studio, 'Podium Publishing')
        self.assertEqual(helper.date, '2013-03-22T00:00:00.000Z')
        self.assertEqual(helper.thumb, fixture['image'])
        self.assertEqual(helper.series, '')
        self.assertEqual(helper.volume, '')
        self.assertIsNone(helper.similar)

    def test_book_detail_series(self):
        helper = make_album()
        fixture = load_fixture('book_detail_series.json')
        helper.parse_api_response(fixture)
        self.assertEqual(helper.title, fixture['title'])
        self.assertEqual(helper.subtitle, fixture['subtitle'])
        self.assertEqual(helper.series, 'Dune')
        self.assertEqual(helper.volume, 'Book 1')
        self.assertEqual(helper.series2, 'The Dune Sequence')
        self.assertEqual(helper.volume2, 'Book 12')

    def test_empty_response(self):
        helper = make_album()
        helper.parse_api_response({})
        self.assertIsNone(helper.date)
        self.assertIsNone(helper.genres)
        self.assertIsNone(helper.rating)
        self.assertEqual(helper.series, '')
        self.assertEqual(helper.subtitle, '')
        self.assertEqual(helper.thumb, '')
        self.assertIsNone(helper.similar)


class TestAlbumSetEmptyVariables(unittest.TestCase):
    def test_values(self):
        helper = make_album()
        helper.set_empty_variables()
        self.assertIsNone(helper.date)
        self.assertIsNone(helper.genres)
        self.assertIsNone(helper.rating)
        self.assertEqual(helper.series, '')
        self.assertEqual(helper.series2, '')
        self.assertIsNone(helper.similar)
        self.assertEqual(helper.subtitle, '')
        self.assertEqual(helper.thumb, '')
        self.assertEqual(helper.volume, '')
        self.assertEqual(helper.volume2, '')


class TestSetMetadataDate(unittest.TestCase):
    def test_no_date_no_change(self):
        helper = make_album()
        metadata = helper.metadata
        helper.date = None
        helper.set_metadata_date()
        self.assertIsNone(metadata.originally_available_at)

    def test_sets_when_empty(self):
        helper = make_album()
        helper.date = '2013-03-22'
        helper.set_metadata_date()
        self.assertEqual(helper.metadata.originally_available_at, '2013-03-22')

    def test_keeps_existing_without_force(self):
        helper = make_album()
        helper.metadata.originally_available_at = '2000-01-01'
        helper.date = '2013-03-22'
        helper.set_metadata_date()
        self.assertEqual(helper.metadata.originally_available_at, '2000-01-01')

    def test_force_overwrites(self):
        helper = make_album(force=True)
        helper.metadata.originally_available_at = '2000-01-01'
        helper.date = '2013-03-22'
        helper.set_metadata_date()
        self.assertEqual(helper.metadata.originally_available_at, '2013-03-22')


class TestSetMetadataRating(unittest.TestCase):
    def test_rating_times_two(self):
        helper = make_album()
        helper.rating = 4.8
        helper.set_metadata_rating()
        self.assertEqual(helper.metadata.rating, 9.6)

    def test_none_rating_no_change(self):
        helper = make_album()
        helper.rating = None
        helper.metadata.rating = 1.0
        helper.set_metadata_rating()
        self.assertEqual(helper.metadata.rating, 1.0)


class TestSetMetadataSummary(unittest.TestCase):
    def test_sets_when_empty(self):
        helper = make_album()
        helper.synopsis = '<p>Hi there</p>'
        helper.set_metadata_summary()
        self.assertEqual(helper.metadata.summary, 'Hi there')

    def test_keeps_existing_without_force(self):
        helper = make_album()
        helper.metadata.summary = 'Old'
        helper.synopsis = 'New'
        helper.set_metadata_summary()
        self.assertEqual(helper.metadata.summary, 'Old')

    def test_force_overwrites(self):
        helper = make_album(force=True)
        helper.metadata.summary = 'Old'
        helper.synopsis = 'New'
        helper.set_metadata_summary()
        self.assertEqual(helper.metadata.summary, 'New')


class TestSetMetadataStudio(unittest.TestCase):
    def test_sets_when_empty(self):
        helper = make_album()
        helper.studio = 'Podium Publishing'
        helper.set_metadata_studio()
        self.assertEqual(helper.metadata.studio, 'Podium Publishing')

    def test_force_overwrites(self):
        helper = make_album(force=True)
        helper.metadata.studio = 'Old'
        helper.studio = 'New'
        helper.set_metadata_studio()
        self.assertEqual(helper.metadata.studio, 'New')


class TestSetMetadataSortTitle(unittest.TestCase):
    def test_plain_title(self):
        helper = make_album()
        helper.set_empty_variables()
        helper.title = 'The Martian'
        helper.metadata.title = 'The Martian'
        helper.set_metadata_sort_title()
        self.assertEqual(helper.metadata.title_sort, 'The Martian')

    def test_series_with_volume(self):
        helper = make_album()
        helper.set_empty_variables()
        helper.title = 'Dune'
        helper.metadata.title = 'Dune'
        helper.series = 'Dune'
        helper.volume = 'Book 1'
        helper.set_metadata_sort_title()
        self.assertEqual(helper.metadata.title_sort, 'Dune, Book 1 - Dune')

    def test_series_without_volume_uses_subtitle_rule(self):
        helper = make_album()
        helper.set_empty_variables()
        helper.title = 'Dune'
        helper.subtitle = 'The Original'
        helper.metadata.title = 'Dune: The Original'
        helper.series = 'Dune'
        helper.volume = ''
        helper.set_metadata_sort_title()
        self.assertEqual(helper.metadata.title_sort, 'Dune: The Original')


class TestSetMetadataTags(unittest.TestCase):
    def test_book_tags(self):
        helper = make_album()
        fixture = load_fixture('book_detail.json')
        helper.parse_api_response(fixture)
        helper.set_metadata_tags()
        self.assertEqual(
            helper.metadata.genres,
            {g['name'] for g in fixture['genres']}
        )
        self.assertEqual(
            helper.metadata.moods,
            {a['name'] for a in fixture['authors']}
        )
        self.assertEqual(
            helper.metadata.styles,
            {n['name'] for n in fixture['narrators']}
        )

    def test_force_clears_moods_and_styles(self):
        helper = make_album(force=True)
        fixture = load_fixture('book_detail.json')
        helper.parse_api_response(fixture)
        helper.metadata.moods.add('Stale')
        helper.metadata.styles.add('Stale')
        helper.set_metadata_tags()
        self.assertNotIn('Stale', helper.metadata.moods)
        self.assertNotIn('Stale', helper.metadata.styles)

    def test_keep_existing_genres(self):
        Prefs['keep_existing_genres'] = True
        try:
            helper = make_album()
            fixture = load_fixture('book_detail.json')
            helper.parse_api_response(fixture)
            helper.metadata.genres.add('Existing')
            helper.set_metadata_tags()
            self.assertEqual(helper.metadata.genres, {'Existing'})
        finally:
            Prefs['keep_existing_genres'] = False

    def test_series_to_moods(self):
        helper = make_album()
        fixture = load_fixture('book_detail_series.json')
        helper.parse_api_response(fixture)
        helper.set_metadata_tags()
        self.assertIn('Series: Dune', helper.metadata.moods)
        self.assertIn('Series: The Dune Sequence', helper.metadata.moods)


class TestSetMetadataTitle(unittest.TestCase):
    def test_plain(self):
        helper = make_album()
        helper.title = 'The Martian'
        helper.subtitle = ''
        helper.set_metadata_title()
        self.assertEqual(helper.metadata.title, 'The Martian')

    def test_with_subtitle(self):
        helper = make_album()
        helper.title = 'Dune'
        helper.subtitle = 'The Original'
        helper.set_metadata_title()
        self.assertEqual(helper.metadata.title, 'Dune: The Original')

    def test_simplify_title_pref(self):
        helper = make_album()
        Prefs['simplify_title'] = True
        try:
            helper.title = 'Dune, Book 1 (Unabridged)'
            helper.subtitle = 'The Original'
            helper.set_metadata_title()
            # Legacy: series-part regex runs before the abridged strip and
            # requires the series part to be terminal, so only the
            # "(Unabridged)" suffix is removed.
            self.assertEqual(helper.metadata.title, 'Dune, Book 1')
        finally:
            Prefs['simplify_title'] = False


class TestSimplifyTitle(unittest.TestCase):
    def _t(self, title):
        helper = make_album()
        helper.title = title
        return helper.simplify_title()

    def test_series_part(self):
        self.assertEqual(self._t('Dune, Book 1'), 'Dune')

    def test_abridged(self):
        self.assertEqual(self._t('The Story (Unabridged)'), 'The Story')

    def test_plain(self):
        self.assertEqual(self._t('Plain Title'), 'Plain Title')


class TestVolumePrefix(unittest.TestCase):
    def _t(self, string):
        return make_album().volume_prefix(string)

    def test_bare_number(self):
        self.assertEqual(self._t('1'), 'Book 1')

    def test_existing_prefix(self):
        self.assertEqual(self._t('Book 1'), 'Book 1')

    def test_other_prefix(self):
        self.assertEqual(self._t('Vol. 2'), 'Book Vol. 2')


class FakeUrlopen(object):
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data

    def close(self):
        pass


def _jpeg(width, height):
    # Minimal JPEG: SOI, APP0, SOF0 (height/width), EOI.
    import struct
    sof0 = (
        b'\xff\xc0' + struct.pack('>H', 17) + b'\x08' +
        struct.pack('>HH', height, width) + b'\x01' + b'\x01\x22\x00'
    )
    app0 = b'\xff\xe0' + struct.pack('>H', 16) + b'JFIF\x00\x01\x01\x00' \
        b'\x00\x01\x00\x01\x00\x00'
    return b'\xff\xd8' + app0 + sof0 + b'\xff\xd9'


class TestGetSquareImage(unittest.TestCase):
    def _helper(self):
        return make_artist()

    def _with_image(self, data):
        def urlopen(url):
            return FakeUrlopen(data)
        update_tools.urllib.urlopen = urlopen
        try:
            return
        finally:
            pass

    def test_portrait_cropped_to_square(self):
        helper = self._helper()
        update_tools.urllib.urlopen = lambda url: FakeUrlopen(
            _jpeg(width=100, height=200))
        out = helper.get_square_image('http://x/img.jpg')
        self.assertEqual(
            out, 'http://x/img.__01_SX100_CR0,0,100,100__.jpg'
        )

    def test_landscape_cropped_to_square(self):
        helper = self._helper()
        update_tools.urllib.urlopen = lambda url: FakeUrlopen(
            _jpeg(width=400, height=200))
        out = helper.get_square_image('http://x/img.jpg')
        # Legacy quirk: division is int division on py2 ('100') and float
        # division on py3 ('100.0').
        padding = '100' if sys.version_info[0] < 3 else '100.0'
        self.assertEqual(
            out, 'http://x/img.__01_SY200_CR%s,0,200,200__.jpg' % padding
        )

    def test_square_unchanged(self):
        helper = self._helper()
        update_tools.urllib.urlopen = lambda url: FakeUrlopen(
            _jpeg(width=150, height=150))
        out = helper.get_square_image('http://x/img.jpg')
        self.assertEqual(out, 'http://x/img.jpg')

    def test_error_returns_original(self):
        helper = self._helper()
        def urlopen(url):
            raise IOError('nope')
        update_tools.urllib.urlopen = urlopen
        Log.Clear()
        out = helper.get_square_image('http://x/img.jpg')
        self.assertEqual(out, 'http://x/img.jpg')
        levels = [e[0] for e in Log.entries]
        self.assertIn('ERROR', levels)


class TestArtistParseApiResponse(unittest.TestCase):
    def test_author_detail(self):
        helper = make_artist()

        def urlopen(url):
            raise IOError('nope')
        update_tools.urllib.urlopen = urlopen
        helper.parse_api_response(load_fixture('author_detail.json'))
        fixture = load_fixture('author_detail.json')
        self.assertEqual(helper.name, 'Andy Weir')
        self.assertEqual(helper.description, fixture['description'])
        self.assertEqual(helper.genres, fixture['genres'])
        self.assertEqual(helper.thumb, fixture['image'])
        self.assertEqual(helper.similar, fixture['similar'])

    def test_empty_response(self):
        helper = make_artist()
        helper.parse_api_response({})
        self.assertIsNone(helper.genres)
        self.assertIsNone(helper.similar)
        self.assertEqual(helper.thumb, '')


class TestArtistSetEmptyVariables(unittest.TestCase):
    def test_values(self):
        helper = make_artist()
        helper.set_empty_variables()
        self.assertIsNone(helper.date)
        self.assertIsNone(helper.genres)
        self.assertIsNone(helper.similar)
        self.assertEqual(helper.thumb, '')


class TestArtistSetMetadataDescription(unittest.TestCase):
    def test_sets_when_empty(self):
        helper = make_artist()
        helper.description = '<p>Bio</p>'
        helper.set_metadata_description()
        self.assertEqual(helper.metadata.summary, 'Bio')

    def test_keeps_existing_without_force(self):
        helper = make_artist()
        helper.metadata.summary = 'Old'
        helper.description = 'New'
        helper.set_metadata_description()
        self.assertEqual(helper.metadata.summary, 'Old')


class TestArtistSetMetadataSortTitle(unittest.TestCase):
    def _run(self, name, title, pref=True):
        helper = make_artist()
        Prefs['sort_author_by_last_name'] = pref
        helper.name = name
        helper.metadata.title = title
        helper.set_metadata_sort_title()
        return helper.metadata.title_sort

    def test_two_part_name(self):
        self.assertEqual(
            self._run('Andy Weir', 'Andy Weir'), 'Weir, Andy'
        )

    def test_single_word_keeps_title(self):
        self.assertEqual(
            self._run('Weir', 'Weir'), 'Weir'
        )

    def test_suffix_kept(self):
        # Legacy quirk: group(1) includes the space before the suffix and
        # group(3) keeps its leading comma, yielding "Doe, John,  Jr."
        self.assertEqual(
            self._run('John Doe Jr.', 'John Doe Jr.'), 'Doe, John,  Jr.'
        )

    def test_pref_false_keeps_title(self):
        self.assertEqual(
            self._run('Andy Weir', 'Andy Weir', pref=False),
            'Andy Weir'
        )


class TestArtistSetMetadataTags(unittest.TestCase):
    def test_tags_and_similar(self):
        helper = make_artist()
        fixture = load_fixture('author_detail.json')
        helper.parse_api_response(fixture)
        helper.set_metadata_tags()
        self.assertEqual(
            helper.metadata.genres, {g['name'] for g in fixture['genres']}
        )
        self.assertEqual(
            helper.metadata.similar, {a['name'] for a in fixture['similar']}
        )


class TestArtistSetMetadataTitle(unittest.TestCase):
    def test_sets_title(self):
        helper = make_artist()
        helper.name = 'Andy Weir'
        helper.set_metadata_title()
        self.assertEqual(helper.metadata.title, 'Andy Weir')

    def test_keeps_existing_without_force(self):
        helper = make_artist()
        helper.metadata.title = 'Old'
        helper.name = 'New'
        helper.set_metadata_title()
        self.assertEqual(helper.metadata.title, 'Old')


class TestTagToolGenres(unittest.TestCase):
    def _helper_with_genres(self, keep=False):
        Prefs['keep_existing_genres'] = keep
        helper = make_album()
        helper.genres = [{'name': 'SciFi'}, {'name': ''}]
        return helper

    def test_replaces_when_pref_off(self):
        helper = self._helper_with_genres()
        TagTool(helper, Prefs).add_genres()
        self.assertEqual(helper.metadata.genres, {'SciFi'})

    def test_keeps_when_pref_on(self):
        helper = self._helper_with_genres(keep=True)
        helper.metadata.genres.add('Existing')
        TagTool(helper, Prefs).add_genres()
        self.assertEqual(helper.metadata.genres, {'Existing'})

    def test_no_genres_no_change(self):
        helper = make_album()
        helper.genres = None
        TagTool(helper, Prefs).add_genres()
        self.assertEqual(helper.metadata.genres, set())


class TestTagToolNarrators(unittest.TestCase):
    def test_adds_narrators(self):
        helper = make_album()
        helper.narrator = [{'name': '  Narr  '}]
        TagTool(helper, Prefs).add_narrators_to_styles()
        self.assertEqual(helper.metadata.styles, {'Narr'})

    def test_existing_without_force_untouched(self):
        helper = make_album()
        helper.narrator = [{'name': 'N'}]
        helper.metadata.styles.add('Existing')
        TagTool(helper, Prefs).add_narrators_to_styles()
        self.assertEqual(helper.metadata.styles, {'Existing'})

    def test_force_replaces(self):
        helper = make_album(force=True)
        helper.narrator = [{'name': 'N'}]
        helper.metadata.styles.add('Existing')
        TagTool(helper, Prefs).add_narrators_to_styles()
        self.assertEqual(helper.metadata.styles, {'N'})


class TestTagToolAuthors(unittest.TestCase):
    def test_adds_authors_skips_contributors(self):
        helper = make_album()
        helper.author = [{'name': 'Andy Weir'}, {'name': 'Jane - Editor'}]
        TagTool(helper, Prefs).add_authors_to_moods()
        self.assertEqual(helper.metadata.moods, {'Andy Weir'})

    def test_force_replaces(self):
        # Legacy: the tagger does NOT clear moods itself; only the album's
        # set_metadata_tags() pre-clears moods/styles on force.
        helper = make_album(force=True)
        helper.author = [{'name': 'A'}]
        helper.metadata.moods.add('Stale')
        TagTool(helper, Prefs).add_authors_to_moods()
        self.assertEqual(helper.metadata.moods, {'A', 'Stale'})


class TestTagToolSeries(unittest.TestCase):
    def test_adds_series(self):
        helper = make_album()
        helper.series = 'Dune'
        helper.series2 = 'The Dune Sequence'
        TagTool(helper, Prefs).add_series_to_moods()
        self.assertEqual(
            helper.metadata.moods,
            {'Series: Dune', 'Series: The Dune Sequence'}
        )

    def test_no_series(self):
        helper = make_album()
        helper.series = ''
        helper.series2 = ''
        TagTool(helper, Prefs).add_series_to_moods()
        self.assertEqual(helper.metadata.moods, set())


class TestTagToolSimilar(unittest.TestCase):
    def test_adds_similar(self):
        helper = make_artist()
        helper.similar = [{'name': 'Blake Crouch'}, {'name': 'X'}]
        TagTool(helper, Prefs).add_similar()
        self.assertEqual(helper.metadata.similar, {'Blake Crouch', 'X'})

    def test_none_no_change(self):
        helper = make_artist()
        helper.similar = None
        TagTool(helper, Prefs).add_similar()
        self.assertEqual(helper.metadata.similar, set())


class TestTagToolClear(unittest.TestCase):
    def test_clear_moods(self):
        helper = make_album()
        helper.metadata.moods.add('X')
        TagTool(helper, Prefs).clear_moods()
        self.assertEqual(helper.metadata.moods, set())

    def test_clear_styles(self):
        helper = make_album()
        helper.metadata.styles.add('X')
        TagTool(helper, Prefs).clear_styles()
        self.assertEqual(helper.metadata.styles, set())
