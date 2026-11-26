"""How well does the Card Scanner read real photos? A small, paid accuracy test.

It copies what the page does, step by step:
  - the prompt is read out of index.html (so it can't drift from the page)
  - each image is shrunk to about 1.2 megapixels, as the platform does before
    Claude sees it; photos over 1.8 MP also get the 4 overlapping quarters
  - every name Claude returns is matched the page's way: exact, corrected
    (closest real card within a small edit distance), or unknown

Test photos: the 5 binder pages behind fixtures/binder_truth.json (9 cards each,
hand-checked). From each page it also cuts a 2x2 block (4 cards) and the top two
rows (6 cards), a stand-in for photos of a few cards at a time. Those cuts are
still binder pockets, not cards loose on a table.

One difference stays: the page runs on whichever model the viewer's Claude plan
serves for its default tier; this test names MODEL below.

    python scanner_artifact/eval_scan.py --photos /mnt/c/Users/<you>/Downloads/magic
    python scanner_artifact/eval_scan.py --photos DIR --only 4773     # one page
Results: data/scanner_eval/<timestamp>.json plus a printed summary.
"""

import argparse
import base64
import io
import json
import re
import time
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from PIL import Image, ImageOps

HERE = Path(__file__).resolve().parent
P18 = HERE.parent
PAGE = HERE / "index.html"
TRUTH = P18 / "fixtures" / "binder_truth.json"
CARDS = P18 / "data" / "scanner_artifact" / "cards.json"
OUT = P18 / "data" / "scanner_eval"
ENV = P18.parents[1] / ".env"

MODEL = "claude-opus-5-5"
PLATFORM_PIXELS = 1.2e6      # the platform downsizes each image to about this
QUARTERS_FROM = 1.8e6        # the page adds quarters for photos larger than this
PRICE_IN, PRICE_OUT = 4.00 / 1e6, 20.00 / 1e6   # claude-opus-5-5, $ per token


# ---------- the page's prompt, read from the page ----------

def page_prompt(n_images):
    html = PAGE.read_text(encoding="utf-8")
    m = re.search(r'const SCAN_PROMPT = \(n\) => `\$\{n > 1 \? `(.*?)\$\{n\}(.*?)` : "(.*?)"\}\n(.*?)`;', html, re.S)
    if not m:
        raise SystemExit("Couldn't find SCAN_PROMPT in index.html; update eval_scan.py to match the page.")
    multi_a, multi_b, single, rest = m.groups()
    head = f"{multi_a}{n_images}{multi_b}" if n_images > 1 else single
    return head + "\n" + rest


# ---------- images, prepared like the page + platform ----------

def shrink(im, pixels=PLATFORM_PIXELS):
    w, h = im.size
    if w * h <= pixels:
        return im
    k = (pixels / (w * h)) ** 0.5
    return im.resize((max(1, round(w * k)), max(1, round(h * k))), Image.LANCZOS)


def quarters(im):
    """The page's 4 overlapping quarters, each 56% of the width and height."""
    w, h = im.size
    cw, ch = round(w * 0.56), round(h * 0.56)
    return [im.crop((x, y, x + cw, y + ch)) for x, y in ((0, 0), (w - cw, 0), (0, h - ch), (w - cw, h - ch))]


def images_for(photo):
    """[whole photo, quarters...] as the page would send them, each shrunk by the platform."""
    parts = [photo]
    if photo.size[0] * photo.size[1] >= QUARTERS_FROM:
        parts += quarters(photo)
    return [shrink(p) for p in parts]


def b64(im):
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=90)
    return base64.standard_b64encode(buf.getvalue()).decode()


# ---------- name matching, as the page does it ----------

def norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.replace("‘", "'").replace("’", "'").replace("ʼ", "'").replace("`", "'")
    return re.sub(r"\s+", " ", s.lower()).strip()


def lev(a, b, cap):
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        best = i
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
            best = min(best, cur[j])
        if best > cap:
            return cap + 1
        prev = cur
    return prev[-1]


class Matcher:
    def __init__(self, names):
        self.by_key, self.by_first, self.names = {}, {}, names
        for n in names:
            k, front = norm(n), norm(n.split(" // ")[0])
            self.by_key.setdefault(k, n)
            self.by_key.setdefault(front, n)
            self.by_first.setdefault(front[:1], []).append(n)

    def match(self, raw):
        k = norm(raw)
        if not k:
            return None, "unknown"
        hit = self.by_key.get(k) or self.by_key.get(norm(k.split(" // ")[0]))
        if hit:
            return hit, "exact"
        cap = max(2, len(k) // 5)
        best, best_d = None, cap + 1
        for n in self.by_first.get(k[0], []):
            d = min(lev(k, norm(n.split(" // ")[0]), min(cap, best_d)), lev(k, norm(n), min(cap, best_d)))
            if d < best_d:
                best, best_d = n, d
        if best and best_d <= cap:
            return best, "corrected"
        for n in self.names:   # first letter misread: one wider pass
            d = lev(k, norm(n.split(" // ")[0]), min(2, best_d))
            if d < best_d:
                best, best_d = n, d
        return (best, "corrected") if best and best_d <= 2 else (None, "unknown")


# ---------- the test cases ----------

def cases(photos_dir, truth, only=None):
    """(case id, PIL image, expected names). Binder slot order: 1-3 top row, 4-6 middle, 7-9 bottom."""
    out = []
    for name, expected in sorted(truth.items()):
        if only and only not in name:
            continue
        path = Path(photos_dir) / name
        if not path.exists():
            print(f"skip {name}: not found in {photos_dir}")
            continue
        im = ImageOps.exif_transpose(Image.open(path))
        w, h = im.size
        out.append((f"{name} page (9)", im, expected))
        # Cut a little inside the grid lines so the next row's title bar isn't in the picture.
        out.append((f"{name} 2x2 (4)", im.crop((0, 0, round(w * 0.62), round(h * 0.60))), [expected[i] for i in (0, 1, 3, 4)]))
        out.append((f"{name} two rows (6)", im.crop((0, 0, w, round(h * 0.60))), expected[:6]))
    return out


def score(expected, got):
    """Multiset comparison: right, missed, wrong/extra names."""
    e, g = Counter(expected), Counter(got)
    right = sum((e & g).values())
    return {"expected": len(expected), "right": right, "missed": sorted((e - g).elements()), "extra": sorted((g - e).elements())}


def run_case(client, matcher, case_id, im, expected):
    imgs = images_for(im)
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64(x)}} for x in imgs]
    content.append({"type": "text", "text": page_prompt(len(imgs))})
    t0 = time.time()
    resp = client.beta.messages.create(
        model=MODEL, max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        messages=[{"role": "user", "content": content}],
    )
    secs = time.time() - t0
    text = "".join(b.text for b in resp.content if b.type == "text")
    if resp.stop_reason == "refusal":
        return {"case": case_id, "error": "refused", "secs": secs}
    m = re.search(r"\{.*\}", text, re.S)
    try:
        cards = json.loads(m.group(0))["cards"] if m else []
    except (json.JSONDecodeError, KeyError, TypeError):
        cards = []
    matched, how = [], Counter()
    for c in cards:
        name, kind = matcher.match(c.get("name", ""))
        how[kind] += 1
        if name:
            matched.append(name)
    cost = resp.usage.input_tokens * PRICE_IN + resp.usage.output_tokens * PRICE_OUT
    return {"case": case_id, "images": len(imgs), "secs": round(secs, 1), "cost": round(cost, 4),
            "read": [c.get("name") for c in cards], "how": dict(how), **score(expected, matched)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--photos", required=True, help="folder holding the photos named in binder_truth.json")
    ap.add_argument("--only", help="run only photos whose name contains this")
    args = ap.parse_args(argv)
    load_dotenv(ENV)
    client = anthropic.Anthropic()
    matcher = Matcher([r[0] for r in json.loads(CARDS.read_text(encoding="utf-8"))])
    truth = json.loads(TRUTH.read_text(encoding="utf-8"))
    results = []
    for case_id, im, expected in cases(args.photos, truth, args.only):
        r = run_case(client, matcher, case_id, im, expected)
        results.append(r)
        if "error" in r:
            print(f"{case_id:28} ERROR {r['error']}")
            continue
        print(f"{case_id:28} {r['right']}/{r['expected']} right  {r['how']}  {r['secs']}s  ${r['cost']:.3f}"
              + (f"  missed {r['missed']}" if r["missed"] else "") + (f"  extra {r['extra']}" if r["extra"] else ""))
    ok = [r for r in results if "error" not in r]
    by_kind = {}
    for r in ok:
        kind = r["case"].split(" ", 1)[1]
        k = by_kind.setdefault(kind, {"right": 0, "expected": 0, "extra": 0, "secs": []})
        k["right"] += r["right"]; k["expected"] += r["expected"]; k["extra"] += len(r["extra"]); k["secs"].append(r["secs"])
    print("\nSummary")
    for kind, k in by_kind.items():
        print(f"  {kind:16} {k['right']}/{k['expected']} right ({100 * k['right'] / max(1, k['expected']):.0f}%), "
              f"{k['extra']} wrong or extra, median {sorted(k['secs'])[len(k['secs']) // 2]}s per photo")
    print(f"  total cost ${sum(r.get('cost', 0) for r in results):.2f}, {len(results)} calls, model {MODEL}")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"scan_eval_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps({"model": MODEL, "results": results, "summary": by_kind}, indent=1), encoding="utf-8")
    print(f"  saved {path}")


if __name__ == "__main__":
    main()
