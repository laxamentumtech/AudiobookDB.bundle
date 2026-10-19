# Test Coverage Map

Fixture-backed, offline. `make test` (Python 3) and `make test-py2`
`python:2.7-slim` in docker, full unittest discovery). 275 tests, 0 network.

Note: the py3 shim (`tests/plex_shim.py`) monkeypatches
`ScoreTool.reduce_string` to decode bytes first, because the production
path (inherited verbatim from legacy) encodes the title to `bytes` and
`bytes.replace` is py3-incompatible. The suite therefore exercises a
slightly py3-adapted scoring path; the bundle targets python2.7.

## Contents/Code modules → test files

| Module | Tests |
|---|---|
| `__init__.py` (AudiobookAlbum/Artist: Start, ValidatePrefs, getDateFromString, search, update, compile_metadata) | `test_agent.py` |
| `api_client.py` | `test_api_client.py` |
| `logging.py` | `test_logging.py` |
| `metadata_ids.py` | `test_metadata_ids.py` |
| `search_tools.py` | `test_search_tools.py` |
| `update_tools.py` | `test_update_tools.py` |
| (sandbox compliance of every shipped module) | `test_sandbox_compliance.py` (7 tests: underscore-name ban, unavailable-builtin ban, code-dir presence) |

## `test_agent.py` (34 tests) — end-to-end agent flows

| Class | Count | Production path covered |
|---|---|---|
| `TestStartAndIdentity` | 5 | `Start`, `ValidatePrefs`, `getDateFromString`, agent name/prefix constants |
| `TestAlbumSearch` | 13 | `AudiobookAlbum.search` end-to-end: POSTed body, serialized IDs, GOOD_SCORE short-circuit (auto breaks at ≥98, manual keeps all), ordering conflicts dropped automatically but visible manually (with and without an artist), supported/mid-range candidates still appended, course/pack controls |
| `TestAlbumQuickMatch` | 3 | `search` ASIN quick-match: album/filename ASIN → single 100-point result; unresolvable ASIN falls through |
| `TestAlbumUpdate` | 8 | `update` end-to-end: full release, work-only (no release writes), pinned-release 404 fail-closed, search→update native round trip (detail endpoints only), forced update with empty/null description keeps the existing summary and still writes title/studio/styles/native ID |
| `TestArtistSearchAndUpdate` | 5 | artist `search` + `update` round trip; legacy ASIN migration; 404 leaves item untouched; forced update with empty bio keeps the existing summary and still writes name/genres/native ID |

## `test_api_client.py` (35 tests)

| Class | Count | Production path covered |
|---|---|---|
| `TestMakeRequest` | 6 | `make_request`: 200, 404, non-2xx, malformed JSON, error envelope, exhausted attempts → `None` |
| `TestFetchBytes` | 9 | `fetch_bytes`: returns raw bytes; raises `IOError` after exhaustion; non-HTTPS and untrusted-host URLs refused before any request; redirect to allowlisted host (absolute + relative) followed; redirect to off-allowlist host / http scheme blocked (target never requested); 3xx loop stopped at `MAX_IMAGE_REDIRECTS` |
| `TestPostJson` | 2 | `post_json`: headers + JSON body; failure → `None` |
| `TestResolveAsinBook` | 2 | `resolve_asin_book`: single hit → book ID; 404 → `None` |
| `TestResolveAsinPerson` | 2 | `resolve_asin_person`: single hit → hits list; failure/empty → `[]` |
| `TestDetailAndGetters` | 8 | `get_book` (+ `include=chapters`), `get_release`, `get_person`, `get_ratings`, `search` (book/people fixtures, short-q with no filters → `[]` with no request) |
| `TestRetryAfter` | 6 | 429 + `Retry-After` retry then success; exhausted → `None`; oversized value clamped to `MAX_RETRY_AFTER`; negative value falls back to default; future HTTP-date waits until the requested time; past HTTP-date falls back to default |

## `test_logging.py` (16 tests)

| Class | Count | Production path covered |
|---|---|---|
| `TestDebug` / `TestInfo` / `TestWarn` / `TestError` | 8 | level gating: pass at/above level, swallowed below |
| `TestLogOutput` | 2 | `log_output` at debug/info |
| `TestSeparator` | 2 | `separator` plain and with message |
| `TestMetadata` / `TestMetadataArrs` | 4 | `metadata` (falsy skipped, debug-gated), `metadata_arrs` (inverted key/value, empty skipped) |

## `test_metadata_ids.py` (23 tests)

| Class | Count | Production path covered |
|---|---|---|
| `TestParseNativeBook` | 5 | `parse_metadata_id`: work-only, book+release, invalid type/missing parts |
| `TestParseNativePerson` | 3 | `parse_metadata_id`: person, invalid type, missing ID |
| `TestParseLegacyAsin` | 4 | `parse_metadata_id`: bare ASIN book/author, region suffix discarded, uppercased |
| `TestParseInvalid` | 6 | `parse_metadata_id`: empty, `None`, too short/long, garbage, bad suffix |
| `TestSerialize` | 5 | `serialize_book_id` / `serialize_person_id`: work-only, +release, person, empty → `None`, round trip |

## `test_search_tools.py` (86 tests)

| Class | Count | Production path covered |
|---|---|---|
| `TestCheckForAsinBooks` | 9 | album ASIN check: filename, album, and native `book.` ID sources (incl. release pair), release/ASIN/ID 404s and non-ID input → `False` |
| `TestCheckForAsinPeople` | 8 | artist ASIN check: sources, non-ASIN ignored |
| `TestSearchToolHelpers` | 5 | `validate_author_name`: clears bad, keeps good, sets primary author |
| `TestAlbumSearchToolBody` | 5 | `build_search_body`: with/without artist filters, too-short → `None`, nothing → `None`, filters-only (short title + artist) |
| `TestNameToInitials` | 5 | `name_to_initials`: full names, already abbreviated, multi-word |
| `TestNormalizeName` | 3 | `normalize_name`: brackets/specials/words stripped, album→title fallback, diacritics |
| `TestAlbumParseApiResponse` | 7 | album `parse_api_response`: fixture hits, missing required keys, non-dict items, no narrator role, `seriesWithId` preserved (title/ordinal/position), missing/non-dict series defaults to `[]` |
| `TestPreSearchLogging` | 5 | `pre_search_logging`: missing album → track title, unknown album → `None`, manual |
| `TestArtistSearchToolBody` | 2 | `build_search_body` (artist): body, too-short → `None` |
| `TestCleanupAuthorName` | 4 | `cleanup_author_name`: role removals, diacritics |
| `TestArtistMultiArtist` | 5 | `find_non_contributor`, `handle_multi_artist`, `get_primary_author` |
| `TestArtistParseApiResponse` | 2 | artist `parse_api_response`: fixture, missing keys rejected |
| `TestScoreTool` | 11 | `reduce_string`, `sum_scores`, `run_score_author`, `run_score_book` (perfect, empty people, ignore-boundary skip, index penalty, language deduction), `score_album`/`score_author` no-match → 0, `score_language` mismatch |
| `TestScoreOrdering` | 15 | `score_ordering` / `ordering_suffix` / `series_position`: the four reported wrong pins drop below the append floor automatically and keep their manual scores; same-number titles and supporting memberships are preserved; unrelated title numbers cannot override or manufacture membership evidence; numeric-ordinal fallback, disjoint spans, absent/fractional/range data; course, pack, volume, year, Roman and spelled-out controls |

## `test_update_tools.py` (71 tests)

| Class | Count | Production path covered |
|---|---|---|
| `TestAlbumResolveLegacyAsin` | 2 | album `resolve_item`: legacy migration (populates, stashes native IDs), 404 untouched |
| `TestAlbumResolveNative` | 6 | album `resolve_item`: book+release pinned, book-only lowest-ID select, selected-release 404 → work-only, pinned 404 preserved, book 404 preserved, wrong-type invalid |
| `TestAlbumParseApiResponse` | 6 | album `parse_api_response`: series, no-releases work-only, audible chip rating (absent/non-first), missing cover → empty thumb, null/absent person names filtered from author/narrator lists |
| `TestReleaseSelection` | 6 | `select_release`: pinned wins, matched > only > lowest, only release, lowest-ID default, matched-not-present falls through |
| `TestArtistResolve` | 5 | artist `resolve_item`: legacy migration, native person, 404 untouched, ambiguous ASIN untouched, wrong-type invalid |
| `TestUpdateToolHelpers` | 8 | `cleanup_html` (books/authors), `replace_html_special`, `collect_metadata_to_log` (books + authors), `collect_metadata_arrs_to_log` (legacy typo), `getDateFromString`, `volume_prefix` |
| `TestAlbumSetters` | 18 | `set_metadata_title` (+subtitle), `set_metadata_rating` (x2, none no-op), `set_metadata_date` guard, `set_metadata_studio`, `set_metadata_summary` (+ empty/whitespace/markup-only description preserves an existing summary and is logged; forced and non-forced assignment unchanged), `set_metadata_sort_title` (+series), `set_metadata_tags` (+keep existing genres) |
| `TestArtistSetters` | 15 | `set_metadata_title`, `set_metadata_description` (+ same keep-existing-on-empty policy as the album setter), `set_metadata_sort_title` (last name/JR/single word), `set_metadata_tags`, `set_empty_variables` |
| `TestTagTool` | 5 | `TagTool` force-clears narrators (styles preserved when there are no narrators to re-add), non-force keeps existing, author/contributor handling, `similar=None` no-op |

## Legacy → new equivalence (legacy ref: Audnexus.bundle)

| Legacy behavior | New behavior |
|---|---|
| `ASIN + _us` IDs | native `book.<id>[.release.<id>]`, `person.<id>` |
| `HTTP.CacheTime = CACHE_1WEEK` response cache | `HTTP.CacheTime = CACHE_1WEEK` — Plex serves the `resolve_asin_book`/`resolve_asin_person` GETs from a one-week cache |
| `result_dict['language'].title()` (KeyError if absent) | `originalLanguage` title-cased before `score_language` (None-guarded) |
| `r['year']` KeyError on year-less hits | `book.get('copyright')`; artist hits pass no year |
| no `Retry-After` handling | 429 `Retry-After` retry loop (max 4 attempts, value clamped to 0–60s) |
| no image URL allowlist | `fetch_bytes` restricted to HTTPS on `cdn.audiobookdb.org`; 3xx followed hop-by-hop with the allowlist re-checked per `Location` (max 3 hops, loop rejected) — residual platform limitation: on some Plex transports the 3xx is consumed inside the transport and the `Location` never reaches the check, so such hops are invisible (initial URL always pre-validated; any redirect the transport surfaces is enforced) |
| `clear_styles` on forced album update | narrators re-added from release `people` (role `Narrator`); styles never cleared on work-only updates |
| `set_empty_variables` on empty `narrator` | no-op on empty `narrator` |
| `response['rating']` from the detail body | `get_ratings` (`audible` chip, order-independent) |
| `search_asin`/`override_with_asin` (ASIN anywhere in title/album) | `check_for_asin` is the sole ASIN appender (album/filename/metadata_id) |
| `matchedReleaseId` select | `select_release` (pinned > matched > only > lowest) |
| `store_author_as_mood` pref | kept |
| `clear_moods` on force | kept |
| forced update with a missing/empty description sets `metadata.summary` to `''` (album `synopsis` and artist `description` alike) | an empty, whitespace-only or markup-only incoming description leaves an existing summary untouched (the unavailable summary is logged instead); genuinely present text still overwrites on a forced update |
