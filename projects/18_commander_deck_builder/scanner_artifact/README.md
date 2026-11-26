# Commander Card Scanner

A phone-friendly page (a claude.ai artifact) built on this project's data. Take
a photo of one card, a few loose cards, or a binder page. Claude reads the
names, and every name is checked against the card database before anything is
shown. Each card gets a price for each version, a price trend, and how well it
fits your commander. It's also a bulk-sorting tool: cards worth pulling are
flagged, sorted by place, and exported for selling.

The same rule as the deck builder: **the model reads, code decides.** Claude
only transcribes title bars (and the small set code and number when it can read
them). Code owns every fact: which card a name is, the price, the color
identity, EDHREC numbers, legality.

## Measured scan accuracy

From `eval_scan.py` (`claude-opus-5-5`, 2026-11-26). It uses the same prompt,
image shrinking, zoomed quarters and name matching as the page, on the 5
hand-checked binder pages behind `fixtures/binder_truth.json`:

| Photo | Cards right | Wrong or extra | Typical time |
|---|---|---|---|
| Binder page (9 cards) | **45 / 45** | 0 | ~6 s |
| 4-card cut (2×2) | **20 / 20** | 0 | ~4 s |
| 6-card cut (two rows) | **30 / 30** | 0 | ~6 s |

Every name was an exact match, so nothing needed correcting. The full 15-call run
cost $0.67. With a 3-call pilot and a 3-call re-run of one page, the total was
$0.93 for 21 calls.

**What this does and doesn't show:**
- **Same set and setting.** The pages are from one set (Born of the Gods),
  photographed in decent light. Foils, glare, older frames and cards loose on a
  table aren't covered yet. The 4- and 6-card cuts are still binder pockets.
- **The page's model may differ.** On the page, Claude runs on whatever model
  the viewer's plan serves for its default tier, which may score differently
  from the model named here.
- **Set codes and collector numbers aren't scored.** The answer key has names
  only.
- **A test fix, not a model fix.** The first run counted 5 "extra" cards on one
  page. Looking at the cut showed the third row's title bars really were in the
  picture, so Claude was right. The cut was tightened and that page re-run.

To add a case, put the photo in a folder and add its names (slot order) to
`fixtures/binder_truth.json`, then run:

```bash
python scanner_artifact/eval_scan.py --photos /mnt/c/Users/<you>/Downloads/magic
```

## What it does

- **Scan:** one card, 4 to 9 loose cards, or a binder page. Photos queue up,
  and you can pick up to 30 at once. The screen stays awake while photos are
  read. Large photos also send four zoomed-in quarters, because the platform
  shrinks each image to about 1.2 MP. Each name is matched exactly, corrected
  (closest real card, flagged for you), or shown as unknown, never guessed.
- **Review before adding:** checkboxes, the set symbol, and price for each
  card. A **PULL** or **LEAVE** tag compares the price with your threshold.
- **Price:** the cheapest regular printing, or your exact printing. The set
  code and number read from the photo set it automatically, or you pick it with
  "Mine" in the versions table. Each card also shows a 14-week trend (MTGJSON)
  and the Card Kingdom buylist offer.
- **Fit:** pick a commander, or use Prices only. For the commanders with
  cached EDHREC data, fit uses real inclusion % and synergy. For any other
  commander it uses color identity plus overall rank, and says so.
- **Decks:** paste a list from Moxfield, Archidekt or the deck builder. The
  page shows:
  - off-color and banned cards;
  - deck shape (lands, ramp, draw, removal, wipes) from Scryfall Tagger roles;
  - the lowest bracket it fits (Game Changers, mass land denial, extra turns;
    combos are not checked here);
  - swap ideas and popular missing cards, with a budget filter;
  - copy buttons, and a review from Claude.
- **Organize:** places (binder or box, page, slot), a set-symbol filter, and a
  trade binder (cards in none of your decks).
- **Export:** TCGplayer Mass Entry, Moxfield/Archidekt collection CSV, or a
  sell list with Card Kingdom offers. Exports follow the current filters, with
  an option for PULL cards only.
- **Sync:** for the owner, the pile and decks are saved to their account and
  shown on every device. Anyone else the page is shared with keeps theirs in
  their own browser.

## How it fits together

```
updater.py (daily)          ──► step 10 "scanner export"
export_scanner_data.py      ──► data/scanner_artifact/  (gitignored)
   cards.json        34k cards: identity, type, price, rank, flags, roles, set, rarity
   printings/x.json  every printing with nonfoil/foil/etched prices, one file per letter
   commanders.json   cached EDHREC pages: inclusion % and synergy
   trends.json       weekly prices + Card Kingdom buylist (watchlist.sqlite)
   set_icons.json    Scryfall set symbols (downloaded once, cached)
   oracle.json       rules text, loaded only for "Ask Claude"
index.html                  the page; Claude is reached through the artifact runtime
eval_scan.py                the accuracy test above
```

The artifact can't call Scryfall or EDHREC, and can't show their images. That's
why the facts ship beside the page, and the card images are your own photos
plus "View on Scryfall" links. The update job rebuilds the files every day, but
the page only picks them up when it is republished.

**Privacy:** photos go to Claude on the viewer's own account, and the
thumbnails stay on the device. No API key lives in the page.
