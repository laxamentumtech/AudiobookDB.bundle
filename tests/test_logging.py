# -*- coding: utf-8 -*-
"""Tests for Contents/Code/logging.py (Logging class)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import plex_shim  # noqa: F401,E402  (framework fakes must load first)

from logging import Logging  # noqa: E402


class LoggingTestCaseBase(unittest.TestCase):
    def setUp(self):
        self.log = Logging()
        plex_shim.Log.Clear()

    def _set_level(self, level):
        plex_shim.Prefs['logging_level'] = level


class TestDebug(LoggingTestCaseBase):
    def test_debug_passes_at_debug_level(self):
        self._set_level('DEBUG')
        self.log.debug('hello %s', 'world')
        self.assertEqual(plex_shim.Log.entries[0][0], 'DEBUG')
        self.assertEqual(plex_shim.Log.entries[0][1], 'hello %s')
        self.assertEqual(plex_shim.Log.entries[0][2], ('world',))

    def test_debug_swallowed_below_debug(self):
        for level in ('INFO', 'WARN', 'ERROR'):
            self._set_level(level)
            self.log.debug('hidden')
        self.assertEqual(plex_shim.Log.entries, [])


class TestInfo(LoggingTestCaseBase):
    def test_info_passes_at_info(self):
        self._set_level('INFO')
        self.log.info('msg %s', 'x')
        self.assertEqual(plex_shim.Log.entries[0][0], 'INFO')
        self.assertEqual(plex_shim.Log.entries[0][1], 'msg %s')
        self.assertEqual(plex_shim.Log.entries[0][2], ('x',))

    def test_info_passes_at_debug(self):
        self._set_level('DEBUG')
        self.log.info('msg')
        self.assertEqual(plex_shim.Log.entries, [('INFO', 'msg', ())])

    def test_info_swallowed_below_info(self):
        for level in ('WARN', 'ERROR'):
            self._set_level(level)
            self.log.info('hidden')
        self.assertEqual(plex_shim.Log.entries, [])


class TestWarn(LoggingTestCaseBase):
    def test_warn_passes_at_debug_info_warn(self):
        for level in ('DEBUG', 'INFO', 'WARN'):
            plex_shim.Log.Clear()
            self._set_level(level)
            self.log.warn('careful')
            self.assertEqual(plex_shim.Log.entries, [('INFO', 'careful', ())])

    def test_warn_swallowed_at_error(self):
        self._set_level('ERROR')
        self.log.warn('hidden')
        self.assertEqual(plex_shim.Log.entries, [])


class TestError(LoggingTestCaseBase):
    def test_error_passes_at_all_levels(self):
        for level in ('DEBUG', 'INFO', 'WARN', 'ERROR'):
            plex_shim.Log.Clear()
            self._set_level(level)
            self.log.error('boom %d', 1)
            self.assertEqual(
                plex_shim.Log.entries, [('ERROR', 'boom %d', (1,))])


class TestLogOutput(LoggingTestCaseBase):
    def test_log_output_debug(self):
        self._set_level('DEBUG')
        self.log.log_output('Key', 'value', 'debug')
        entry = plex_shim.Log.entries[0]
        self.assertEqual(entry[0], 'DEBUG')
        self.assertEqual(entry[1], 'Key' + ' ' * 17 + 'value')

    def test_log_output_info(self):
        self._set_level('INFO')
        self.log.log_output('K', 'v', 'info')
        entry = plex_shim.Log.entries[0]
        self.assertEqual(entry[0], 'INFO')
        self.assertEqual(entry[1], 'K' + ' ' * 19 + 'v')


class TestSeparator(LoggingTestCaseBase):
    def test_separator_plain(self):
        self._set_level('INFO')
        self.log.separator(log_level='info')
        entry = plex_shim.Log.entries[0]
        self.assertEqual(entry[0], 'INFO')
        self.assertEqual(entry[1], '-' * 70)

    def test_separator_with_msg(self):
        self._set_level('DEBUG')
        self.log.separator(msg='TITLE', log_level='debug')
        entry = plex_shim.Log.entries[0]
        self.assertEqual(entry[0], 'DEBUG')
        self.assertEqual(entry[1], '-' * 35 + 'TITLE' + '-' * 35)


class TestMetadata(LoggingTestCaseBase):
    def test_metadata_skips_falsy_values(self):
        self._set_level('INFO')
        self.log.metadata([{'A': '1'}, {'B': ''}, {'C': '3'}])
        lines = [e[1] for e in plex_shim.Log.entries]
        self.assertEqual(lines, ['A' + ' ' * 19 + '1',
                                 'C' + ' ' * 19 + '3'])

    def test_metadata_debug_level(self):
        self._set_level('DEBUG')
        self.log.metadata([{'A': '1'}], log_level='debug')
        self.assertEqual(plex_shim.Log.entries[0][0], 'DEBUG')


class TestMetadataArrs(LoggingTestCaseBase):
    def test_metadata_arrs_logs_inverted_key_value(self):
        # Legacy quirk (LEGACY_ISSUES #4): logs (value, key), not (key, value).
        self._set_level('INFO')
        self.log.metadata_arrs([{'Authors': ['A', 'B']}])
        lines = [e[1] for e in plex_shim.Log.entries]
        self.assertEqual(lines, ['A' + ' ' * 19 + 'Authors',
                                 'B' + ' ' * 19 + 'Authors'])

    def test_metadata_arrs_skips_empty(self):
        self._set_level('INFO')
        self.log.metadata_arrs([{'Authors': []}])
        self.assertEqual(plex_shim.Log.entries, [])
