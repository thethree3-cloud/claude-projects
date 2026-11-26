"""Do the spec signals work? Check them against what prices did next.

For every day with an EDHREC snapshot, re-score the cards on that day's list
the same way ``watchlist.spec_signals`` does (EDHREC trend x supply x price
already moved), then look up each card's price ``horizon`` days later. The
top-scored cards should rise more often than the list as a whole; if they
don't, the weights need changing.

Honest limits: supply uses today's printing data (a reprint announced since
then is already known), and results are noisy until there are several weeks of
days. Until a day has a price ``horizon`` days later, it can't be scored.

CLI:
    python backtest.py                 # horizon 7 days, top 20
    python backtest.py --horizon 3 --top 10
"""

import argparse
import datetime as dt
import statistics
import sys

import card_db
import watchlist

RISE_PCT = 10.0  # a "hit" = price up at least this much over the horizon


def _price_on(wl, date):
    """{oracle_id: usd} for one snapshot date."""
    return {r[0]: r[1] / 100 for r in wl.conn.execute(
        "SELECT c.oracle_id, s.cents FROM snapshots s JOIN card_ids c ON c.id = s.card WHERE s.day = ?",
        (watchlist._day(date),))}


def _edhrec_on(wl, date):
    """[(name, trend)] from one EDHREC snapshot date."""
    return [(r[0], (r[1] or 0) / 1000) for r in wl.conn.execute(
        "SELECT n.name, d.trend_milli FROM edhrec_days d JOIN edhrec_names n ON n.id = d.name WHERE d.day = ?",
        (watchlist._day(date),))]


def _nearest(dates, target, before=True):
    """Latest date <= target (before=True) or earliest date >= target."""
    pick = [d for d in dates if (d <= target if before else d >= target)]
    return (pick[-1] if before else pick[0]) if pick else None


def _summary(returns):
    if not returns:
        return {"n": 0, "mean": None, "median": None, "hit_rate": None}
    return {"n": len(returns), "mean": round(statistics.mean(returns), 1),
            "median": round(statistics.median(returns), 1),
            "hit_rate": round(sum(r >= RISE_PCT for r in returns) / len(returns) * 100, 1)}


def run(db, wl, horizon=7, top=20, min_usd=0.5, today=None):
    """``{"days": [...per scored day...], "top": summary, "all": summary, "needed": ...}``."""
    price_dates = wl.dates()
    edhrec_dates = wl.edhrec_dates()
    today = today or dt.date.today().isoformat()
    days, top_returns, all_returns = [], [], []
    for d in edhrec_dates:
        start = _nearest(price_dates, d, before=True)
        target = (dt.date.fromisoformat(d) + dt.timedelta(days=horizon)).isoformat()
        end = _nearest(price_dates, target, before=False)
        if start is None or end is None:
            continue
        before = _nearest(price_dates, (dt.date.fromisoformat(start) - dt.timedelta(days=7)).isoformat())
        p0, p1 = _price_on(wl, start), _price_on(wl, end)
        pb = _price_on(wl, before) if before and before != start else {}
        listed = _edhrec_on(wl, d)
        cards = db.get_many([n for n, _ in listed])
        supply = db.supply(list(cards), today)
        scored = []
        for name, trend in listed:
            card = cards.get(name)
            if card is None or trend <= 0:
                continue
            oid = card["oracle_id"]
            if oid not in p0 or oid not in p1 or p0[oid] < min_usd:
                continue
            prior = round((p0[oid] - pb[oid]) / pb[oid] * 100, 1) if pb.get(oid) else None
            score = trend * watchlist.supply_factor(supply.get(name), d)[0] * watchlist.price_factor(prior)[0]
            scored.append((score, round((p1[oid] - p0[oid]) / p0[oid] * 100, 1), name))
        if not scored:
            continue
        scored.sort(reverse=True)
        best = [r for _, r, _ in scored[:top]]
        rest = [r for _, r, _ in scored]
        top_returns += best
        all_returns += rest
        days.append({"date": d, "from": start, "to": end, "cards": len(scored),
                     "top": _summary(best), "all": _summary(rest),
                     "best_names": [n for _, _, n in scored[:5]]})
    needed = None
    if not days:
        first = edhrec_dates[0] if edhrec_dates else today
        ready = (dt.date.fromisoformat(first) + dt.timedelta(days=horizon)).isoformat()
        needed = f"needs a price snapshot on or after {ready} ({horizon} days after the first EDHREC snapshot)"
    return {"horizon": horizon, "top_n": top, "days": days, "top": _summary(top_returns),
            "all": _summary(all_returns), "needed": needed}


# ---------------------------------------------------------------------------
# Price-only checks (possible now, from backfilled history)
# ---------------------------------------------------------------------------

MOMENTUM_BUCKETS = (("fell 10%+", None, -10), ("flat (-10% to +10%)", -10, 10), ("up 10-30%", 10, 30),
                    ("up 30%+", 30, None))


def _supply_bucket(label):
    for key, name in (("reprint coming", "reprint on the way"), ("Reserved List", "Reserved List"),
                      ("in print", "still in print"), ("plentiful", "8+ printings"),
                      ("1 printing", "1 printing (out of print)")):
        if key in label:
            return name
    return "2-7 printings" if "printings" in label else "unknown"


def price_patterns(db, wl, horizon=14, lookback=7, min_usd=1.0, step=7, today=None):
    """What prices did next, grouped two ways (no EDHREC data needed):

    - momentum: price change over the ``lookback`` days before a start day ->
      change over the ``horizon`` days after (tests the "price already up" penalty)
    - supply: printings / Reserved List / in print -> change over ``horizon``
      (tests the supply weights)

    Start days are every ``step`` days with prices ``lookback`` before and
    ``horizon`` after. Supply uses today's printing data (a small look-ahead)."""
    dates = wl.dates()
    today = today or dt.date.today().isoformat()
    starts = []
    for d in dates:
        back = (dt.date.fromisoformat(d) - dt.timedelta(days=lookback)).isoformat()
        fwd = (dt.date.fromisoformat(d) + dt.timedelta(days=horizon)).isoformat()
        if back in dates and fwd in dates and (not starts or
                                               (dt.date.fromisoformat(d) - dt.date.fromisoformat(starts[-1][0])).days >= step):
            starts.append((d, back, fwd))
    if not starts:
        return {"starts": [], "momentum": [], "supply": [], "needed": f"needs {lookback + horizon}+ days of prices"}
    names = {r["oracle_id"]: r["name"] for r in db.conn.execute("SELECT oracle_id, name FROM cards")}
    supply = db.supply(list(names.values()), today)
    labels = {oid: watchlist.supply_factor(supply.get(n), today)[1] for oid, n in names.items() if n in supply}
    mom = {b[0]: [] for b in MOMENTUM_BUCKETS}
    sup = {}
    for d, back, fwd in starts:
        p0, pb, p1 = _price_on(wl, d), _price_on(wl, back), _price_on(wl, fwd)
        for oid, now in p0.items():
            if now < min_usd or oid not in p1 or not pb.get(oid):
                continue
            prior = (now - pb[oid]) / pb[oid] * 100
            nxt = (p1[oid] - now) / now * 100
            for name, lo, hi in MOMENTUM_BUCKETS:
                if (lo is None or prior >= lo) and (hi is None or prior < hi):
                    mom[name].append(nxt)
            if oid in labels:
                sup.setdefault(_supply_bucket(labels[oid]), []).append(nxt)
    return {"starts": [s[0] for s in starts], "horizon": horizon, "lookback": lookback, "needed": None,
            "momentum": [{"group": n, **_summary(mom[n])} for n, _, _ in MOMENTUM_BUCKETS],
            "supply": sorted(({"group": g, **_summary(v)} for g, v in sup.items()), key=lambda r: -(r["mean"] or 0))}


def format_patterns(res):
    if res["needed"]:
        return f"Price patterns: not enough history yet ({res['needed']})."
    lines = [f"Price patterns over {len(res['starts'])} start days ({res['starts'][0]} to {res['starts'][-1]}), "
             f"next {res['horizon']} days, cards $1+:", "", f"After the price moved over the prior {res['lookback']} days:"]
    for r in res["momentum"]:
        lines.append(f"  {r['group']:<22} mean {r['mean']:+6.1f}%  median {r['median']:+6.1f}%  "
                     f"{r['hit_rate']:4.0f}% rose 10%+  (n={r['n']:,})" if r["n"] else f"  {r['group']:<22} no cards")
    lines += ["", "By supply:"]
    for r in res["supply"]:
        lines.append(f"  {r['group']:<26} mean {r['mean']:+6.1f}%  median {r['median']:+6.1f}%  "
                     f"{r['hit_rate']:4.0f}% rose 10%+  (n={r['n']:,})")
    return "\n".join(lines)


def format_report(res):
    if res["needed"]:
        return f"Not enough history yet: {res['needed']}."
    t, a = res["top"], res["all"]
    lines = [f"Spec-signal backtest: {len(res['days'])} day(s), price change over {res['horizon']} days.",
             f"Top {res['top_n']} by score: mean {t['mean']:+.1f}%, median {t['median']:+.1f}%, "
             f"{t['hit_rate']:.0f}% rose {RISE_PCT:.0f}%+ (n={t['n']})",
             f"All scored cards:  mean {a['mean']:+.1f}%, median {a['median']:+.1f}%, "
             f"{a['hit_rate']:.0f}% rose {RISE_PCT:.0f}%+ (n={a['n']})"]
    edge = (t["mean"] or 0) - (a["mean"] or 0)
    lines.append(f"Edge of the top picks: {edge:+.1f} points (noisy until several weeks of days).")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check spec signals against later price moves.")
    parser.add_argument("--horizon", type=int, default=7)
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args(argv)
    db = card_db.open_db(log=lambda m: print(m, file=sys.stderr))
    wl = watchlist.WatchList()
    try:
        print(format_report(run(db, wl, args.horizon, args.top)))
        print()
        print(format_patterns(price_patterns(db, wl, horizon=args.horizon)))
    finally:
        wl.close()
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
