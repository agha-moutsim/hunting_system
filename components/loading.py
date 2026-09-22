"""Loading skeleton components."""

import streamlit as st


def skeleton(lines: int = 3, title: bool = False):
    """Render a text skeleton placeholder."""
    if title:
        st.markdown('<div class="skeleton skeleton-title"></div>', unsafe_allow_html=True)
    for _ in range(lines):
        st.markdown('<div class="skeleton"></div>', unsafe_allow_html=True)


def skeleton_card():
    """Render a card skeleton placeholder."""
    st.markdown('<div class="skeleton skeleton-card"></div>', unsafe_allow_html=True)


def skeleton_chart():
    """Render a chart skeleton placeholder."""
    st.markdown('<div class="skeleton skeleton-chart"></div>', unsafe_allow_html=True)


def skeleton_table(rows: int = 5):
    """Render a table skeleton placeholder."""
    for _ in range(rows):
        st.markdown(
            '<div class="skeleton" style="height:2rem;margin-bottom:0.3rem;"></div>',
            unsafe_allow_html=True,
        )


def loading_spinner(text: str = "Loading..."):
    """Show a loading spinner with text."""
    return st.spinner(text)
