"""Title-frequency counts for the title helper - Phase F.

The helper answers a narrow, measurable question: for the listings eBay
actually returned for a query, which words and adjacent word pairs appear in
their titles? The answer is a count over the sample in hand. It is not a
keyword tool and it carries no search volume: eBay gives this app no such
figure, so a column for one would be invented.

The module is pure - no I/O, no network, no database - so the counting rules
can be tested without an eBay call. The route in `api/titles.py` supplies the
titles and reports the sample size.

What the tests pin:

  * A unigram count is the number of LISTINGS whose title contains the token,
    not the number of occurrences. "hose hose hose" counts once, and no count
    can exceed `listings_analysed`.
  * A bigram is an adjacent pair in the title as written. Stop words are
    removed from the word table, but they are never skipped over to invent a
    pair: "garden hose for sale" yields "garden hose", never "hose sale".
  * `listings_analysed` is the number of titles handed in, including a title
    that yields no countable word. It is the sample size and is always
    reported.
  * There is no search-volume, popularity, rank or score field. The output
    has exactly two count tables and the sample size.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

__all__ = ["STOPWORDS", "tokenise", "analyse_titles"]

# Words that describe the listing rather than the product, plus the English
# glue that would otherwise top every table. Deliberately conservative:
# "set", "kit", "pack", "bundle" and every model number stay, because those
# change what the buyer receives. No stemming: "hose" and "hoses" are
# different tokens, and merging them would be a guess about intent.
STOPWORDS = frozenset(
    """
    a an the and or of to in on for with by from at as is are was were be
    been being this that these those it its into over under than then so
    such your our my
    new free uk postage post shipping delivery genuine oem original quality
    premium professional pro plus deluxe super ultra high best top great
    perfect ideal special fast next day days discount sale offer offers
    stock available listing auction buy now bn bnib bnip boxed sealed rrp
    """.split()
)

# A token is a run of letters/digits, optionally joined by a hyphen or dot so
# "anti-kink", "3-pack" and "2.5l" survive as one term. Everything else
# separates tokens.
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")


def _raw_tokens(title: str) -> list[str]:
    """Lower-cased tokens, before stop words are removed.

    Bigrams are built from this list, not from the filtered one, so a pair is
    counted only when the two words really sit next to each other in a title.
    """
    if not isinstance(title, str) or not title:
        return []
    return _TOKEN_RE.findall(title.lower())


def _is_countable(token: str) -> bool:
    """A token worth counting: not glue, and not a lone letter.

    Digits are kept even when single ("size 5"), because a size or model
    number can be the most identifying word in a title. A lone letter ("x")
    is not.
    """
    if token in STOPWORDS:
        return False
    return len(token) > 1 or token.isdigit()


def tokenise(title: str) -> list[str]:
    """The countable words in one title, lower-cased and punctuation-free.

    Order is preserved so a caller can inspect what a title actually said.
    """
    return [token for token in _raw_tokens(title) if _is_countable(token)]


def _ranked(counts: Counter[str], field: str) -> list[dict]:
    """Most listings first; ties alphabetical, so output is deterministic."""
    return [
        {field: term, "count": count}
        for term, count in sorted(
            counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]


def analyse_titles(titles: Iterable[str]) -> dict:
    """Count words and adjacent pairs across the titles that were fetched.

    Returns exactly::

        {
            "listings_analysed": <number of titles handed in>,
            "unigrams": [{"word": <token>, "count": <listings>}, ...],
            "bigrams":  [{"phrase": <pair>,  "count": <listings>}, ...],
        }

    The counts are document frequencies over the sample: one listing
    contributes at most once to a term, however many times the term appears
    in its title. A title with no countable word still counts towards
    `listings_analysed`; it is part of the sample and simply contributes
    nothing to the tables.
    """
    if isinstance(titles, str):
        title_list = [titles]
    else:
        title_list = list(titles or [])

    unigrams: Counter[str] = Counter()
    bigrams: Counter[str] = Counter()

    for title in title_list:
        tokens = _raw_tokens(title)
        unigrams.update({token for token in tokens if _is_countable(token)})
        bigrams.update(
            {
                f"{left} {right}"
                for left, right in zip(tokens, tokens[1:])
                if _is_countable(left) and _is_countable(right)
            }
        )

    return {
        "listings_analysed": len(title_list),
        "unigrams": _ranked(unigrams, "word"),
        "bigrams": _ranked(bigrams, "phrase"),
    }
