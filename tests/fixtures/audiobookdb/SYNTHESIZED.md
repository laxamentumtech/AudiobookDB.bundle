SYNTHESIZED FIXTURES
====================
ratings_book_WQQDcMBQ3qUT.json: recorded body with a synthetic openlibrary chip PREPENDED so the audible chip is not first (tests chip selection by source, not position).
book_detail_no_releases_WQQDcMBQ3qUT.json: recorded book detail with releases[] emptied (matchedReleaseId absent in the plain detail; tests the work-only update path). No live no-release book was found.
error_404.json: canonical JSON:API 404 envelope (recorded live from /audiobooks/external/audible/BBBBBBBBBB).
release_detail_RAffFyqchypK.json: copy of release_detail_dPL9fC7YnK8X.json with the id swapped to RAffFyqchypK, the second release listed in the book detail (tests lowest-ID selection + the selected-release 404 fallback, where this detail is omitted from the transport).
search_books_ordering_gaps.json: synthesized /search hits for the reported wrong-pin groups. Contains the four targets (Swing Shift book 1, Cultivating Chaos book 1, Domestic Decay 2) plus unnumbered and matching-position controls. No catalog entries were fabricated for the missing Swing Shift 2 / 3 or Domestic Decay 4 books.
search_books_numbering_exceptions.json: synthesized /search hits for the numbering shapes that must not be penalised: course numbers (Dungeon Diving 101/102/201), Publisher's Pack and Volume titles, complete range positions, multiple series memberships, absent/fractional positions, and year/Roman/spelled-out controls.
