# Test Coverage Map

Fixture-backed, offline. `make test` (Python 3) and `make test-py2`
`python:2.7-slim` in docker, full unittest discovery). 342 tests, 0 network.

The test transport double (`tests/plex_shim.py`) has two modes: an
eager default, and a `lazy=True` mode that mirrors Plex's real
HTTPRequest (no `.status`, `str()` loads the body and raises `HTTPError`
for non-2xx, and a headers-only read before the body has loaded raises
so the lazy CSRF prime is forced to load the body first). The lazy mode
applies a response's cookies at the body-load point, as the real
transport does. The handshake tests use it so the production transport
contract is what gets exercised.

## Contents/Code modules → test files

| Module | Tests |
|---|---|
| `__init__.py` (AudiobookAlbum/Artist: Start, ValidatePrefs, getDateFromString, search, update, compile_metadata) | `test_agent.py` |
| `api_client.py` | `test_api_client.py` |
| `logging.py` | `test_logging.py` |
| `metadata_ids.py` | `test_metadata_ids.py` |
| `search_tools.py` | `test_search_tools.py` |
| `update_tools.py` | `test_update_tools.py` |
| (sandbox compliance of every shipped module) | `test_sandbox_compliance.py` (8 tests: restricted names and builtins, augmented assignment rules, code-dir presence) |

## `test_agent.py` (30 tests) — end-to-end agent flows

| Class | Count | Production path covered |
|---|---|---|
| `TestStartAndIdentity` | 4 | `Start`, `ValidatePrefs`, `getDateFromString`, agent name/prefix constants |
| `TestAlbumSearch` | 8 | `AudiobookAlbum.search` end-to-end: POSTed body, serialized IDs, GOOD_SCORE short-circuit (auto breaks at ≥98, manual keeps all), manual edition rows (work-only + up to 5 ranked recordings with release cover/year) |
| `TestAlbumQuickMatch` | 3 | `search` ASIN quick-match: album/filename ASIN → single 100-point result; unresolvable ASIN falls through |
| `TestAlbumUpdate` | 9 | `update` end-to-end: full release, work-only (no release writes), pinned-release 404 fail-closed, search→update native round trip (detail endpoints only), forced update with empty/null description keeps the existing summary and still writes title/studio/styles/native ID |
| `TestArtistSearchAndUpdate` | 6 | artist `search` + `update` round trip; legacy ASIN migration; 404 leaves item untouched; forced update with empty bio keeps the existing summary and still writes name/genres/native ID |

## `test_api_client.py` (61 tests)

| Class | Count | Production path covered |
|---|---|---|
| `TestMakeRequest` | 7 | `make_request`: 200, 404, non-2xx, malformed JSON, error envelope, exhausted attempts → `None` |
| `TestFetchBytes` | 10 | `fetch_bytes`: returns raw bytes; raises `IOError` after exhaustion; non-HTTPS and untrusted-host URLs refused before any request; redirect to allowlisted host (absolute + relative) followed; redirect to off-allowlist host / http scheme blocked (target never requested); 3xx loop stopped at `MAX_IMAGE_REDIRECTS`; redirect without `Location` raises |
| `TestPostJson` | 2 | `post_json`: headers + JSON body; failure → `None` |
| `TestResolveAsinBook` | 2 | `resolve_asin_book`: single hit → book ID; 404 → `None` |
| `TestResolveAsinPerson` | 2 | `resolve_asin_person`: single hit → hits list; failure/empty → `[]` |
| `TestDetailAndGetters` | 7 | `get_book` (+ `include=chapters`), `get_release`, `get_person`, `get_ratings`, `search` (book/people fixtures, short-q with no filters → `[]` with no request) |
| `TestRetryAfter` | 7 | 429 + `Retry-After` retry then success; exhausted → `None`; oversized value clamped to `MAX_RETRY_AFTER`; negative value falls back to default; future HTTP-date waits until the requested time; past HTTP-date falls back to default |
| `TestSearchHandshake` | 14 | anonymous CSRF handshake: same-origin prime GET, double-submit token in header + Cookie, keyed bypass skips the prime, token cached per process, stale token → cache-busted re-prime (jar-held cookie) + one bounded retry, 403 twice → `None` without looping, prime without cookie / prime transport failure → `None`, `includeFields` list and comma-string forms, lazy-transport handshake and non-2xx surfacing |
| `TestLazyStatuslessSuccess` | 3 | a lazy 2xx (no `.status`, body loads cleanly) is a success, not a 599: detail GET through `make_request`, keyed search POST through `post_json`, and `fetch_bytes` — each succeeds in a single attempt |
| `TestLazyNon2xxHeaders` | 3 | a lazy non-2xx (429/3xx) loads the body before any headers read: the coded `HTTPError` drives the retry/`IOError` contract, no `RuntimeError` escape; an uncoded body failure retries to `None` |
| `TestJarCsrfToken` | 3 | `jar_csrf_token`: attribute-only CookieObject (the framework shape), dict-cookie value reads, comma-joined `Set-Cookie` header value |
| `TestAnonymousCoded403` | 1 | a coded 403 `HTTPError` raised in flight by an eager transport reaches `search()`'s re-prime branch (prime, rejected POST, re-prime, accepted POST) instead of being swallowed by the blanket except |

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
| `TestParseNativePerson` | 3 | `parse_metadata_id`: person, invalid types, missing ID |
| `TestParseLegacyAsin` | 4 | `parse_metadata_id`: bare ASIN book/author, region suffix discarded, uppercased |
| `TestParseInvalid` | 6 | `parse_metadata_id`: empty, `None`, too short/long, garbage, bad suffix |
| `TestSerialize` | 5 | `serialize_book_id` / `serialize_person_id`: work-only, +release, person, empty → `None`, round trip |

## `test_search_tools.py` (124 tests)

| Class | Count | Production path covered |
|---|---|---|
| `TestCheckForAsinBooks` | 10 | album ASIN check: filename, album, and native `book.` ID sources (incl. release pair), release/ASIN/ID 404s, release without a book, and non-ID input → `False` |
| `TestFileAsinHints` | 8 | filename ASIN hints: detection, suffixes, non-ASIN ignored |
| `TestCheckForAsinPeople` | 8 | artist ASIN check: sources, non-ASIN ignored |
| `TestSearchToolHelpers` | 5 | `validate_author_name`: clears bad, keeps good, sets primary author |
| `TestAlbumSearchToolBody` | 6 | `build_search_body`: with/without artist filters, too-short → `None`, nothing → `None`, filters-only (short title + artist) |
| `TestAlbumParentAuthor` | 6 | parent author ID wiring: matched native person ID as evidence, mismatch/absence tolerated |
| `TestNameToInitials` | 5 | `name_to_initials`: full names, already abbreviated, multi-word |
| `TestNormalizeName` | 6 | `normalize_name`: brackets/specials/words stripped, album→title fallback, diacritics, bracketed book number preserved (unbracketed) while non-number and mixed tags are stripped |
| `TestAlbumParseApiResponse` | 7 | album `parse_api_response`: fixture hits, missing required keys, non-dict items, no narrator role, string-role credit skipped without dropping the hit |
| `TestPreSearchLogging` | 5 | `pre_search_logging`: missing album → track title, unknown album → `None`, manual |
| `TestAlbumReleasesForBook` | 5 | `releases_for_book`: original dicts returned, duplicate IDs deduped, merged-book 301 to winner resolved, release for another book filtered, failure/empty → `[]` |
| `TestRecordingHints` | 11 | `recording_hints`: track duration and language signals, partial/absent → `None`, unmapped stream code without a usable label → no hint, display label in the code field is a hint |
| `TestImageAndDateHelpers` | 5 | `image_thumb`, `release_year` (non-text date → missing), `release_narrator`, `first_image_thumb` (first usable image, not just the first) |
| `TestArtistSearchToolBody` | 2 | `build_search_body` (artist): body, too-short → `None` |
| `TestCleanupAuthorName` | 4 | `cleanup_author_name`: role removals, diacritics |
| `TestArtistMultiArtist` | 5 | `find_non_contributor`, `handle_multi_artist`, `get_primary_author` |
| `TestArtistParseApiResponse` | 2 | artist `parse_api_response`: fixture, missing keys rejected |
| `TestScoreTool` | 24 | scoring: subtitle + coauthor full-match evidence, four same-base wrong-volume targets available only in Fix Match, bracketed book number rejects an unnumbered same base (auto), accent-folded stem rejects a number conflict (comparison path only), prefixed/accented series title resolves a book-number conflict, ranged and disjoint-set series positions, legacy ordinal only when position is missing, explicit unknown/partial positions abstain for unnumbered titles but do not hide a same-stem title-number conflict, partial coverage is never support, fractional and non-finite ordinals/spans abstain, malformed/reversed spans are not contradictions, literal title number precedence, unrelated series/edition numbers tolerated, unrelated title numbers do not override membership, bare title + wrong author rejected, parent author ID evidence (match/mismatch/absence), relaxed author caps the name penalty at twenty, thumb carried without score change |

## `test_update_tools.py` (80 tests)

| Class | Count | Production path covered |
|---|---|---|
| `TestAlbumResolveLegacyAsin` | 3 | album `resolve_item`: legacy migration (populates, stashes native IDs), 404 untouched |
| `TestAlbumResolveNative` | 11 | album `resolve_item`: book+release pinned, book-only multi-edition stays work-only, single-release 404 → work-only, mismatched pinned release rejected, pinned release 404 preserved, merged-book canonical detail ID replaces the stored loser ID (work-only and pinned), pinned release with `book: null` fails closed, unpinned release with `book: null` falls back to work-only, book 404 preserved, wrong-type invalid |
| `TestAlbumParseApiResponse` | 7 | album `parse_api_response`: series, no-releases work-only, audible chip rating (absent/non-first), missing cover → empty thumb, null/absent person names filtered from author/narrator lists, non-mapping `chapterDetail` / non-list `chapters` → no chapter data |
| `TestReleaseSelection` | 3 | `select_release`: only release selected, multi-edition → work-only, no releases → `None` |
| `TestArtistResolve` | 5 | artist `resolve_item`: legacy migration, native person, 404 untouched, ambiguous ASIN untouched, wrong-type invalid |
| `TestUpdateToolHelpers` | 8 | `cleanup_html` (books/authors), `replace_html_special`, `collect_metadata_to_log` (books + authors), `collect_metadata_arrs_to_log` (legacy typo), `getDateFromString`, `volume_prefix` |
| `TestAlbumSetters` | 23 | `set_metadata_title` (+subtitle), `set_metadata_rating` (x2, none no-op), `set_metadata_date` guard, `set_metadata_studio`, `set_metadata_summary` (+ empty/whitespace/markup-only description preserves an existing summary and is logged; forced and non-forced assignment unchanged), `set_metadata_sort_title` (+series), `set_metadata_tags` (+keep existing genres), `set_metadata_series_collections` (no container → warning, not silent), `set_metadata_chapters` (overlapping — out-of-order and identical — and one-based-ordinal sequences rejected before any title write; in-order sequence rewrites generic titles) |
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
| `matchedReleaseId` select | `select_release` (only release selected; multiple editions stay work-level) |
| `store_author_as_mood` pref | kept |
| `clear_moods` on force | kept |
| forced update with a missing/empty description sets `metadata.summary` to `''` (album `synopsis` and artist `description` alike) | an empty, whitespace-only or markup-only incoming description leaves an existing summary untouched (the unavailable summary is logged instead); genuinely present text still overwrites on a forced update |
