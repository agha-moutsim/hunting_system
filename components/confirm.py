"""Delete confirmation dialog."""

import streamlit as st


def confirm_delete(key: str, item_name: str = "this item") -> bool:
    """Show a delete confirmation. Returns True if confirmed.

    Usage:
        if confirm_delete(f"del_{item['id']}", item['name']):
            delete_item(item['id'])
    """
    confirm_key = f"confirm_{key}"

    if st.session_state.get(confirm_key, False):
        # Show confirmation
        st.warning(f"⚠️ Are you sure you want to delete **{item_name}**?")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✓ Yes, Delete", key=f"yes_{key}", type="primary"):
                st.session_state[confirm_key] = False
                return True
        with col2:
            if st.button("✗ Cancel", key=f"no_{key}"):
                st.session_state[confirm_key] = False
                st.rerun()
        return False
    else:
        # Show delete button
        if st.button("🗑️ Delete", key=f"del_{key}"):
            st.session_state[confirm_key] = True
            st.rerun()
        return False
