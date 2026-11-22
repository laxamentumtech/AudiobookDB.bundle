# AudiobookDB Agent

Plex audiobook metadata agent powered by the AudiobookDB catalog, with direct ASIN and native-ID matching.

[AudiobookDB Agent](https://github.com/laxamentumtech/AudiobookDB.bundle) is a [Plex](https://www.plex.tv) metadata agent for audiobook libraries that sources everything — books, releases, and people — from the [AudiobookDB](https://audiobookdb.org) public API (`https://api.audiobookdb.org/api`). It is the successor to the Audnexus agent and installs alongside it: it registers under its own plug-in identifier (`com.plexapp.agents.audiobookdb`), so the legacy `Audnexus.bundle` can stay installed. Each library keeps using whichever agent is selected for it until you switch it over, and old pinned Audnexus IDs migrate safely (see [Migrating from Audnexus](#migrating-from-audnexus)).

What sets it apart:

- AudiobookDB book, release, and person metadata — titles, summaries, studios, ratings, genres, moods, posters, and native IDs.
- Direct matching: drop an Audible ASIN (or an AudiobookDB native ID) into the manual search field, and the agent resolves it straight to a score-100 result, skipping free-text search.
- A safe migration path: libraries switched from Audnexus keep their pinned `ASIN` / `ASIN_region` IDs working and are re-pinned to AudiobookDB's native ID form on the next refresh.

## Contents

- [Install](#install)
- [Usage](#usage)
- [Configuration](#configuration)
- [Quick match](#quick-match)
- [API details](#api-details)
- [Migrating from Audnexus](#migrating-from-audnexus)
- [Source installation](#source-installation)
- [Contributing](#contributing)
- [Acknowledgements](#acknowledgements)
- [License](#license)

## Install

**Prerequisite:** a running Plex Media Server that still provides the legacy agent system. On **Plex Media Server 1.43+** legacy agents are hidden during library setup — enable *Show legacy agents during library setup* in the server's library settings to pick this agent. Note that Plex has announced the legacy agent system is being removed from new PMS releases in 2026; this bundle requires it.

**Release (recommended):**

1. Download `AudiobookDB.bundle.zip` from the [releases](https://github.com/laxamentumtech/AudiobookDB.bundle/releases) page.
2. Unzip it.
3. Place the `AudiobookDB.bundle` folder in your Plex `Plug-ins` directory.
4. Restart Plex.

The installed bundle should look like this (only `Contents/` matters; `Info.plist` inside it declares the agent):

```
Plug-ins/
└── AudiobookDB.bundle/
    └── Contents/
        ├── Code/
        │   ├── __init__.py      # Album + Artist agents
        │   ├── _version.py
        │   ├── api_client.py
        │   ├── logging.py
        │   ├── metadata_ids.py
        │   ├── search_tools.py
        │   └── update_tools.py
        ├── DefaultPrefs.json
        └── Info.plist
```

After a restart, *AudiobookDB Agent* appears in the agent picker for audiobook libraries.

[Source installation](#source-installation) is available if you prefer deploying from the repository.

## Usage

1. Configure your personal key before full-library matching: [generate your personal AudiobookDB API key](https://audiobookdb.org/docs#authentication) and add it in Plex (steps below). Anonymous access is intended for browsing/searching, not full-library enrichment.
2. Open the **Edit Library** dialog for a Music library that holds your audiobooks in Plex (or create a new Music library).
3. On the **Advanced** tab, choose **AudiobookDB Agent** from the **Agent** drop-down. Existing libraries keep their current agent until you switch it here.
4. Optionally set the other preferences below, then run a refresh.

A refresh populates from AudiobookDB: books appear as albums — title, sort title, summary, studio, original release date, rating, genres, moods/styles, poster, and the native ID; authors appear as artists — name, sort title, summary, genres, poster, and native ID. Narrators are stored as Style tags, not as separate profiles. Series information is stored as Mood tags. An experimental preference can also contribute series names as collections.

Album title searches keep punctuation and accents. Without a matched parent author ID, the agent tries the title and author name first. It retries by title alone if no filtered result is usable. A matched parent author's native person ID counts as positive evidence even if the author's name differs. The agent skips results that conflict with an explicit book number during automatic matching. Use **Fix Match** to choose a result manually or change an existing pin.

A title match pins the book, not a specific recording. If the book has one visible release, **Fix Match** can show its narrator and a refresh can use its release metadata. For multiple releases, **Fix Match** retains a work-only result and offers up to five selectable recording results. Available local runtime and language guide their ordering, but the agent does not automatically select an edition. Results include cover and year information where known. You can also enter the Audible ASIN or composite native ID for the recording you want.

## Configuration

Preferences are set in the Plex Web App under **Settings → Server → Agents**: choose the agent, then click the gear icon to its right (see Plex's [Agents](https://support.plex.tv/articles/200241558-agents/) article).

To get a personal key, sign in at [audiobookdb.org](https://audiobookdb.org), open your account settings page (`/users/{your-id}/edit`), and use the **API Key** card's **Generate API key** button. The full key is shown only once; copy it and store it securely — do not share or publish it. The **Key ID** is not the secret key. In the agent's Plex preferences, enter the full key in **AudiobookDB API key (optional, raises rate limits)**, then save.

| Preference | Default | Description |
|---|---|---|
| `api_key` | *(empty)* | Enter your personal AudiobookDB API key for full-library matching. |
| `keep_existing_genres` | `false` | Keep existing genres in place. |
| `store_author_as_mood` | `true` | Append authors as Mood tags. |
| `sort_author_by_last_name` | `true` | Sort artist by name `[Last, First]`. |
| `simplify_title` | `false` | Simplify book titles (remove subtitle, series part, (un)abridged, etc.). |
| `use_chapter_titles` | `false` | Opt in to chapter titles for eligible local tracks. See the conditions below. |
| `store_series_as_collection` | `false` | Experimentally contribute series names as collections. See the limitations below. |
| `logging_level` | `WARN` | Level of plugin logging (`DEBUG`, `INFO`, `WARN`, `ERROR`). |

`use_chapter_titles` replaces only empty titles or generic chapter, track, or part titles. It requires multiple distinct local tracks and a verified release with a complete chapter sequence and matching timings. It cannot add embedded chapters to an M4B file.

`store_series_as_collection` contributes series names without removing existing tags or collections. Series Mood tags remain in place. Plex server import and filtering of these collections have not been live-verified, so this preference is experimental.

## Quick match

Enter an ASIN in the manual search field and the agent resolves it directly, skipping normal search. For automatic album matching, the agent also checks the scanner filename and all file parts supplied by Plex for ASINs. If those hints contain conflicting IDs, the agent does not select a recording by ASIN. Manual input overrides file hints:

- `B0XXXXXXXX` — an Audible ASIN, resolved through
  `GET /audiobooks/external/audible/{ASIN}` (albums) or
  `GET /people?external=Audible:{ASIN}` (artists). A book ASIN resolves to a single title, but a person ASIN shared by multiple people can yield several choices — use **Fix Match** (or enter the person ID manually) to pick one.
- Native IDs `book.<id>[.release.<id>]` and `person.<id>` are also accepted as manual search input; they are validated against the corresponding detail endpoint before a score-100 result is appended.

## API details

- Base URL: `https://api.audiobookdb.org/api` — see the [API documentation](https://audiobookdb.org/docs/api).
- Album titles shorter than 3 characters need an author credit. Without a key, the agent obtains the CSRF cookie needed for text search.
- Calls make up to 4 total attempts. `Retry-After` delays are capped at 60 seconds; the client does not guarantee honoring a longer server delay.
- The agent sends a configured API key only to the AudiobookDB API origin. If the key field is empty, the agent makes anonymous requests. Full-library matching still requires a personal key.
- Your Plex agent and any other AudiobookDB client using the same key share that account's allowance. Short-term request throttling and daily endpoint cost-unit budgets are separate; costs vary by endpoint, and there is no fixed books-per-day or requests-per-day equivalence. See the live [access tiers and limits](https://audiobookdb.org/docs#api-access-tiers) and [endpoint costs](https://audiobookdb.org/docs#endpoint-costs) rather than relying on static quota figures.
- A missing/invalid/expired/suspended key, a 429 throttle, or network/server errors are not evidence that an audiobook is absent from the catalog. The agent does not provide credential validation, a daily-budget stop, or automatic pause/resume. If a refresh fails, check the key and Plex preference; for throttling or exhausted daily allowance, wait for capacity to return before using Plex's refresh control. Do not immediately restart a full-library refresh. A genuine catalog miss is distinct and may require adding the external link to AudiobookDB.
- Image fetches are restricted to HTTPS on the catalog's image CDN (`cdn.audiobookdb.org`); other hosts and plain HTTP are refused.

## Migrating from Audnexus

`AudiobookDB.bundle` declares its own plug-in identifier (`com.plexapp.agents.audiobookdb`), so it coexists with the legacy `Audnexus.bundle` — nothing needs to be removed.

Once a library is switched to this agent, its old pinned IDs (`ASIN` / `ASIN_region`) keep working: on the next refresh the agent resolves the ASIN against AudiobookDB, populates metadata, and rewrites the pinned ID to the new native form (`book.<id>.release.<id>` / `person.<id>`).

Two cases are left untouched and reported in the log:

- An ASIN not in the AudiobookDB catalog — add the external link to AudiobookDB and retry.
- An artist ASIN that resolves to multiple people — use **Fix Match** (or enter the person ID manually) to disambiguate before the ID can be rewritten.

## Source installation

<details>
<summary>Install from the develop branch</summary>

Clone the `develop` branch into your Plex [Plug-ins](https://support.plex.tv/articles/201106098-how-do-i-find-the-plug-ins-folder/) directory — the `Contents/` folder must sit directly inside `AudiobookDB.bundle/` — then restart Plex:

```sh
cd "$HOME/Library/Application Support/Plex Media Server/Plug-ins"   # replace with your Plug-ins path
git clone -b develop https://github.com/laxamentumtech/AudiobookDB.bundle.git
```

</details>

## Contributing

There is no separate contributor guide; the essentials:

- Work on the `develop` branch.
- Tests run offline, fixture-backed, through plain `unittest`:

  ```sh
  make test        # Python 3, local
  make test-py2    # python:2.7-slim in Docker
  ```

- The bundle targets the Python 2.7 Plex sandbox; keep new code py2/py3-compatible.
- CI (`.github/workflows/test.yml`) runs the suite on Python 3.9/3.11/3.12 plus the Docker py2 job on every push to `develop` and on pull requests. Release tags `v*` run both suites and package `Contents/` into `AudiobookDB.bundle.zip`.
- See [tests/COVERAGE.md](https://github.com/laxamentumtech/AudiobookDB.bundle/blob/develop/tests/COVERAGE.md) for the module-to-test map.

## Acknowledgements

Metadata by [AudiobookDB](https://audiobookdb.org)

## License

[GPL-3.0-only](https://github.com/laxamentumtech/AudiobookDB.bundle/blob/develop/LICENSE)
