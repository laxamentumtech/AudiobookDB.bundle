SYNTHESIZED FIXTURES
====================
ratings_book_WQQDcMBQ3qUT.json: recorded body with a synthetic openlibrary chip PREPENDED so the audible chip is not first (tests chip selection by source, not position).
book_detail_no_releases_WQQDcMBQ3qUT.json: recorded book detail with releases[] emptied (matchedReleaseId absent in the plain detail; tests the work-only update path). No live no-release book was found.
error_404.json: canonical JSON:API 404 envelope (recorded live from /audiobooks/external/audible/BBBBBBBBBB).
release_detail_RAffFyqchypK.json: copy of release_detail_dPL9fC7YnK8X.json with the id swapped to RAffFyqchypK, the second release listed in the book detail (tests lowest-ID selection + the selected-release 404 fallback, where this detail is omitted from the transport).
