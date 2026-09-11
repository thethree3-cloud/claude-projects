# Screen mockups

Standalone HTML/SVG mockups of the two screens designed so far, built and
iterated as Claude Artifacts before being saved here. Each file is
self-contained (open directly in a browser, no build step) and renders a
phone-frame mockup of the screen at rest.

- **`title_screen.html`** — dusk Hollywood-Boulevard scene: a caricatured
  pagoda-roofed movie palace, the Hollywood sign on the hills, a
  neon-outlined city skyline, crossing searchlights, palm trees, red
  carpet. Dimensional gold "BIG MONEY" + neon-tube "MOVIE" title lockup,
  a movie-ticket-styled "today's category" badge, "Tap to Play" CTA.
  Live version (may have since diverged): https://claude.ai/code/artifact/84c43fa6-b32b-4b50-920a-4c5867a919fc

- **`end_screen.html`** — a red-carpet / step-and-repeat award-wall scene
  (deliberately different composition from the title screen, same
  palette family): light-strung pillars, a small lit theater entrance
  the carpet leads up to, klieg lights, paparazzi camera flashes, a
  velvet-roped carpet with an embedded Walk of Fame star. "YOU GOT IT!"
  header with the player's name in the neon slot the title screen used
  for "MOVIE," a results ticket (guessed title, solve time, guesses,
  hints, today's rank), and a glowing neon "Top Scores Today" CTA.
  Live version (may have since diverged): https://claude.ai/code/artifact/63cd2e00-7270-4f7d-a3b9-1417b23a9c6b

Both are deliberately single-theme (they commit to their scene rather
than adapting to a light/dark host) and reuse the same design tokens
(gold/neon-pink/neon-cyan/cream on a dusk-to-night palette) and Google
Fonts (Bungee, Monoton, Oswald) so they read as one visual system.

## Status

Design only -- not wired into the Kotlin/Compose client (which isn't
built yet). These are references for that build, not final assets: the
illustrations are hand-authored SVG (cheap, scalable, no density-bucket
export headache in Compose), but will likely need re-implementing as
native Compose Canvas/vector drawables rather than embedded as raw SVG.
