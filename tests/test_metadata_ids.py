# -*- coding: utf-8 -*-
"""
Metadata ID grammar tests: parse_metadata_id / serialize_book_id /
serialize_person_id.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plex_shim  # noqa: F401  (framework globals; must stay first)

import metadata_ids


class TestParseNativeBook(unittest.TestCase):
    def test_work_only(self):
        self.assertEqual(
            metadata_ids.parse_metadata_id('book.WQQDcMBQ3qUT', 'books'),
            ('book', 'WQQDcMBQ3qUT', None)
        )

    def test_with_release(self):
        self.assertEqual(
            metadata_ids.parse_metadata_id(
                'book.WQQDcMBQ3qUT.release.dPL9fC7YnK8X', 'books'),
            ('book', 'WQQDcMBQ3qUT', 'dPL9fC7YnK8X')
        )

    def test_wrong_content_type_invalid(self):
        self.assertEqual(
            metadata_ids.parse_metadata_id('book.WQQDcMBQ3qUT', 'authors'),
            ('invalid', None, None)
        )

    def test_missing_book_id_invalid(self):
        self.assertEqual(
            metadata_ids.parse_metadata_id('book.', 'books'),
            ('invalid', None, None)
        )

    def test_missing_release_id_invalid(self):
        self.assertEqual(
            metadata_ids.parse_metadata_id('book.WQQDcMBQ3qUT.release.',
                                           'books'),
            ('invalid', None, None)
        )


class TestParseNativePerson(unittest.TestCase):
    def test_person(self):
        self.assertEqual(
            metadata_ids.parse_metadata_id('person.ypMPwXzWXaiX', 'authors'),
            ('person', 'ypMPwXzWXaiX', None)
        )

    def test_wrong_content_type_invalid(self):
        self.assertEqual(
            metadata_ids.parse_metadata_id('person.ypMPwXzWXaiX', 'books'),
            ('invalid', None, None)
        )

    def test_missing_person_id_invalid(self):
        self.assertEqual(
            metadata_ids.parse_metadata_id('person.', 'authors'),
            ('invalid', None, None)
        )


class TestParseLegacyAsin(unittest.TestCase):
    def test_bare_asin_books(self):
        self.assertEqual(
            metadata_ids.parse_metadata_id('B00B5HZGUG', 'books'),
            ('legacy', 'B00B5HZGUG', None)
        )

    def test_region_suffix_discarded(self):
        self.assertEqual(
            metadata_ids.parse_metadata_id('B00B5HZGUG_us', 'books'),
            ('legacy', 'B00B5HZGUG', None)
        )

    def test_lowercase_uppercased(self):
        self.assertEqual(
            metadata_ids.parse_metadata_id('b00b5hzgug', 'books'),
            ('legacy', 'B00B5HZGUG', None)
        )

    def test_bare_asin_authors(self):
        # The legacy string form is identical for books and people;
        # content_type disambiguates.
        self.assertEqual(
            metadata_ids.parse_metadata_id('B00G0WYW92', 'authors'),
            ('legacy', 'B00G0WYW92', None)
        )


class TestParseInvalid(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(
            metadata_ids.parse_metadata_id('', 'books'),
            ('invalid', None, None)
        )

    def test_none(self):
        self.assertEqual(
            metadata_ids.parse_metadata_id(None, 'books'),
            ('invalid', None, None)
        )

    def test_too_short(self):
        self.assertEqual(
            metadata_ids.parse_metadata_id('B00B5HZG', 'books'),
            ('invalid', None, None)
        )

    def test_too_long(self):
        self.assertEqual(
            metadata_ids.parse_metadata_id('B00B5HZGUG1', 'books'),
            ('invalid', None, None)
        )

    def test_garbage(self):
        self.assertEqual(
            metadata_ids.parse_metadata_id('not a valid id', 'books'),
            ('invalid', None, None)
        )

    def test_bad_region_suffix(self):
        # 3-char suffix is not a region.
        self.assertEqual(
            metadata_ids.parse_metadata_id('B00B5HZGUG_usa', 'books'),
            ('invalid', None, None)
        )


class TestSerialize(unittest.TestCase):
    def test_book_work_only(self):
        self.assertEqual(
            metadata_ids.serialize_book_id('WQQDcMBQ3qUT'),
            'book.WQQDcMBQ3qUT'
        )

    def test_book_with_release(self):
        self.assertEqual(
            metadata_ids.serialize_book_id('WQQDcMBQ3qUT', 'dPL9fC7YnK8X'),
            'book.WQQDcMBQ3qUT.release.dPL9fC7YnK8X'
        )

    def test_person(self):
        self.assertEqual(
            metadata_ids.serialize_person_id('ypMPwXzWXaiX'),
            'person.ypMPwXzWXaiX'
        )

    def test_empty_returns_none(self):
        self.assertIsNone(metadata_ids.serialize_book_id(''))
        self.assertIsNone(metadata_ids.serialize_person_id(''))

    def test_round_trip(self):
        parsed = metadata_ids.parse_metadata_id(
            'book.WQQDcMBQ3qUT.release.dPL9fC7YnK8X', 'books')
        self.assertEqual(parsed, ('book', 'WQQDcMBQ3qUT', 'dPL9fC7YnK8X'))
        self.assertEqual(
            metadata_ids.serialize_book_id(parsed[1], parsed[2]),
            'book.WQQDcMBQ3qUT.release.dPL9fC7YnK8X'
        )


if __name__ == '__main__':
    unittest.main()
