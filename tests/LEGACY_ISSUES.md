# Legacy issues pinned by the Phase-1 test suite

The Phase-1 suite (201 tests, green on Python 2.7 and Python 3) locks in the
exact behaviour of the legacy Audnexus agent code, **defects included**, so
that Phase 3 (migration to the AudiobookDB API) can deliberately change any of
them with full visibility. Each entry cites the code location, the observable
behaviour, the test that pins it, and the Phase-3 resolution.

---

## 1. `make_request` retry loop is dead code

- **Where:** `Contents/Code/__init__.py:503-518`
- **Behaviour:** On failure the loop does
  `log.error("Failed http request attempt #" + x + ...)` where `x` is an `int`
  from `range()`. Concatenating `str + int` raises `TypeError` on **both**
  py2 and py3, so the error branch crashes before `sleep(sleep_time)` can run.
  Retries never happen. (The `try` also swallows the exception into
  `str_error`, but the failure path itself throws.)
- **Pinned by:** `test_agent.TestModuleHelpers.test_make_request_failure_raises_type_error`
- **Phase 3:** rewrite `make_request` with real retry/backoff and `'...#' + str(x)`
  (or an f-string-free `.format`, since the target stays py2-compatible).

## 2. `collect_metadata_arrs_to_log` compares to `'book'`, never `'books'`

- **Where:** `Contents/Code/update_tools.py:109-123`
- **Behaviour:** `content_type` is `'books'` for albums everywhere else in the
  codebase, but this check is `if self.content_type == 'book':`. The
  `Moods (Authors)` / `Styles (Narrators)` arrays are therefore **never**
  logged for book updates — dead metadata logging.
- **Pinned by:** `test_update_tools.TestCollectMetadataArrsToLog.test_books_typo_branch`
- **Phase 3:** fix to `== 'books'` (or drop once logging is restructured).

## 3. Artist quick-match ID is `ASIN_region`, detail lookup uses bare `ASIN`

- **Where:** `Contents/Code/search_tools.py:59,69,294` (IDs appended as
  `asin + '_' + region`) vs `Contents/Code/__init__.py` update path +
  `update_tools.extract_asin_from_id` (`update_tools.py:135-141`).
- **Behaviour:** Artist search results are appended with IDs like
  `B00G0WYW92_us`; Phase-3 AudiobookDB IDs are bare ASINs (`B00G0WYW92`) or
  `us.B00G0WYW92`. Mismatched IDs mean Plex-cached artist IDs from the legacy
  agent do not line up with the new agent's ID scheme (and the legacy code
  itself split on `_` to recover the ASIN — note a region suffix containing
  more `_`s would still work, but an ASIN-derived ID with no suffix is the
  canonical form).
- **Pinned by:** `test_agent.TestArtistSearch.test_search_appends` (IDs carry
  `_us`), `test_update_tools.TestExtractFromId.test_extract_asin_with_region`,
  `test_update_tools.TestExtractFromId.test_extract_asin_bare`,
  `test_agent.TestArtistUpdate.test_update_bare_asin_id`.
- **Phase 3:** `metadata_ids.py` normalises IDs to bare ASIN; migration note
  in README (users re-match artists once).

## 4. `metadata_arrs` logs value as key and key as label (inverted)

- **Where:** `Contents/Code/logging.py:88-100`
- **Behaviour:** For each `{'Label': [values...]}` dict it iterates
  `for item in val: self.log_output(item, key, ...)` — i.e. the **list element
  (the metadata value)** becomes the left-hand "key" column and the **label**
  becomes the right-hand "value". Output reads `Martian             Title is`
  instead of `Title is            Martian`.
- **Pinned by:** `test_logging.TestMetadataArrs.test_metadata_arrs_logs_inverted_key_value`
- **Phase 3:** swap to `log_output(key, item, ...)`.

## 5. Double ampersand `&&keywords=` in ASIN-override book search URLs

- **Where:** `Contents/Code/region_tools.py:126-139` +
  `Contents/Code/search_tools.py:104`
- **Behaviour:** `get_api_params()` ends without `?`-only (it starts `?` and
  has no trailing `&`), but `get_api_search_url` appends `'&' + query` and the
  ASIN-override query for books is built as `'&keywords=' + asin`, producing
  `...products?response_groups=...&products_sort_by=Relevance&&keywords=B00...`.
  The Audnexus/Audible API tolerates the empty first parameter, but the URL
  is malformed.
- **Pinned by:** `test_search_tools.TestSearchToolBuildUrl.test_build_url_asin_override_books`,
  `test_search_tools.TestSearchToolHelpers.test_override_with_asin_books`
  (both assert `&&keywords=` verbatim).
- **Phase 3:** new URL builder emits `&keywords=` once.

## 6. Artist sort title keeps suffix with double space: `Doe, John,  Jr.`

- **Where:** `Contents/Code/update_tools.py:471-489`
- **Behaviour:** The surname regex captures group(3) as `, Jr.`-style text
  **including its leading comma**, then `', '.join([...])` adds another
  separator: `John Doe, Jr.` sorts as `Doe, John,  Jr.` (two spaces before
  `Jr.`). Also, when `sort_author_by_last_name` is off the sort title falls
  back to `metadata.title` (the display name), not a reversed form.
- **Pinned by:** `test_update_tools.TestArtistSetMetadataSortTitle.test_suffix_kept`
  (asserts `'Doe, John,  Jr.'`), `test_pref_false_keeps_title`.
- **Phase 3:** join with the captured suffix stripped of its comma, e.g.
  `'{}, {}{}'.format(last, first, suffix)`.

## 7. Unguarded `r['year']` in artist search results

- **Where:** `Contents/Code/__init__.py:340-348`
- **Behaviour:** `MetadataSearchResult(..., year=r['year'])` assumes every
  scored artist dict has a `year` key. `score_create_result` only adds `year`
  when `self.year` is truthy, so an artist result without a date raises
  `KeyError` and kills the whole search.
- **Pinned by:** `test_agent.TestArtistSearch.test_search_appends` (asserts
  `year=1969` from `r['year']`; a scored artist dict without `year` would
  raise `KeyError` — the suite relies on `score_create_result` always emitting
  `year` in the fixtures).
- **Phase 3:** `r.get('year')`.

## 8. Rating is doubled (`float(rating) * 2`)

- **Where:** `Contents/Code/update_tools.py:253-258`
- **Behaviour:** Audnexus ratings are on a 0-5 scale; Plex stores 0-10, so the
  legacy code does `* 2`. This is *intentional* but undocumented, and it is
  applied unconditionally whenever `self.rating` is set (even pre-clamping).
  AudiobookDB returns 0-5 as well — Phase 3 must keep the scale conversion but
  make it explicit and clamped.
- **Pinned by:** `test_update_tools.TestSetMetadataRating.test_rating_times_two`
  (4.8 -> 9.6), `test_none_rating_no_change`.
- **Phase 3:** `metadata.rating = max(0.0, min(10.0, rating * 2.0))` with a
  named constant/comment.

## 9. `json_decode` catches only `AttributeError`

- **Where:** `Contents/Code/__init__.py:488-495`
- **Behaviour:** Malformed JSON raises `ValueError` on py2 /
  `json.JSONDecodeError` (subclass of `ValueError`) on py3 — neither is caught,
  so a corrupt API response crashes the agent instead of returning `None`.
  Only a non-string input (`None`, empty HTTP response) is handled.
- **Pinned by:** `test_agent.TestModuleHelpers.test_json_decode_garbage`
- **Phase 3:** catch `(ValueError, AttributeError)` (JSONDecodeError is a
  ValueError on every supported version).

## 10. Manual artist search overwrites `media.album` with `media.name`

- **Where:** `Contents/Code/search_tools.py` (`pre_process_title` / manual
  search path used by `__init__.py` `search()` when `manual=True`)
- **Behaviour:** For a manual single-album search the legacy code assigns
  `media.album = media.name` before scoring, so the album-title comparison
  silently uses the *track/file* name rather than the album field. Test
  fixtures have to set `media.name` as well or score 0.
- **Pinned by:** `test_search_tools.TestPreSearchLogging.test_manual_uses_user_name`
  (asserts `tool.media.album == 'My Pick'` i.e. `media.name`).
- **Phase 3:** prefer `media.album`, fall back to `media.name` only when empty.

## 11. `get_square_image` CR padding differs between py2 and py3

- **Where:** `Contents/Code/update_tools.py` (`get_square_image`)
- **Behaviour:** `crop_x = (width - height) / 2` uses floor division on py2
  (int / int -> int, renders `'100'`) and true division on py3
  (-> `50.0`-style float, renders `'100.0'`) — the same code produces
  different CDN crop URLs depending on interpreter.
- **Pinned by:** `test_update_tools.TestGetSquareImage.test_landscape_cropped_to_square`
- **Phase 3:** explicit `int((width - height) / 2)` so both interpreters agree.

## 12. `logging.log_output` crashes on non-ASCII metadata under Python 2

- **Where:** `Contents/Code/logging.py:44-53`
- **Behaviour:** `output = "{key:<20}{val}".format(key=key, val=val)` uses a
  **byte-string** template. Under py2, `str.format` coerces the result toward
  `str`, so any non-ASCII *unicode* value (everything from `json.loads`, e.g.
  a Spanish narrator "Xavi Fernández") raises
  `UnicodeEncodeError: 'ascii' codec can't encode character u'\xe1'`.
  On the real Plex runtime the bundled Log swallows this, but the plain-Python
  port crashes.
- **Pinned/worked around by:** `tests/plex_shim.py` (py2 branch rebinds
  `log_output` to a unicode-safe equivalent so end-to-end tests can run;
  documented in the shim).
- **Phase 3:** `output = u"..."` template with safe decode fallback; delete the
  shim patch then.

---

### Honourable mentions (not defects, just legacy shape)

- GOOD_SCORE break only fires when `len(info) > 1` (`__init__.py:132,355`) — a
  lone 98-score result doesn't break (moot, it's the last row anyway, but the
  condition is load-bearing in tests):
  `test_agent.TestAlbumSearch.test_search_breaks_on_good_score`,
  `test_manual_keeps_below_good_score`.
- Score sums use `reduce` (shadowed by `ScoreTool.reduce_string` method name)
  with a comment claiming builtin `sum()` "isn't available" under Plex — it is;
  the restriction was the old Plex sandbox.
- `IGNORE_SCORE = 45`: results below it are logged but never appended
  (`search_tools.py:628`):
  `test_search_tools.TestScoreTool.test_score_below_ignore_boundary_skipped`.
