# AudiobookDB Agent

Plex audiobook metadata agent powered by the AudiobookDB catalog, with direct ASIN and native-ID matching.

[AudiobookDB Agent](https://github.com/laxamentumtech/AudiobookDB.bundle) is a [Plex](https://www.plex.tv) metadata agent for audiobook libraries that sources everything — books, releases, and people — from the [AudiobookDB](https://audiobookdb.org) public API (`<https://audiobookdb.org/api>`). It is the successor to the Audnexus agent and installs alongside it: it registers under its own plug-in identifier (`com.plexapp.agents.audiobookdb`), so the legacy `Audnexus.bundle` can stay installed. Each library keeps using whichever agent is selected for it until you switch it over, and old pinned Audnexus IDs migrate safely (see [Migrating from Audnexus](#migrating-from-audnexus)).

What sets it apart:

- AudiobookDB book, release, and person metadata — titles, summaries, studios, ratings, genres, moods, posters, and native IDs.
- Direct matching: drop an Audible ASIN (or an AudiobookDB native ID) into the manual search field, and the agent resolves it straight to a score-100 result, skipping free-text search.
- A safe migration path: libraries switched from Audnexus keep their pinned `ASIN` / `ASIN_region` IDs working and are re-pinned to AudiobookDB's native ID form on the next refresh.

## Contents

- [Install](#install)
- [Usage](#usage)
- [Configuration](#configuration)
- [Quick match](#quick-match)
- [Migrating from Audnexus](#migrating-from-audnexus)
- [API details](#api-details)
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

1. Open an audiobook library's **Library Settings** in Plex (or create a new one).
2. Choose **AudiobookDB Agent** as the agent. Existing libraries keep their current agent until you switch it here.
3. Optionally set the preferences below, then run a refresh.

A refresh populates from AudiobookDB: for albums — title, sort title, summary, studio, original release date, rating, genres, moods/styles, poster, and the native ID; for artists (stored as Plex *people*) — name, sort title, summary, genres, poster, and native ID. Series information is stored as Mood tags, not as Plex collections.

## Configuration

Preferences are set in the agent's settings (library settings → agent).

| Preference | Default | Description |
|---|---|---|
| `api_key` | *(empty)* | Optional AudiobookDB API key. Raises rate limits; anonymous access works without one. |
| `keep_existing_genres` | `false` | Keep existing genres in place. |
| `store_author_as_mood` | `true` | Append authors as Mood tags. |
| `sort_author_by_last_name` | `true` | Sort artist by name `[Last, First]`. |
| `simplify_title` | `false` | Simplify book titles (remove subtitle, series part, (un)abridged, etc.). |
| `logging_level` | `WARN` | Level of plugin logging (`DEBUG`, `INFO`, `WARN`, `ERROR`). |

## Quick match

Put an ASIN in the manual search field (or in the media filename for albums) and the agent resolves it directly to a single score-100 result, skipping normal search:

- `B0XXXXXXXXXX` — an Audible ASIN, resolved through
  `GET /audiobooks/external/audible/{ASIN}` (albums) or
  `GET /people?external=Audible:{ASIN}` (artists).
- Native IDs `book.<id>[.release.<id>]` and `person.<id>` are also accepted as manual search input; they are validated against the corresponding detail endpoint before a score-100 result is appended.

## API details

- Base URL: `https://audiobookdb.org/api` — see the [API documentation](https://audiobookdb.org/api).
- Free-text search requires a query of at least 3 characters.
- Calls retry up to 4 total attempts, honouring a server-supplied `Retry-After` (capped at 60 s).
- The `api_key` preference is attached to requests to the API origin only.
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

Clone the `develop` branch (the default branch is a blank shared base, not the code) into your Plex `Plug-ins` directory — the `Contents/` folder must sit directly inside `AudiobookDB.bundle/` — then restart Plex:

```sh
cd "$PLEX_PLUGINS_DIR"
git clone -b develop https://github.com/laxamentumtech/AudiobookDB.bundle.git
```

</details>

## Contributing

There is no separate contributor guide; the essentials:

- Work on the `develop` branch (the default branch is a blank shared base).
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
