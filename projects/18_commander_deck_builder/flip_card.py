"""Animated 3D flip for two-faced cards (Streamlit custom component v2, inline).

The flip happens entirely in the browser (CSS transform on click), so turning
a card over doesn't rerun the app at all. Images are Scryfall links.
"""

import streamlit as st

_HTML = """
<div class="flip" role="button" tabindex="0" title="Click to flip">
  <div class="inner">
    <img class="face front" alt="" />
    <img class="face back" alt="" />
  </div>
</div>
<button class="flip-btn" type="button">Flip</button>
"""

_CSS = """
:host { display: block; }
.flip {
  perspective: 1200px;
  cursor: pointer;
  aspect-ratio: 488 / 680;
  width: 100%;
}
.inner {
  position: relative;
  width: 100%;
  height: 100%;
  transition: transform 0.6s ease;
  transform-style: preserve-3d;
}
.flip.flipped .inner { transform: rotateY(180deg); }
.face {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  border-radius: 4.5% / 3.2%;
  backface-visibility: hidden;
  -webkit-backface-visibility: hidden;
}
.back { transform: rotateY(180deg); }
.flip:focus-visible { outline: 2px solid var(--st-primary-color); outline-offset: 2px; }
.flip-btn {
  margin-top: 0.4rem;
  width: 100%;
  padding: 0.25rem 0.5rem;
  font: inherit;
  color: var(--st-text-color);
  background: var(--st-secondary-background-color);
  border: 1px solid var(--st-border-color);
  border-radius: var(--st-button-radius, 0.5rem);
  cursor: pointer;
}
.flip-btn:hover { border-color: var(--st-primary-color); color: var(--st-primary-color); }
@media (prefers-reduced-motion: reduce) { .inner { transition: none; } }
"""

_JS = """
export default function (component) {
  const { data, parentElement } = component
  const card = parentElement.querySelector(".flip")
  const front = parentElement.querySelector(".front")
  const back = parentElement.querySelector(".back")
  const button = parentElement.querySelector(".flip-btn")
  if (!card || !front || !back || !button) return

  if (front.getAttribute("src") !== data.front) front.setAttribute("src", data.front)
  if (back.getAttribute("src") !== data.back) back.setAttribute("src", data.back)
  front.alt = data.name + " (front)"
  back.alt = data.name + " (back)"
  card.setAttribute("aria-label", data.name + ": two-faced card, click to flip")

  const toggle = () => {
    card.classList.toggle("flipped")
    card.setAttribute("aria-pressed", card.classList.contains("flipped") ? "true" : "false")
  }
  card.onclick = toggle
  button.onclick = toggle
  card.onkeydown = (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      toggle()
    }
  }
}
"""

_FLIP_CARD = st.components.v2.component("commander_flip_card", html=_HTML, css=_CSS, js=_JS)


def flip_card(name: str, front_url: str, back_url: str, *, key: str):
    """Show a two-faced card that turns over (3D) when clicked."""
    return _FLIP_CARD(data={"name": name, "front": front_url, "back": back_url}, key=key)
