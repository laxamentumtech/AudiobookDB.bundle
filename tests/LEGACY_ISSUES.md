# Legacy issues — post-migration status

The Phase-1 suite locked in the exact behaviour of the legacy Audnexus agent,
**defects included**. This file records the post-migration (AudiobookDB)
status of each pinned issue, plus defects that carried over into the new
implementation. Numbers are stable; `#n` citations in `COVERAGE.md` and test
docstrings point here.

---

## 1. `make_request` retry loop is dead code — **RESOLVED (deleted)**

`make_request` (and `json_decode`) were deleted with the Audnexus API.
`api_client.py` now has real retry/backoff for 5xx and `Retry-After`
clamping, tested in `test_api_client.py`.

## 2. `collect_metadata_arrs_to_log` compares to `'book'`, never `'books'` — **KEPT**

`update_tools.py` `collect_metadata_arrs_to_log` still checks
`if self.content_type == 'book':`, so the `Moods (Authors)` / `Styles
(Narrators)` arrays are never logged for book updates. Retained for
parity; the typo is load-bearing in legacy log output.
Pinned by `test_update_tools.TestUpdateToolHelpers`
(`test_collect_metadata_arrs_legacy_typo`).

## 3. Artist quick-match ID is `ASIN_region` — **REPLACED by the sole-appender**

The legacy ID scheme is gone end to end. `check_for_asin`
(`search_tools.py`) is the **sole** result appender for quick matches: it
resolves a legacy ASIN through `api_client.resolve_asin_book` /
`api_client.resolve_asin_person` and appends a native `book.<id>/.release.<id>` /
`person.<id>` result (score 100). The agent's `search()` no longer appends
anything itself. Artist ASIN quick match is manual-input only (legacy
parity — album/track filenames are not scanned for artist ASINs). Legacy
`ASIN_region` IDs stored by the old agent still parse via
`metadata_ids.parse_metadata_id` and migrate on first update.

## 4. `metadata_arrs` logs value as key and key as label (inverted) — **KEPT**

`logging.py` `metadata_arrs` is unchanged (byte-for-byte legacy).
Pinned by `test_logging.TestMetadataArrs`.

## 5. Double ampersand `&&keywords=` — **RESOLVED (gone with `region_tools.py`)**

There are no URL builders anymore; `api_client` assembles fixed endpoint
paths and `search_tools.build_search_body` emits a JSON body.

## 6. Artist sort title keeps suffix with double space: `Doe, John,  Jr.` — **KEPT**

`update_tools.py` `set_metadata_sort_title` is unchanged: `John Doe, Jr.`
sorts as `Doe, John,  Jr.` (two spaces before `Jr.`); pref-off falls back to
the display name. Pinned by
`test_update_tools.TestArtistSetters` (`test_set_metadata_sort_title_*`).

## 7. Unguarded `r['year']` in search results — **RESOLVED**

The legacy album search passed `year=r['year']` (KeyError on hits without a
year). The new album parse path uses `book.get('copyright')` and the artist
parse path passes no year at all, so no year access can raise.

## 8. Rating is doubled (`float(rating) * 2`) — **KEPT (audible chip only)**

`update_tools.py` `set_metadata_rating` still applies `* 2` (Plex 0-10 scale)
with no clamping. The *source* changed: the rating now comes from the
AudiobookDB ratings endpoint's **`Audible` chip only** — the first chip is
never used (fixture: openlibrary 4.3 first, audible 4.8 -> 9.6). Pinned by
`test_update_tools.TestAlbumSetters` (`test_set_metadata_rating_*`) and
`test_agent.TestAlbumUpdate.test_legacy_asin_migration`.

## 9. `json_decode` catches only `AttributeError` — **RESOLVED (deleted)**

`json_decode` was deleted with `make_request`. `api_client.decode` catches
JSON parse errors (`ValueError`/`AttributeError`) and returns `None`, so a
malformed payload surfaces as `None` for the caller to handle — no
silent-corruption path remains. Pinned by `test_api_client.py`
`TestMakeRequest` (`test_malformed_json_returns_none`).

## 10. Manual artist search overwrites `media.album` with `media.name` — **KEPT**

`search_tools.py` manual search path still does `media.album = media.name`
before scoring (album content type). Pinned by
`test_search_tools.TestPreSearchLogging`.

## 11. `get_square_image` CR padding differs between py2 and py3 — **RESOLVED (deleted)**

`get_square_image` was deleted: the AudiobookDB person detail can carry
`images`, and `ArtistUpdateTool.parse_api_response` uses
`images[0]['url'] + '/large.jpg'` as the thumb when present. Search hits
omit `images`, so the search list has no artwork (see #14).

## 12. `logging.log_output` crashes on non-ASCII metadata under Python 2 — **RESOLVED (unicode template)**

`logging.py` `log_output` now formats with a unicode template
(`u"{key:<20}{val}"`), so non-ASCII catalog text no longer raises
UnicodeEncodeError on Python 2; the `tests/plex_shim.py` py2 rebind of
`log_output` has been dropped, and the py2 CI leg exercises the shipped
implementation.

---

## New issues (post-migration)

### 13. Filename ASIN regex `(?=.\d)` anchors the match, not the ASIN's end

- **Where:** `search_tools.py:17` `asin_regex = re.compile(r'(?=.\d)[A-Z\d]{10}')`
  (inherited verbatim from the legacy agent).
- **Behaviour:** The lookahead `(?=.\d)` runs at the match start: it requires
  that the character two positions ahead (the candidate's second character)
  is a digit. It does not look past the 10-character candidate, so nothing
  after the ASIN is inspected — `B00B5HZGUG1` matches the same `B00B5HZGUG`.
  The practical effect is that a 10-character window inside a longer
  alphanumeric run still matches, provided that window's second character is
  a digit: `1B00B5HZGUG` matches `B00B5HZGUG` (the lookahead is checked at
  each position, so the match simply starts at index 1).
- **No URL-encoding quirk:** `check_for_asin` URL-decodes the filename
  (`url_parse.unquote`) *before* matching, so the regex sees a plain
  filename — `%` characters from encodings like `%20` are never fed to it.
  The legacy agent had the same unquote-before-match step; parity is kept.
- **Pinned by:** `test_search_tools.TestCheckForAsinBooks` (filename case),
  `test_agent.TestAlbumQuickMatch.test_asin_in_filename_appends_single_score_100`.

### 14. Search-hit persons have no `images` — artist search list has no art

- **Where:** `update_tools.py` `ArtistUpdateTool.parse_api_response` (thumb
  from `images[0]['url'] + '/large.jpg'` when present); `__init__.py` artist
  `compile_metadata` (poster fetch from `helper.thumb`).
- **Behaviour:** Artist updates set `metadata.thumb`/poster from the person
  detail's `images` when it carries them. Search hits omit `images`, so the
  search-list description has no artwork. Deliberate: the legacy
  `get_square_image` CDN crop is gone.
- **Pinned by:** `test_update_tools.TestArtistResolve` (thumb assertions),
  `test_agent.TestArtistSearchAndUpdate`.

### 15. `r['author']`/`r['narrator']` are joined strings after scoring

- **Where:** `search_tools.py` `ScoreTool.score_create_result` writes
  `author`/`narrator` as joined display strings into the scored dict.
- **Behaviour:** The album `search()` display path guards both with
  `r.get(...) or ''` because scored dicts no longer guarantee the keys;
  artist results only ever carry `author`. This is a shape contract between
  `ScoreTool` and the agent loop, not a user-facing defect.
- **Pinned by:** `test_search_tools.TestScoreTool` +
  `test_agent.TestAlbumSearch`.

---

### Honourable mentions (not defects, just legacy shape)

- GOOD_SCORE break only fires when `len(info) > 1` (`__init__.py`) — a lone
  98-score result doesn't break (moot, it's the last row anyway).
- Score sums use `reduce` (shadowed by `ScoreTool.reduce_string` method name)
  with a comment claiming builtin `sum()` "isn't available" under Plex — it
  is; the restriction was the old Plex sandbox.
- `IGNORE_SCORE = 45`: results below it are logged but never appended
  (`search_tools.py`).
