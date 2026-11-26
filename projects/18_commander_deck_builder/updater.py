"""Update everything: the daily data job, shared by cron and the app's button.

Steps (each one's result is kept in ``data/update_status.json``):
  1. card data      check Scryfall for a new daily file (every 6 h), rebuild if new
  2. prices         today's price snapshot (once per Scryfall date)
  3. popularity     EDHREC's weekly top list (once per day)
  4. owned cards    keep tracking everything in your binder
  5. buylist        MTGJSON prices + Card Kingdom buylist (once per price date)
  6. casual decks   Archidekt sample, up to 150 new decks (once per day)
  7. tournaments    import up to 2 new big EDHTop16 events (once per day)
  8. card tags      Scryfall Tagger jobs (weekly)
  9. digest         the daily digest (once per price date)
 10. scanner export files for the Card Scanner artifact (once per price date)
``force`` re-runs the once-a-day steps even if they already ran today (sources
still only change when they publish); card tags stay weekly either way. A step that fails is recorded and the
others still run.

Only one update runs at a time: a lock file holds the running process id
(stale locks from a crashed run are cleared).

CLI (cron runs ``watchlist.py snapshot``, which calls this):
    python updater.py              # what's due
    python updater.py --force      # re-run the daily steps now
    python updater.py --status
"""

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"
STATUS_PATH = DATA / "update_status.json"
LOCK_PATH = DATA / "update.lock"
LOG_PATH = DATA / "update_log.txt"
STEPS = ("card data", "prices", "popularity", "owned cards", "buylist", "casual decks", "tournaments",
         "card tags", "digest", "scanner export")


# ---------------------------------------------------------------------------
# Status + lock
# ---------------------------------------------------------------------------


def load_status(path=STATUS_PATH):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return {"steps": {}}


def _save_status(status, path=STATUS_PATH):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(status, indent=1))
    tmp.replace(path)


def _alive(pid):
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


def running(lock=LOCK_PATH):
    """The pid of a running update, or None (a lock left by a dead process doesn't count)."""
    try:
        pid = int(Path(lock).read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None
    return pid if _alive(pid) else None


def _acquire(lock=LOCK_PATH):
    lock = Path(lock)
    lock.parent.mkdir(parents=True, exist_ok=True)
    if running(lock):
        return False
    try:
        lock.unlink(missing_ok=True)  # stale
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w") as f:
        f.write(f"{os.getpid()} {time.strftime('%Y-%m-%d %H:%M:%S')}")
    return True


def _release(lock=LOCK_PATH):
    try:
        if Path(lock).read_text().split()[0] == str(os.getpid()):
            Path(lock).unlink()
    except (OSError, IndexError):
        pass


# ---------------------------------------------------------------------------
# The job
# ---------------------------------------------------------------------------


def _ran_today(status, step, key=None):
    s = status["steps"].get(step) or {}
    return s.get("ok") and s.get("key", s.get("date")) == (key or dt.date.today().isoformat())


def run_update(force=False, log=print, status_path=STATUS_PATH, lock=LOCK_PATH):
    """Run every step that's due. Returns the status dict, or None if another update is running."""
    if not _acquire(lock):
        log(f"An update is already running (process {running(lock)}).")
        return None
    status = load_status(status_path)
    status.update({"running": True, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "finished": None,
                   "forced": force})
    _save_status(status, status_path)
    today = dt.date.today().isoformat()

    def record(step, ok, message, key=None):
        status["steps"][step] = {"ok": ok, "message": message, "at": time.strftime("%Y-%m-%d %H:%M"),
                                 "date": today, "key": key or today}
        _save_status(status, status_path)
        log(f"[{'ok' if ok else 'skipped'}] {step}: {message}")

    def step(name, fn, key=None, daily=True):
        if daily and not force and _ran_today(status, name, key):
            log(f"[done] {name}: already ran ({status['steps'][name]['message']})")
            return None
        try:
            message = fn()
            record(name, True, message, key)
            return message
        except Exception as exc:  # one failing source mustn't stop the rest
            record(name, False, f"{type(exc).__name__}: {exc}", key)
            log(traceback.format_exc(limit=2))
            return None

    try:
        import card_db
        import watchlist
        from dotenv import load_dotenv
        from scan_binder import ENV_PATH
        load_dotenv(ENV_PATH)

        holder = {}

        def card_data():
            path = card_db.ensure_db(max_age_hours=watchlist.SCRYFALL_CHECK_HOURS, log=log)
            holder["db"] = card_db.CardDB(path)
            return f"Scryfall file of {holder['db'].meta().get('updated_at', '?')[:10]}"
        step("card data", card_data, daily=False)
        if "db" not in holder:
            raise RuntimeError("no card data")
        db, wl = holder["db"], watchlist.WatchList()
        try:
            def prices():
                date, new = wl.snapshot(db)
                holder["date"] = date
                return f"{date} {'saved' if new else 'already saved'} ({len(wl.dates())} days)"
            step("prices", prices, daily=False)
            price_date = holder.get("date") or (wl.dates() or [today])[-1]

            def popularity():
                saved = wl.snapshot_edhrec(watchlist.fetch_top("week"))
                return f"{'saved' if saved else 'already saved'} ({len(wl.edhrec_dates())} days)"
            step("popularity", popularity)

            def owned():
                import portfolio
                return f"{len(portfolio.track_owned(db, wl))} cards tracked"
            step("owned cards", owned)

            def buylist():
                import price_history
                return f"{price_history.update_buylist(db, wl, log=log):,} cards"
            step("buylist", buylist, key=price_date)

            def casual():
                import archidekt
                a = archidekt.Archidekt()
                try:
                    added = a.sample(max_new=150, log=log)
                    a.set_meta("sampled_on", today)
                    return f"{added} new decks ({a.count():,} saved)"
                finally:
                    a.close()
            step("casual decks", casual)

            def events():
                import tournaments
                names = tournaments.auto_import(log=log)
                return ("imported " + "; ".join(names)) if names else "nothing new"
            step("tournaments", events)

            def tags():
                import scryfall_tags
                if not scryfall_tags.is_stale():  # weekly even when forced: a full refresh is ~90
                    return "up to date (weekly)"   # Scryfall pages and repeated runs get rate-limited
                data = scryfall_tags.refresh(log=log)
                card_db.ensure_db(log=log, rebuild=True)
                return f"{len(data['roles']):,} cards"
            step("card tags", tags, daily=False)

            def digest():
                import alerts
                path, _ = alerts.daily_digest(db, wl, price_date, log=log)
                return f"{path.name}"
            step("digest", digest, key=price_date)

            def scanner():
                import export_scanner_data
                return export_scanner_data.export_all(log=lambda *_: None)
            step("scanner export", scanner, key=price_date)
        finally:
            wl.close()
            db.close()
    except Exception as exc:
        log(f"Update stopped: {exc}")
    finally:
        status.update({"running": False, "finished": time.strftime("%Y-%m-%d %H:%M:%S")})
        _save_status(status, status_path)
        _release(lock)
    return status


def start_background(force=False, log_path=LOG_PATH):
    """Start ``updater.py`` as its own process (for the app's button). False if one is running."""
    if running():
        return False
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    out = log_path.open("w")
    subprocess.Popen([sys.executable, str(HERE / "updater.py")] + (["--force"] if force else []),
                     cwd=HERE, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    return True


# ---------------------------------------------------------------------------
# Freshness (for the panel): what each source has right now
# ---------------------------------------------------------------------------


def freshness():
    """``[(source, latest, detail)]`` read from the local files only (no network)."""
    import archidekt
    import card_db
    import tournaments
    import watchlist
    out = []
    try:
        db = card_db.CardDB(card_db.DATA_DIR / card_db.DB_NAME)
        out.append(("Card data (Scryfall)", db.meta().get("updated_at", "")[:10], f"{db.count():,} cards"))
        db.close()
    except Exception:
        out.append(("Card data (Scryfall)", None, "not built yet"))
    wl = watchlist.WatchList()
    try:
        dates = wl.dates()
        out.append(("Prices", dates[-1] if dates else None, f"{len(dates)} days of history"))
        row = wl.conn.execute("SELECT MAX(day) FROM snapshots WHERE buy_cents IS NOT NULL").fetchone()
        out.append(("Buylist (Card Kingdom)", watchlist._date(row[0]) if row and row[0] else None, "via MTGJSON"))
        e = wl.edhrec_dates()
        out.append(("EDHREC popularity", e[-1] if e else None, f"{len(e)} days"))
        out.append(("Digest", wl.get_meta("digest_date"), "data/digests"))
    finally:
        wl.close()
    a = archidekt.Archidekt()
    try:
        out.append(("Casual decks (Archidekt)", a.get_meta("sampled_on"), f"{a.count():,} decks"))
    finally:
        a.close()
    events = tournaments.saved_events()
    out.append(("Tournaments (EDHTop16)", max((e["date"] for e in events), default=None),
                f"{len(events)} events, newest event date"))
    try:
        import scryfall_tags
        tags = json.loads(scryfall_tags.TAGS_PATH.read_text())
        out.append(("Card tags (Scryfall Tagger)", tags.get("fetched"), f"{len(tags['roles']):,} cards, weekly"))
    except (OSError, json.JSONDecodeError, KeyError):
        out.append(("Card tags (Scryfall Tagger)", None, "not fetched yet"))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="Update every data source (what cron runs).")
    parser.add_argument("--force", action="store_true", help="re-run the once-a-day steps now")
    parser.add_argument("--status", action="store_true", help="show the last run and data dates")
    args = parser.parse_args(argv)
    if args.status:
        st = load_status()
        print(f"Last run: {st.get('started')} -> {st.get('finished')}" + (" (running)" if running() else ""))
        for name in STEPS:
            s = st["steps"].get(name)
            print(f"  {name:13} " + (f"{'ok' if s['ok'] else 'FAILED'} {s['at']}: {s['message']}" if s else "never"))
        for source, latest, detail in freshness():
            print(f"  {source:28} {latest or 'n/a':12} {detail}")
        return 0
    result = run_update(force=args.force, log=lambda m: print(m, flush=True))
    return 0 if result is not None else 2


if __name__ == "__main__":
    sys.exit(main())
