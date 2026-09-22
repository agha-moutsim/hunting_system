"""Sortable table component using st.dataframe (click headers to sort)."""

import streamlit as st
import pandas as pd


def render_sortable_table(data: list[dict], columns: dict = None, height: int = 400):
    """Render a sortable table.

    Args:
        data: List of dicts (rows).
        columns: Optional dict mapping key -> display name.
        height: Table height in px.

    Usage:
        render_sortable_table(sales, {"product_name": "Product", "profit": "Profit £"})
    """
    if not data:
        st.info("No data to display.")
        return

    df = pd.DataFrame(data)

    if columns:
        # Keep only specified columns, rename them
        available = {k: v for k, v in columns.items() if k in df.columns}
        df = df[list(available.keys())].rename(columns=available)

    st.dataframe(
        df,
        use_container_width=True,
        height=height,
        hide_index=True,
    )
