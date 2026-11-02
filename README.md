# DownChess

[![tests](https://github.com/Scr1ble12/DownChess/actions/workflows/tests.yml/badge.svg)](https://github.com/Scr1ble12/DownChess/actions/workflows/tests.yml)

**Find out what's actually costing you games.** DownChess pulls every game for a Chess.com or Lichess username, runs Stockfish over them, and reports your three biggest weaknesses with the numbers behind them and example positions from your own games.

It comes as a **desktop app for Mac and Windows** with the official Stockfish 18 built in: no Terminal, no installs, everything clickable. The original Python command-line version is still here too. Rapid games are the default focus.

| Games | Game review |
| --- | --- |
| ![Games page](docs/images/app-games.png) | ![Game review page](docs/images/app-review.png) |

<sub>Screenshots use generated demo games.</sub>

## Desktop app

### Download

Get the latest installer from the [Releases page](https://github.com/Scr1ble12/DownChess/releases):

- **Mac with Apple silicon (M1 or later):** `DownChess-…-mac-arm64.dmg`
- **Intel Mac:** `DownChess-…-mac-x64.dmg`
- **Windows:** `DownChess-…-windows-setup.exe`

The app isn't code-signed (that costs $99 a year from Apple), so the first launch needs one extra step:

- **Mac:** open the .dmg and drag DownChess into Applications. Open it once; when macOS says it can't verify the app, open **System Settings > Privacy & Security**, scroll down, and click **Open Anyway**. After that it opens normally.
- **Windows:** if SmartScreen says "Windows protected your PC", click **More info > Run anyway**.

### Using it

1. **Games:** pick Chess.com or Lichess, type your username, choose a **From / To** date range (or *Last 3 months*, *Last year*, *All time*) and a time control, then click **Download**. Downloading again only adds games you don't have.
2. Still on **Games**, click **Analyse** to run Stockfish over your most recent games. You can stop at any time and continue later.
3. **Stats**, **Top 3 weaknesses** and **Game review** work on the player and time control picked at the top. On the weaknesses page, *Review this game* opens any example game move by move.
4. **Game review** also takes a pasted PGN or a Lichess link. Use the arrow keys or the buttons to step through moves.

Your games and analysis are saved on your computer only. *Delete* on the Games page removes them.

### Building it yourself

Needs Node.js 22.

```bash
cd app
npm install
npm run stockfish   # downloads the official Stockfish for this computer into app/stockfish/
npm start           # runs the app
npm test            # unit tests (uses that Stockfish)
npm run dist        # builds an installer into app/dist/
```

GitHub Actions builds the Mac and Windows installers on every push (download them from the run's *Artifacts*). Pushing a tag such as `v1.0.0` publishes them on the Releases page.

How it's put together: an Electron window (`app/main.cjs`) runs Stockfish processes and makes the requests to Chess.com and Lichess; the page itself (`app/renderer/`) is plain JavaScript modules that port the Python logic one-to-one (`normalize`, `classify`, `stats`, `weaknesses`, `review`), and stores games in the browser engine's IndexedDB.

## Python command-line version

The same analysis as a Python package with a Streamlit dashboard, for running from the Terminal. The weakness checks and move labels described here are the same in the desktop app.

### What it does

- **Fetches** your full public game history from Chess.com and Lichess into one SQLite file. Reruns only download new games.
- **Analyses** every move with Stockfish: centipawn loss, a label (ok, inaccuracy, mistake, blunder), the game phase, and a Lichess-style accuracy score. Games Lichess already analysed reuse that analysis.
- **Summarises** your record by color, opponent rating, opening and month.
- **Reviews any single game** move by move, like Chess.com's Game Review but free and local: your games, a pasted PGN, or a Lichess link.
- **Ranks your weaknesses.** Six checks each compare you with a baseline from your own games. The three biggest gaps are shown with example boards: the position before your worst move, your move (dark arrow) and the engine's best move (white arrow).

| Check | You | Compared with |
| --- | --- | --- |
| Game phase | Avg centipawn loss in your worst phase | The other phases |
| Openings | Score in your worst opening and color (10+ games) | Your overall score |
| Time trouble | Blunder rate with under 2 min or 10% of your time left | Blunder rate with more time |
| Converting wins | Share of games you don't win after reaching +3 | How often opponents fail to win from +3 against you |
| After a loss | Score in the next game within 2 hours of a loss | Score after a win |
| Rating gap | Score against opponents 50+ points higher or lower | The Elo-expected score |

A check has to be at least 10% worse than its baseline to count, and every number shows the sample it's based on.

#### Game review

A free, local take on Chess.com's Game Review, for any single game. Open **Game review** in the sidebar, then either pick one of your stored games or paste a PGN or game link:

- **Stored games** show their saved analysis straight away. Games the engine pass hasn't reached get an *Analyse* button; the result is saved, so it also counts towards your stats.
- **Pasted PGNs** (Chess.com: Share > PGN; Lichess: Share & export > PGN) are analysed as soon as you paste them. Lichess links are downloaded for you. Chess.com links work for games you've already fetched, since Chess.com has no public API for one game.

You get each player's accuracy and a count of best, good, book, inaccuracy, mistake and blunder moves, then step through the game on the board: the move played is the dark arrow and Stockfish's choice is the white arrow. *Next error* jumps to your next inaccuracy, mistake or blunder. A key-moments table and the full move list sit underneath. Raise *Engine depth* for a slower, stronger review.

<img src="docs/images/review.png" alt="Game review page" width="480">

### Quick start

Needs Python 3.11+ and Stockfish (`brew install stockfish` on macOS, `apt install stockfish` on Debian/Ubuntu).

```bash
git clone https://github.com/Scr1ble12/DownChess.git
cd DownChess
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python cli.py fetch chesscom:<username>     # or lichess:<username>
python cli.py analyze chesscom:<username>   # Stockfish over your latest 200 rapid games
streamlit run app.py                        # opens the dashboard in your browser
```

Streamlit keeps its terminal busy, so run other commands in a second terminal tab.

### Commands

| Command | What it does |
| --- | --- |
| `python cli.py fetch <site>:<user>` | Download games (rapid only). `--all-speeds` for every time control, `--full` to re-download everything. |
| `python cli.py analyze <site>:<user>` | Run Stockfish. `--games 500` to go further back, `--depth 14` to go deeper, `--workers N` to set processes. Safe to stop with Ctrl+C; the next run continues. |
| `python cli.py summary <site>:<user>` | Show what's stored, by time control. |
| `python cli.py moves <file.pgn>` | Print a PGN's moves and clocks. |

Optional environment variables:

| Variable | What it does |
| --- | --- |
| `STOCKFISH_PATH` | Path to the Stockfish binary, if it isn't on your `PATH`. |
| `LICHESS_TOKEN` | A Lichess API token. Not needed, but speeds up downloads from about 20 to 30 games per second. |
| `DOWNCHESS_CONTACT` | Contact info for the User-Agent both sites ask for. Defaults to this repo's URL. |
| `DOWNCHESS_DB` | A different SQLite file for the dashboard. Default `data/downchess.db`. |

### How it works

```
fetch (Chess.com / Lichess)  ->  normalize  ->  SQLite  ->  Stockfish pass  ->  stats  ->  Streamlit
```

Each stage reads from and writes to SQLite, so any stage can be rerun on its own.

- **Fetching.** Chess.com serves monthly archives; months already stored are skipped except the newest. Lichess streams NDJSON; only games after the newest stored one are requested. Requests are sequential with a descriptive User-Agent and a one-minute wait on HTTP 429, as both sites ask.
- **One game format.** Both sites provide a PGN, so moves, clocks (`%clk`) and Lichess evals (`%eval`) all go through one python-chess path in `fetch/normalize.py`. Nothing downstream knows which site a game came from.
- **Engine pass.** One single-threaded Stockfish per CPU core, each on a different game, which is faster at shallow depth than one multi-threaded engine. Workers only compute; the main process does all writes. The first 8 plies count as opening theory. Results are committed per game, and asking for a greater depth re-queues games.
- **Move labels.** Centipawn loss is the mover's drop in eval across the move, with evals capped at ±1000: inaccuracy ≥ 50, mistake ≥ 100, blunder ≥ 300. Endgame means at most 13 points of non-pawn material per side. Accuracy uses Lichess's win-percentage formula.

### Project layout

```
fetch/      chesscom.py, lichess.py, normalize.py, sync.py, http.py
db/         schema.sql, store.py
engine/     runner.py (batch Stockfish), classify.py (labels, phase, accuracy), review.py (single-game review)
stats/      games.py, results.py, analysis.py, weaknesses.py
ui/         views.py (pages), review.py (game review page), board.py (board images), text.py (plain-text tables)
app/        the desktop app (Electron + JavaScript port), see above
app.py      Streamlit dashboard
cli.py      fetch / analyze / summary / moves
tests/      pytest suite with saved site responses (no network needed)
```

### Tests

```bash
pytest
```

The suite uses saved Chess.com and Lichess responses, so it never touches the network. Engine tests run against a real Stockfish when one is installed and are skipped otherwise. GitHub Actions runs everything on each push.

### Ideas for later

- Practice drills built from your own mistakes
- Tactical motif tagging (forks, pins, hanging pieces)
- Comparing against players at your rating instead of only against yourself

## Credits

[Stockfish](https://stockfishchess.org) (GPLv3) does the analysis; the desktop app ships the official release binary. [chess.js](https://github.com/jhlywa/chess.js) (BSD) handles moves in the app, and the piece drawings are by Colin M.L. Burnett, via [python-chess](https://github.com/niklasf/python-chess).
