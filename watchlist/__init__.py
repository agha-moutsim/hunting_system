"""Watchlist & Saved Searches module."""

from watchlist.items import (
    add_to_watchlist,
    remove_from_watchlist,
    get_watchlist_items,
    update_watchlist_item,
)
from watchlist.searches import (
    save_search,
    delete_search,
    get_saved_searches,
    update_search,
)
from watchlist.runner import (
    run_search,
    run_all_searches,
    get_new_results,
    mark_result_read,
    get_unread_results_count,
)

__all__ = [
    "add_to_watchlist",
    "remove_from_watchlist",
    "get_watchlist_items",
    "update_watchlist_item",
    "save_search",
    "delete_search",
    "get_saved_searches",
    "update_search",
    "run_search",
    "run_all_searches",
    "get_new_results",
    "mark_result_read",
    "get_unread_results_count",
]
