# DownChess

A personal, locally run tool that pulls your Chess.com and Lichess games, analyzes them with Stockfish, and reports your biggest weaknesses with example games. Rapid games are the default focus.

## Status

| Step | What | State |
| --- | --- | --- |
| 1 | Fetch and store games from both sites | Done |
| 2 | Basic stats page | Done |
| 3 | Engine pass (Stockfish move labels, accuracy) | Done |
| 4 | Top 3 weaknesses page | Done |

## Setup

Needs Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Install Stockfish for the engine pass (macOS: `brew install stockfish`). If it's somewhere unusual, set `STOCKFISH_PATH`.

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

Then run Stockfish over your recent games:

```bash
python cli.py analyze chesscom:<user>                # latest 200 rapid games, depth 12
python cli.py analyze chesscom:<user> --games 500    # go further back
python cli.py analyze chesscom:<user> --depth 14     # re-analyse deeper
```

It uses one Stockfish process per CPU core. You can stop it with Ctrl+C at any time; finished games are saved and the next run continues where it left off. Lichess games that Lichess already analysed reuse that analysis instead of running the engine. Each move gets a label (ok, inaccuracy ≥ 50 cp, mistake ≥ 100, blunder ≥ 300), a phase (opening, middlegame, endgame), and an accuracy score using Lichess's formula. The first 8 plies are treated as opening theory and not judged.

Then open the dashboard:

```bash
streamlit run app.py
```

It's plain white-on-black text: your record, results by color, by opponent rating and by opening, and your rating by month. Pick a player and time control (rapid by default) in the sidebar. Set `DOWNCHESS_DB` to point it at a different database file.

Pick **Top 3 weaknesses** in the sidebar for the report. Each metric compares you with a baseline from your own games:

| Metric | You | Compared with |
| --- | --- | --- |
| Phase | Avg cp loss per move in your worst phase | The other phases |
| Opening | Score in your worst opening + color (10+ games) | Your overall score |
| Time trouble | Blunder rate with under 2 min or 10% of your time left | Blunder rate with more time |
| Converting wins | Share of games you don't win after reaching +3 | How often opponents fail to win from +3 against you |
| After a loss | Score in the next game within 2 hours of a loss | Score after a win |
| Rating gap | Score vs opponents 50+ points higher or lower | Elo-expected score |

A metric needs to be at least 10% worse than its baseline to count. The three biggest gaps are shown with three example games each: a board before your worst move, with your move (dark arrow) and the engine's best move (white arrow). "All checks" lists every metric with its sample size.

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
