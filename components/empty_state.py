"""Empty state placeholders."""

import streamlit as st


def empty_state(icon: str = "📭", title: str = "Nothing here yet", message: str = ""):
    """Show an empty state placeholder.

    Usage:
        empty_state("🔍", "No results", "Try a different search query")
    """
    st.markdown(
        f"""
        <div class="empty-state">
            <div class="icon">{icon}</div>
            <div class="title">{title}</div>
            <div class="message">{message}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
