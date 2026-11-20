"""Daily digest: the day's top signals, your watched cards' moves, and target-price hits.

Built once per new price date (``watchlist.py snapshot`` calls it after saving a
new day, so the cron job produces it automatically) and saved to
``data/digests/YYYY-MM-DD.md``.

Email is optional and off until you set all of these in the repo-root ``.env``:
    WATCH_SMTP_HOST, WATCH_SMTP_PORT (default 587), WATCH_SMTP_USER,
    WATCH_SMTP_PASSWORD, WATCH_EMAIL_TO
Nothing is sent while any of them is missing.

CLI:
    python alerts.py              # build today's digest (again) and print it
    python alerts.py --send       # also email it, if email is set up
"""

import argparse
import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

import card_db
import edhrec_client
import portfolio
import watchlist

DIGEST_DIR = Path(__file__).parent / "data" / "digests"
WATCHED_MOVE_PCT = 10.0
SMTP_KEYS = ("WATCH_SMTP_HOST", "WATCH_SMTP_USER", "WATCH_SMTP_PASSWORD", "WATCH_EMAIL_TO")


def _money(v):
    return "n/a" if v is None else f"${v:,.2f}"


def _pct(v):
    return "n/a" if v is None else f"{v:+.1f}%"


def build_digest(db, wl, date, rising=None, spec=None, risers=None, hits=None, binder=None, top=10):
    """Markdown digest. Every input can be passed in (tests) or is computed."""
    if rising is None:
        try:
            rising = watchlist.rising_cards(db)
        except edhrec_client.EdhrecError:
            rising = []
    spec = watchlist.spec_signals(db, wl, rising, out_of_print_only=True) if spec is None else spec
    risers = wl.price_risers(db, days=1, min_usd=1.0, limit=top) if risers is None else risers
    hits = wl.target_hits(db) if hits is None else hits
    binder = portfolio.binder_value(db, wl) if binder is None else binder
    watched = wl.watched(db, rising)

    lines = [f"# Card watch digest - {date}", ""]
    lines += ["## Target prices reached", ""]
    lines += [f"- **{h['name']}** is {_money(h['usd'])} ({h['direction']} your {_money(h['target'])} target)"
              for h in hits] or ["None today."]
    moves = [w for w in watched if w["change_7d_pct"] is not None and abs(w["change_7d_pct"]) >= WATCHED_MOVE_PCT]
    lines += ["", f"## Your watched cards that moved {WATCHED_MOVE_PCT:.0f}%+ in 7 days", ""]
    lines += [f"- {w['name']}: {_money(w['usd'])} ({_pct(w['change_7d_pct'])} 7 days, "
              f"{_pct(w['since_added_pct'])} since added)" for w in moves] or ["None."]
    lines += ["", "## Top spec signals (out of print)", ""]
    lines += [f"{i}. **{r['name']}** {_money(r['usd'])}, score {r['score']}: {'; '.join(r['reasons'])}"
              for i, r in enumerate(spec[:top], 1)] or ["None (EDHREC unreachable?)."]
    lines += ["", f"## Biggest price jumps since the last snapshot ({risers.get('from') or 'n/a'} -> "
              f"{risers.get('to') or 'n/a'})", ""]
    lines += [f"- {r['name']}: {_money(r['old'])} -> {_money(r['new'])} ({_pct(r['change_pct'])})"
              for r in risers["rows"][:top]] or ["Not enough history yet."]
    lines += ["", "## Your binder", "",
              f"{binder['cards']} cards worth {_money(binder['total'])} today."]
    lines += [f"- rising: {c['name']} {_pct(c['change_pct'])} (7 days)" for c in binder["risers"]]
    lines += ["", "_Signals to research, not predictions. Prices: Scryfall (TCGplayer / Cardmarket); "
              "popularity: EDHREC._"]
    return "\n".join(lines)


def email_settings(env=None):
    env = os.environ if env is None else env
    if not all(env.get(k) for k in SMTP_KEYS):
        return None
    return {"host": env["WATCH_SMTP_HOST"], "port": int(env.get("WATCH_SMTP_PORT") or 587),
            "user": env["WATCH_SMTP_USER"], "password": env["WATCH_SMTP_PASSWORD"], "to": env["WATCH_EMAIL_TO"]}


def send_email(subject, body, settings, smtp=smtplib.SMTP):
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, settings["user"], settings["to"]
    msg.set_content(body)
    with smtp(settings["host"], settings["port"], timeout=30) as server:
        server.starttls()
        server.login(settings["user"], settings["password"])
        server.send_message(msg)


def daily_digest(db, wl, date, send=None, out_dir=DIGEST_DIR, log=print):
    """Write the day's digest file (once per date unless forced) and email it if set up.

    ``send``: True = email if configured, False = never, None = email only the
    first time this date's digest is built."""
    out_dir = Path(out_dir)
    path = out_dir / f"{date}.md"
    first = wl.get_meta("digest_date") != date
    text = build_digest(db, wl, date)
    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n")
    wl.set_meta("digest_date", date)
    settings = email_settings()
    if (send is True or (send is None and first)) and settings:
        try:
            send_email(f"Card watch digest {date}", text, settings)
            log(f"Digest emailed to {settings['to']}.")
        except (OSError, smtplib.SMTPException) as exc:
            log(f"Digest saved, but email failed: {exc}")
    return path, text


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build (and optionally email) today's card watch digest.")
    parser.add_argument("--send", action="store_true", help="email it too (needs WATCH_SMTP_* in .env)")
    args = parser.parse_args(argv)
    from dotenv import load_dotenv
    from scan_binder import ENV_PATH
    load_dotenv(ENV_PATH)
    db = card_db.open_db(log=lambda m: print(m, file=sys.stderr))
    wl = watchlist.WatchList()
    try:
        date = (db.meta().get("updated_at") or "")[:10]
        path, text = daily_digest(db, wl, date, send=args.send or False, log=lambda m: print(m, file=sys.stderr))
        print(text)
        print(f"\n(saved to {path})", file=sys.stderr)
    finally:
        wl.close()
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
