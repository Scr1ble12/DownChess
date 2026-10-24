# DownChess

A personal, locally run tool that pulls your Chess.com and Lichess games, analyzes them with Stockfish, and reports your biggest weaknesses with example games. Rapid games are the default focus.

## Status

| Step | What | State |
| --- | --- | --- |
| 1 | Fetch and store games from both sites | Done |
| 2 | Basic stats page | Next |
| 3 | Engine pass (Stockfish move labels, accuracy) | |
| 4 | Top 3 weaknesses page | |

## Setup

Needs Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Optional environment variables:

| Variable | What it does |
| --- | --- |
| `DOWNCHESS_CONTACT` | Contact info (e.g. your email) put in the User-Agent, as both sites ask. Defaults to this repo's URL. |
| `LICHESS_TOKEN` | A Lichess personal API token. Not needed, but raises the download speed from about 20 to 30 games per second. |

## Usage

```bash
python cli.py fetch chesscom:<user>     # rapid games from Chess.com
python cli.py fetch lichess:<user>      # rapid games from Lichess
python cli.py summary chesscom:<user>   # what's stored
python cli.py moves tests/fixtures/sample.pgn   # print a PGN's moves
```

Run `fetch` again any time; it only downloads and stores new games. Flags:

- `--all-speeds` stores bullet, blitz, classical and daily games too.
- `--full` ignores what's stored and re-downloads the whole history (use this once if you switch to `--all-speeds` after a rapid-only fetch).

Games go into `data/downchess.db` (SQLite, ignored by git). Use `--db path` for a different file.

## How fetching works

| | Chess.com | Lichess |
| --- | --- | --- |
| Endpoint | `/pub/player/{user}/games/archives`, then one request per month | `/api/games/user/{user}` streamed as NDJSON |
| Rerun rule | Months already fetched are skipped, except the newest one (it may have been fetched mid-month) | Only games after the newest stored one (`since`) |
| Evals | None, Stockfish adds them in Step 3 | Stored when the game was already analysed on Lichess |

Requests are sequential, send a descriptive User-Agent, and wait a minute on HTTP 429. Chess960 and other variants, and unfinished games, are skipped.

## Tests

```bash
pytest
```

Tests use saved fixture responses, so they don't touch the network.
