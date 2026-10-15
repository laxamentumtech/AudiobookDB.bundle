# Phase-1 test coverage map

Every public method in `Contents/Code/` (legacy snapshot) mapped to the tests
that exercise it. 201 tests total, green on **Python 2.7** (docker
`python:2.7-slim`, via `make test-py2`) and **Python 3** (`make test`).
Test files: `tests/test_logging.py` (16), `tests/test_region_tools.py` (13),
`tests/test_search_tools.py` (63), `tests/test_update_tools.py` (80),
`tests/test_agent.py` (29). Legacy defects are cross-referenced to
`LEGACY_ISSUES.md` as `#n`.

Harness: `tests/plex_shim.py` (fake Plex framework: `HTTP`, `Log`, `Prefs`,
`Locale`, `Agent`, `MetadataSearchResult`, `Proxy`, `String`, `Util`,
`Datetime`, `SSLError`, `CACHE_1WEEK`; injectable HTTP transport) and
`tests/py23_compat.py` (py2↔py3 stdlib deltas; no-op under py2). Fixtures:
`tests/fixtures/legacy/*.json`.

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

## Contents/Code/region_tools.py — `RegionTool` (+ `available_regions`)

| Method | Tests |
|---|---|
| `__init__` / `get_region` / `get_region_name` / `get_region_query` / `get_region_tld` | `test_region_tools.TestRegionTool` (basic getters) |
| `get_content_type_url` | `TestRegionTool` (audnex.us URL) |
| `get_search_url` | `TestRegionTool` (`?region=` + `&query`) |
| `get_id_url` | `TestRegionTool` |
| `get_id_url_with_query` | `TestRegionTool` |
| `get_api_region_url` | `TestRegionTool` (per-region TLD) |
| `get_api_params` | `TestRegionTool` |
| `get_api_search_url` | `TestRegionTool`; single-`&` base form pinned here, `&&` quirk surfaces via `#5` |
| `available_regions` table | `test_region_tools.TestAvailableRegions` (2: count + row shape) |

## Contents/Code/search_tools.py

### `SearchTool` (base)

| Method | Tests |
|---|---|
| `build_url` | `test_search_tools.TestSearchToolBuildUrl` (3: books URL, authors URL, ASIN override → `#5 &&keywords=`) |
| `check_for_asin` | `TestSearchToolCheckForAsin` (5: filename, manual book, manual artist, none, artist album-fallback) |
| `check_for_region` | `TestSearchToolRegion` (3: `[uk]` override, default pref, bracket regex) |
| `clear_contributor_text` / `log_search_url` / `override_with_asin` / `pre_process_title` / `search_asin` / `search_region` / `validate_author_name` | `TestSearchToolHelpers` (10) |

### `AlbumSearchTool`

| Method | Tests |
|---|---|
| `build_search_args` | `TestAlbumSearchToolArgs` (2) |
| `check_if_preorder` | `TestAlbumSearchToolPreorder` (2) |
| `name_to_initials` | `TestNameToInitials` (5) |
| `normalize_name` | `TestNormalizeName` (3) |
| `parse_api_response` | `TestAlbumParseApiResponse` (3: book_search fixture, unknown-filter, empty) |
| `pre_search_logging` | `TestPreSearchLogging` (5: incl. manual `media.album := media.name` — `#10`) |

### `ArtistSearchTool`

| Method | Tests |
|---|---|
| `build_search_args` | `TestArtistSearchToolArgs` (1) |
| `cleanup_author_name` | `TestCleanupAuthorName` (4) |
| `find_non_contributor` / `handle_multi_artist` / `get_primary_author` / `set_media_artist` | `TestArtistMultiArtist` (5) |
| `parse_api_response` | `TestArtistParseApiResponse` (2: author_search fixture; `ASIN_region` IDs — `#3`) |

### `ScoreTool`

| Method | Tests |
|---|---|
| `reduce_string` | `TestScoreTool.test_reduce_string` (py3 bytes shim in plex_shim) |
| `sum_scores` | `TestScoreTool.test_sum_scores` (reduce/`sum()` unavailability comment) |
| `run_score_author` | `TestScoreTool.test_run_score_author_perfect_match` |
| `run_score_book` | `TestScoreTool.test_run_score_book_perfect_match` |
| `score_create_result` | via `TestScoreTool` e2e; `IGNORE_SCORE=45` skip in `test_score_below_ignore_boundary_skipped` |
| `score_result` / `score_album` / `score_author` / `score_language` | `TestScoreTool` (10 total) |

## Contents/Code/update_tools.py

### `UpdateTool` (base)

| Method | Tests |
|---|---|
| `build_url` | `test_update_tools.TestUpdateToolBuildUrl` (3: book id URL `?region=us`, artist id URL, bare-ASIN) |
| `cleanup_html` | `TestCleanupHtml` (2) |
| `replace_html_special` | `TestReplaceHtmlSpecial` (2) |
| `collect_metadata_to_log` | `TestCollectMetadataToLog` (2) |
| `collect_metadata_arrs_to_log` | `TestCollectMetadataArrsToLog` (2); `test_books_typo_branch` pins `'book'` vs `'books'` (`#2`) |
| `extract_asin_from_id` / `extract_region_from_id` | `TestExtractFromId` (4: region-suffixed, bare ASIN, region from ID, bare-ID pref fallback) |
| `get_preferred_region` | `TestExtractFromId` (2: class attr, pref fallback) |
| `log_update_metadata` | `TestLogUpdateMetadata` (2 smoke, books + authors) |

### `AlbumUpdateTool`

| Method | Tests |
|---|---|
| `parse_api_response` | `TestAlbumParseApiResponse` (3: book_detail, book_detail_series, empty — `#12` bullet is `\u2022` escape) |
| `set_metadata_date` | `TestSetMetadataDate` (4) |
| `set_empty_variables` | `TestAlbumSetEmptyVariables` (1) |
| `set_metadata_rating` | `TestSetMetadataRating` (2: `*2` — `#8`) |
| `set_metadata_summary` | `TestSetMetadataSummary` (3) |
| `set_metadata_studio` | `TestSetMetadataStudio` (2) |
| `set_metadata_sort_title` | `TestSetMetadataSortTitle` (3: plain, series+volume, subtitle rule) |
| `set_metadata_tags` | `TestSetMetadataTags` (4: genres, force-clear, keep-existing, series→moods) |
| `set_metadata_title` | `TestSetMetadataTitle` (3) |
| `simplify_title` | `TestSimplifyTitle` (3) |
| `volume_prefix` | `TestVolumePrefix` (3) |

### `ArtistUpdateTool`

| Method | Tests |
|---|---|
| `get_square_image` | `TestGetSquareImage` (4: passthrough, landscape crop py2-vs-py3 padding — `#11`, portrait, non-JPEG) |
| `parse_api_response` | `TestArtistParseApiResponse` (2) |
| `set_empty_variables` | `TestArtistSetEmptyVariables` (1) |
| `set_metadata_description` | `TestArtistSetMetadataDescription` (2) |
| `set_metadata_sort_title` | `TestArtistSetMetadataSortTitle` (4: two-part, single word, `Jr.` double-space — `#6`, pref off) |
| `set_metadata_tags` | `TestArtistSetMetadataTags` (1) |
| `set_metadata_title` | `TestArtistSetMetadataTitle` (2) |

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
| `Start` / `ValidatePrefs` | `test_agent.TestStartAndValidate` (2) |
| `VERSION_NO` + class attrs (`Agent.Artist`/`Agent.Album`) | `TestAgentClassAttrs` (2), `TestModuleHelpers.test_version` |
| `json_decode` | `TestModuleHelpers.test_json_decode_dict`, `test_json_decode_garbage` (`AttributeError`-only catch — `#9`) |
| `make_request` | `TestModuleHelpers.test_make_request_success`, `test_make_request_failure_raises_type_error` (dead retry — `#1`) |
| `AudiobookArtist.search` | `TestArtistSearch` (3: appends `ASIN_us` IDs — `#3`, quick match — `#7` unguarded `r['year']` via year assert, bad-name no results) |
| `AudiobookArtist.update` / `call_item_api` / `compile_metadata` | `TestArtistUpdate` (2: populates, bare-ASIN update URL) |
| `AudiobookAlbum.search` + `process_results` | `TestAlbumSearch` (7: GOOD_SCORE break `len(info)>1`, manual below-threshold, result name display, fixture search (Spanish narrator exercises `#12` shim), unknown-album bail, ASIN quick match, filename ASIN) |
| `AudiobookAlbum.update` / posters | `TestAlbumUpdate` (5: populates, poster stored, no refetch without force, refetch on force, only-detail-requested) |
| `getDateFromString` | `TestGetDateFromString` (3: valid ISO → `datetime.date`, None, garbage) |

## Coverage gaps (accepted for Phase 1)

- **No live network**: every test runs against the shim transport + fixtures.
  Real AudiobookDB smoke tests arrive in Phase 3 (`test_live_api.py`, keyed,
  CI-skipped without secret).
- **`Contents.codecache` decorators** (`@cache.cache`/`@agent.interval`):
  not decorated in the snapshot copy; the shim supplies `CACHE_1WEEK` for when
  the bundle runs under Plex. Plex-only semantics untested by design.
- `SearchTool.__init__` / `UpdateTool.__init__` / `ScoreTool.__init__` /
  `TagTool.__init__`: covered only indirectly through the per-method tests.
