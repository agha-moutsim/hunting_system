"""
Theme toggle — dark/light mode for Streamlit dashboard.

Usage:
    from utils.theme import apply_theme, get_theme
    apply_theme("dark")
"""

import streamlit as st


THEMES = {
    "dark": {
        "bg_color": "#0e1117",
        "secondary_bg": "#262730",
        "text_color": "#fafafa",
        "accent": "#ff4b4b",
        "success": "#00c853",
        "warning": "#ffb300",
        "error": "#ff1744",
    },
    "light": {
        "bg_color": "#ffffff",
        "secondary_bg": "#f0f2f6",
        "text_color": "#31333F",
        "accent": "#ff4b4b",
        "success": "#00c853",
        "warning": "#ffb300",
        "error": "#ff1744",
    },
}


def get_theme() -> str:
    """Get current theme from session state."""
    return st.session_state.get("theme", "dark")


def set_theme(theme: str):
    """Set theme in session state."""
    st.session_state["theme"] = theme


def apply_theme(theme: str = None):
    """Apply theme CSS to Streamlit."""
    if theme is None:
        theme = get_theme()

    colors = THEMES.get(theme, THEMES["dark"])

    css = f"""
    <style>
    /* Main background */
    .stApp {{
        background-color: {colors["bg_color"]};
    }}

    /* Sidebar */
    section[data-testid="stSidebar"] {{
        background-color: {colors["secondary_bg"]};
    }}

    /* Headers */
    h1, h2, h3, h4, h5, h6 {{
        color: {colors["text_color"]};
    }}

    /* Metrics */
    [data-testid="stMetricValue"] {{
        color: {colors["text_color"]};
    }}

    /* Success/Warning/Error */
    .stSuccess {{
        border-color: {colors["success"]};
    }}
    .stWarning {{
        border-color: {colors["warning"]};
    }}
    .stError {{
        border-color: {colors["error"]};
    }}

    /* Buttons */
    .stButton > button {{
        border-color: {colors["accent"]};
        color: {colors["accent"]};
    }}
    .stButton > button:hover {{
        background-color: {colors["accent"]};
        color: white;
    }}

    /* Expander */
    .streamlit-expanderHeader {{
        color: {colors["text_color"]};
    }}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)


def theme_selector():
    """Render theme selector in sidebar."""
    with st.sidebar:
        current = get_theme()
        options = ["dark", "light"]
        idx = options.index(current) if current in options else 0

        new_theme = st.selectbox(
            "Theme",
            options,
            index=idx,
            key="theme_selector",
        )

        if new_theme != current:
            set_theme(new_theme)
            st.rerun()
