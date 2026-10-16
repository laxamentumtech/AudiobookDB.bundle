# Test coverage map (AudiobookDB-migrated)

Every public symbol in `Contents/Code/` mapped to the tests that exercise it.
197 tests, green on **Python 2.7** (docker `python:2.7-slim`, `make test-py2`)
and **Python 3** (`make test`).
Test files: `tests/test_logging.py` (16), `tests/test_api_client.py` (24),
`tests/test_metadata_ids.py` (23), `tests/test_search_tools.py` (65),
`tests/test_update_tools.py` (51), `tests/test_agent.py` (18).
Migrated-implementation defects are cross-referenced to `LEGACY_ISSUES.md`
as `#n`.

Harness: `tests/plex_shim.py` (fake Plex framework: `HTTP`, `Log`, `Prefs`,
`Locale`, `Agent`, `MetadataSearchResult`, `Proxy`, `String`, `Util`,
`Datetime`, `SSLError`, `CACHE_1WEEK`; injectable HTTP transport with a
`(url, method, headers, data)` request log) and `tests/py23_compat.py`
(py2↔py3 stdlib deltas; no-op under py2). Fixtures:
`tests/fixtures/audiobookdb/*.json` (see `tests/fixtures/audiobookdb/SYNTHESIZED.md`
for provenance).

## Contents/Code/logging.py — `Logging`

| Method | Tests |
|---|---|
| `debug` | `test_logging.TestDebug` (2) |
| `info` | `test_logging.TestInfo` (3) |
| `warn` | `test_logging.TestWarn` (2) |
| `error` | `test_logging.TestError` (1) |
| `log_output` | `test_logging.TestLogOutput` (2); py2 non-ASCII crash shimmed (`#12`) |
| `separator` | `test_logging.TestSeparator` (2) |
| `metadata` | `test_logging.TestMetadata` (2) |
| `metadata_arrs` | `test_logging.TestMetadataArrs` (2); inverted key/value pinned (`#4`) |

## Contents/Code/api_client.py

| Symbol | Tests |
|---|---|
| `USER_AGENT` / `BASE_URL` / `DEFAULT_RETRY_AFTER` | `test_api_client.TestConstants` |
| `search` (POST /search, 4xx raise, 5xx retry, retry-after clamp) | `TestSearch` (5) |
| `get_book` / `get_release` / `get_person` (GET detail, 404 → None, 5xx retry) | `TestDetailEndpoints` (5) |
| `ratings` (GET /items/{type}/{id}/ratings, 404 → None) | `TestRatings` (3) |
| `resolve_book` / `resolve_person` (external lookup, 404 → None, non-list → None) | `TestResolve` (4) |
| `fetch_bytes` (bytes passthrough, 4xx/5xx → IOError) | `TestFetchBytes` (4) |

## Contents/Code/metadata_ids.py

| Function | Tests |
|---|---|
| `parse_id` (book/release/person, legacy ASIN + region, bare ASIN, garbage) | `test_metadata_ids.TestParseId` (12) |
| `serialize_book_id` / `serialize_person_id` | `TestSerialize` (4) |
| `is_native` / `is_legacy` | `TestClassifiers` (7) |

## Contents/Code/search_tools.py

### `SearchTool` (base)

| Method | Tests |
|---|---|
| `check_for_asin` | `TestCheckForAsin` (6: album/filename ASIN append, native book/person IDs, manual-only artist ASIN, none) |
| `build_search_body` | `TestBuildSearchBody` (4: books q+filters, people, <3-char None, filters empty-omit) |
| `parse_api_response` (books) | `TestParseBooksResponse` (5: field map, author/narrator roles, empty narrator [], subtitle, language, no hits) |
| `parse_api_response` (people) | `TestParsePeopleResponse` (2: id/name/description/genres, no hits) |
| `validate_author_name` | `TestHelpers` |

### `AlbumSearchTool`

| Method | Tests |
|---|---|
| `name_to_initials` | `TestNameToInitials` (5) |
| `normalize_name` | `TestNormalizeName` (3) |
| `pre_search_logging` | `TestPreSearchLogging` (incl. manual `media.album := media.name` — `#10`) |

### `ArtistSearchTool`

| Method | Tests |
|---|---|
| `cleanup_author_name` | `TestCleanupAuthorName` (4) |
| `find_non_contributor` / `handle_multi_artist` / `get_primary_author` / `set_media_artist` | `TestArtistMultiArtist` (5) |

### `ScoreTool`

| Method | Tests |
|---|---|
| `reduce_string` | `TestScoreTool.test_reduce_string` (py3 bytes shim in plex_shim) |
| `sum_scores` | `TestScoreTool.test_sum_scores` (reduce/`sum()` delta comment) |
| `run_score_author` / `run_score_book` | `TestScoreTool` perfect-match tests |
| `score_album` / `score_author` / `score_language` | `TestScoreTool` (book_id/id field access; region dropped) |
| `score_create_result` | `TestScoreTool` e2e; `IGNORE_SCORE=45` skip; narrator empty-guard |

## Contents/Code/update_tools.py

### `UpdateTool` (base)

| Method | Tests |
|---|---|
| `parse_id` delegation / native field extraction | `test_update_tools.TestUpdateToolInit` (4: book, release, person, legacy) |
| `select_release` | `TestSelectRelease` (5: pinned, matchedReleaseId, only, min(ids), None) |
| `set_empty_variables` | `TestEmptyVariables` (2: album full init, artist) |
| `log_update_metadata` | `TestLogUpdateMetadata` (2) |
| `cleanup_html` | `TestCleanupHtml` (2) |
| `replace_html_special` | `TestReplaceHtmlSpecial` (2) |
| `collect_metadata_to_log` | `TestCollectMetadataToLog` (2) |
| `collect_metadata_arrs_to_log` | `TestCollectMetadataArrsToLog` (2; `'book'` typo — `#2`) |
| `getDateFromString` | `TestGetDateFromString` (3) |
| `volume_prefix` | `TestVolumePrefix` (3) |
| `series_volume` | `TestSeriesVolume` (3: label present, status absent → None, no series) |

### `AlbumUpdateTool`

| Method | Tests |
|---|---|
| `resolve_item` | `TestAlbumResolve` (5: legacy ASIN resolve, native book+release, work-only, 404 → False, ambiguous legacy) |
| `parse_api_response` | `TestAlbumParseApiResponse` (3: book_detail, series, defaults) |
| `set_metadata_rating` | `TestSetMetadataRating` (2: audible chip only, `*2` — `#8`) |
| `set_metadata_summary` | `TestSetMetadataSummary` (3) |
| `set_metadata_title` | `TestSetMetadataTitle` (3) |
| `set_metadata_sort_title` | `TestSetMetadataSortTitle` (3) |
| `set_metadata_studio` | `TestSetMetadataStudio` (2) |
| `set_metadata_date` | `TestSetMetadataDate` (4) |
| `set_metadata_tags` | `TestSetMetadataTags` (4) |

### `ArtistUpdateTool`

| Method | Tests |
|---|---|
| `resolve_item` | `TestArtistResolve` (4: legacy ASIN single-hit, 0/ambiguous → False, native, ID set inside resolve) |
| `parse_api_response` | `TestArtistParseApiResponse` (2) |
| `set_metadata_description` | `TestArtistSetMetadataDescription` (2) |
| `set_metadata_sort_title` | `TestArtistSetMetadataSortTitle` (4; `Jr.` double-space — `#6`) |
| `set_metadata_title` | `TestArtistSetMetadataTitle` (2) |
| `set_metadata_tags` | `TestArtistSetMetadataTags` (1) |

### `TagTool`

| Method | Tests |
|---|---|
| `add_genres` | `TestTagToolGenres` (3) |
| `add_narrators_to_styles` | `TestTagToolNarrators` (3) |
| `add_authors_to_moods` | `TestTagToolAuthors` (2) |
| `add_series_to_moods` | `TestTagToolSeries` (2) |
| `add_similar` | `TestTagToolSimilar` (2) |
| `clear_moods` / `clear_styles` | `TestTagToolClear` (2) |

## Contents/Code/__init__.py (agent glue)

| Function / method | Tests |
|---|---|
| `Start` (UA + X-API-Key anonymous/pref) / `ValidatePrefs` | `test_agent.TestStartAndIdentity` (5) |
| `AudiobookAlbum.search` + `process_results` | `TestAlbumSearch` (2: fixture → `book.<id>` score 99, body assert); no hits below `GOOD_SCORE` |
| `AudiobookAlbum.search` quick match | `TestAlbumQuickMatch` (3: album ASIN → `book.<id>.release.<id>` score 100, filename ASIN, unresolvable fall-through) |
| `AudiobookAlbum.update` / posters | `TestAlbumUpdate` (5: legacy migration `#3`, second-update native-only endpoints, 404 untouched, no-release work-only path, pinned-release 404 preserved) |
| `AudiobookArtist.search` / `update` | `TestArtistSearchAndUpdate` (3: legacy migration `#4`, 404 untouched, search→native update round trip, person detail only) |
| `getDateFromString` (album class copy) | `TestStartAndIdentity.test_get_date_from_string` |

## Coverage notes

- **No live network**: every test runs against the shim transport + fixtures.
  Live smoke checks were run against `api.audiobookdb.org` during migration
  (not committed).
- `region_tools.py` and its tests were deleted with the Audnexus API; region
  handling is gone end to end (legacy region-suffixed IDs still parse via
  `metadata_ids` for migration).
- `make_request` / `json_decode` were deleted with the Audnexus API (legacy
  dead retry — `#1` — is gone with them).
- `get_square_image` was deleted (person detail has no `images`; artist
  posters are intentionally not fetched).
- `check_if_preorder` was deleted with the search endpoint (hit `date` is
  always None; the `getDateFromString` line shape is kept).
- The album agent keeps its own `getDateFromString` copy (legacy parity).
- Plex-only `Contents.codecache` decorators are not present in this repo's
  snapshot; the shim supplies `CACHE_1WEEK` for the bundle runtime.
