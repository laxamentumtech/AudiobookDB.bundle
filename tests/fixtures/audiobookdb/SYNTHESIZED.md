SYNTHESIZED FIXTURES
====================
ratings_book_WQQDcMBQ3qUT.json: recorded body with a synthetic openlibrary chip PREPENDED so the audible chip is not first (tests chip selection by source, not position).
book_detail_no_releases_WQQDcMBQ3qUT.json: recorded book detail with releases[] emptied (matchedReleaseId absent in the plain detail; tests the work-only update path). No live no-release book was found.
error_404.json: canonical JSON:API 404 envelope (recorded live from /audiobooks/external/audible/BBBBBBBBBB).
