"""Zero Manufacturing branding header.

Logo asset (assets/zero_logo.png) is Zero Cases' current official site
icon (zerocases.com), used here on an internal tool built for/at that
company -- not a third-party impersonation. Colors match the live
zerocases.com header (dark charcoal bar, light-blue accent), not the
older blue masthead style from the 2006 print catalogs.
"""

import base64
from pathlib import Path

import streamlit as st

LOGO_PATH = Path(__file__).parent / "assets" / "zero_logo.png"


def render_header(subtitle: str) -> None:
    st.logo(str(LOGO_PATH), size="large", link="https://zerocases.com")

    logo_b64 = base64.b64encode(LOGO_PATH.read_bytes()).decode()
    st.html(f"""
    <div style="background:#14171a; padding:14px 22px; border-radius:8px;
                display:flex; align-items:center; gap:16px; margin-bottom:6px;">
      <img src="data:image/png;base64,{logo_b64}" style="height:46px; width:46px;">
      <div>
        <div style="color:#ffffff; font-size:19px; font-weight:700; letter-spacing:0.5px;
                    font-family: Arial, Helvetica, sans-serif;">ZERO MANUFACTURING</div>
        <div style="color:#3ea6e0; font-size:12px; letter-spacing:1.5px; text-transform:uppercase;
                    font-family: Arial, Helvetica, sans-serif;">{subtitle}</div>
      </div>
    </div>
    """)
