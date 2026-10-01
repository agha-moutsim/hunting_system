# P2 — Provenance Foundation & Killing LLM-Invented Facts

**Status:** COMPLETE · **Tests:** 245 passed (baseline 137 → P1 164 → P2 245) · **0 failed**
**Spec:** `CONSTRAINTS.md` C12 (≤7 verified suppliers, never padded) + C13 (4-tier provenance)
**Scope:** Deep Search (full + fast), the analyzer LLM path, and all JSON/CSV exports.

---

## 1. The two dangerous bugs this phase existed to kill

Both were reachable in normal use and both could put a fabricated number in
front of you as if it had been measured.

| #   | Bug                              | Where                                                                           | Blast radius                                                                                                                |
| --- | -------------------------------- | ------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| 1   | **Hallucinated eBay stores**     | `backend/deep_search.py` read `parsed["ebay_top_sellers"]` straight from Ollama | An invented seller **name paired with an invented eBay listing URL**, rendered as a real store with a working-looking link. |
| 2   | **Hallucinated supplier prices** | `backend/deep_search.py` assigned `parsed["suppliers"]` verbatim                | Fed `best_supplier_price` → `calculate_profit` → **verdict**. A made-up £1.01 could produce a **PASS**.                     |

A third one was found _during_ implementation:

| #   | Bug                              | Where                     | Blast radius                                                                                                                   |
| --- | -------------------------------- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| 3   | **Hallucinated "best supplier"** | `backend/pipeline.py:309` | The analyzer LLM's `best_supplier_match.name` was written to the UI with no check against the supplier list it had been shown. |

### Fixes

**Bug 1 — `deep_search.py`**
`parsed.pop("ebay_top_sellers", None)` now runs **unconditionally** after parsing,
_before_ either branch. The field is written only by the real sold-data scraper
(`EbaySoldScraper`, which queries with `conditions:{NEW}`).

**Bug 2 — `deep_search.py`**
`parsed.pop("suppliers", None)` unconditionally. The model is no longer _asked_
for suppliers at all — see §3.

**Bug 3 — `pipeline.py`**
New `_resolve_supplier_choice(name, suppliers)` binds the model's answer back
onto the rows we actually scraped:

```
exact match → case-insensitive → containment (4-char floor)
```

No binding ⇒ `best_supplier_match` is **not written**; a
`best_supplier_match_unresolved` note explains why. The 4-char floor stops a
one-letter answer (`"a"`) from binding to every supplier on the list.

---

## 2. `backend/engine/provenance.py` — the four-tier type system

New module. The labels are **data, not a UI decision**.

```python
class Provenance(str, Enum):
    VERIFIED   = "verified"     # a real API response or a parsed page
    ESTIMATED  = "estimated"    # computed by a stated, transparent method
    UNVERIFIED = "unverified"   # could not confirm — shown, never gates a verdict
    AI_INSIGHT = "ai_insight"   # LLM analysis — barred from factual fields
```

Each carries `.label` (`"Verified"`) and `.badge` (emoji), and is
`str`-valued so it serialises straight to JSON.

### `Fact` — the guarded value-carrying type

```python
Fact(value, provenance, source_url="", method="", source_name="", captured_at=...)
```

`__post_init__` **raises `ProvenanceError`** on two inputs:

1. **`estimated` with no `method`** — an estimate without a stated method is
   indistinguishable from a guess, so we refuse to represent it as one.
2. **`ai_insight` at all** — AI analysis is _not_ a fact. It cannot be a `Fact`;
   it lives outside the type entirely. This makes the C13 bar a construction-time
   error rather than a rendering-time convention.

Other properties:

- `is_usable_for_verdict` → `True` only for `verified` / `estimated`.
  `unverified` and `ai_insight` can never decide PASS/FAIL.
- `to_dict()` → JSON-safe with `value`, `provenance`, `label`, `source_url`,
  `method`, `source_name`, `captured_at`.

Constructors: `verified()`, `estimated()`, `unverified()`.

### `assert_not_ai_fact(payload, field_name)` — the walk

`FACT_FIELDS` declares **30 factual field names** (`price`, `item_cost`, `url`,
`link`, `stock`, `sold_count_30d`, `seller`, `store_name`, `supplier_name`,
`condition`, `brand`, …). The guard walks dicts and lists recursively and raises
if an `ai_insight` provenance tag sits on an object that either:

- was **called** with a factual `field_name`, **or**
- **contains** factual keys of its own

Both shapes are needed: the second catches
`{"suppliers": [{"price": 1, "provenance": "ai_insight"}]}`, where the tag sits
one level inside a list. _(Found by writing the test — see §7.)_

`annotate()` is a lightweight shim for attaching provenance keys to an existing
dict without constructing a `Fact`.

---

## 3. Deep Search no longer asks the model for facts

### System prompt rewritten

**Removed from the schema the model is asked to produce:**

- `ebay_top_sellers` (seller name + URL + price)
- `suppliers` (name + price + URL + type + delivery)

**Added:** `supplier_candidates: [{url, why}]` — candidate **URLs only**, and
only ones that _literally appeared in the supplied data_.

Explicit prohibitions now in the prompt:

```
- NEVER return a supplier name, supplier price, seller name or seller URL.
  Those come from the retrieval layer, not from you.
- `supplier_candidates` ... The system will fetch and verify each one;
  anything it cannot confirm is DISCARDED, so a guessed URL is wasted work.
- Label your own numbers as estimates: ebay_items_sold_month, ebay_price_range
  and ebay_avg_price are ESTIMATES unless the supplied data states them.
```

### `_verify_supplier_candidates(query, candidates)` — verify or drop

Your explicit call: **verify or drop**.

For each candidate URL:

1. `requests.get` (15s) — **fails ⇒ dropped**, never shown
2. `_extract_price()` — JSON-LD `offers.price` / `lowPrice` / `price` first
   (structured, reliable), then the first `£` amount in visible text within
   £0.50–£5000
3. `_extract_title()` — `og:title` → `<title>` → `<h1>`
4. **price ≤ 0 OR no title ⇒ dropped** (we confirm nothing usable)
5. Surviving row is written with `provenance=verified`, `source_url`,
   `source_name`, `supplier_type` (derived from the domain), and
   `match_basis` (the model's stated reason)

Also enforced: de-duplication by URL, malformed entries skipped
(non-dict / non-http), and a **hard cap of 7** (C12 — never pad past what we
could confirm).

If candidates were proposed but none survived, a note is appended:
_"Supplier candidates could not be confirmed against their live pages — dropped
rather than shown unverified (C12)."_

---

## 4. `backend/engine/source_type.py` — shared honest classifier

New leaf module (no project imports ⇒ no circular-import risk) so
`deep_search`, `analysis_pipeline` and the exporters share **one** definition.

```python
supplier_type_from_url(url)  -> wholesaler | dropshipper | retailer | unknown
supplier_type_from_name(name) -> wholesaler | dropshipper | retailer | unknown
supplier_type(name="", url="") -> URL first, else name, else unknown
```

**Never guesses** — an unrecognised host reports `unknown`, not `dropshipper`,
because dropshipper is the usual case.

Replaces **three** separate hardcoded versions:

- `deep_search._supplier_type_from_url` (deleted — delegate to the new module)
- `deep_search` fast path: `retailer if source_name == "Amazon UK" else "dropshipper"`
- `analysis_pipeline`: `"dropship"` written as a constant

> **Bug found while writing this:** `supplier_type_from_url(url) or supplier_type_from_name(name)`
> never reached the name fallback, because `supplier_type_from_url("")` returns the
> _truthy_ string `"unknown"`. Now compares against `UNKNOWN` explicitly.

---

## 5. Fabricated database constants removed

`analysis_pipeline.save_analysis_to_db()` wrote three values as if measured:

```python
"supplier_type": "dropship",   # regardless of where it came from
"confidence":    "medium",     # no matcher had run
"match_score":   0.5,          # no matcher had run
# and the `verified` column silently inherited default=True
```

Now:

```python
"supplier_type": supplier_type(name=s.source, url=s.url),  # derived
"confidence":    None,   # unknown — shown as unknown, not as "medium"
"match_score":   None,   # unknown — engine/match.py (P4) supplies one
"verified":      True,   # set EXPLICITLY: we read this off a live scraper
```

The `verified` default is the more subtle half of this: a column defaulting to
`True` means a row that was never checked still displays as checked.

---

## 6. The analyzer LLM path hardened

### `llm/prompts.py`

- **`SYSTEM_PROMPT`** now forbids fabrication outright:
  _"never invent a supplier name, a seller name, a price, a URL or a stock
  figure… When a value is absent from that data, report it as unknown rather
  than estimating it."_
- **`ANALYSIS_PROMPT`** binds the choice:
  _"the name of ONE supplier copied EXACTLY from the list above, or omit this
  object entirely if none fits"_
- **`build_analysis_prompt`** — removed a silent default of the same shape as P1:

  ```python
  condition=product.get("condition", "New")   # told the model the gate had passed
  condition=product.get("condition") or "unknown"   # honest
  ```

### `pipeline.py`

When the model returns a `best_supplier_match`:

- **Resolved** → written with `provenance=verified` + `source_url` +
  `source_name` (the _identity_ claim is checked), and the model's
  `confidence` / `reasoning` tagged `analysis_provenance=ai_insight` — so a
  confidence of 0.9 can never be read as evidence the supplier was verified.
- **Not resolved** → `best_supplier_match` is omitted entirely; a
  `best_supplier_match_unresolved` note explains the drop.

`SupplierMatch` (in `llm/analyzer.py`) has **no price field**, so this path was
already unable to inject a price — verified during this phase rather than assumed.

---

## 7. Provenance in exports (C13)

### JSON — `export/format.py`

New top-level `provenance` block, uniform shape:

```jsonc
"provenance": {
  "demand":           {"provenance": "verified",   "label": "Verified"},
  "top_eBay_sellers": {"provenance": "unverified", "label": "Unverified"},
  "suppliers":        {"provenance": "verified",   "label": "Verified"},
  "profit_analysis":  {"provenance": "estimated",  "label": "Estimated",
                       "method": "calculate_profit() from engine.profit using PROFIT_CONFIG..."},
  "fields": { "ebay_avg_price": {...}, "suppliers": {...}, ... }
}
```

- `profit_analysis` is always an **estimate**, and C13 requires it to **state
  its method**.
- Every supplier row gains `provenance`, `provenance_label`, `source_url`,
  `source_name`, `match_basis`.
- Every top-seller row gains `provenance` — **`verified` only if it has a URL**,
  else `unverified`.
- `_prov_of()` coerces a missing **or malformed** stamp (e.g. `"banana"`) to
  `unverified`. **A missing stamp never reads as `verified`** — that is the same
  silent-default bug class as P1, and it would defeat the whole feature.

### CSV — `export/csv_export.py`

Single export gains 4 columns: `Demand Provenance`, `Top Sellers Provenance`,
`Suppliers Provenance`, `Profit Provenance`.
Bulk export gains 2: `Demand Provenance`, `Suppliers Provenance`.

---

## 8. Dead code removed

`_llm_price_in_band()` — became unreachable once LLM top-seller figures were
deleted. Removed rather than left as a trap for the next reader.

---

## 9. Tests — 81 new (164 → 245)

New file `tests/test_provenance.py`.

| Class                                 | Covers                                                                                                                                                                                            |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `TestProvenanceEnum`                  | exactly 4 tiers, labels, badges, JSON serialisation                                                                                                                                               |
| `TestFactGuards`                      | estimate w/o method refused · `ai_insight` Fact refused · verdict usability · auto `captured_at`                                                                                                  |
| `TestAiInsightCannotBeAFact`          | 8 factual fields declared · `ai_insight` in a fact field raises (flat **and nested**) · analysis fields allowed · clean payloads pass                                                             |
| `TestLLMIsNotASourceOfSellers`        | the hallucinated store name **and** its URL never reach the result; stamp reads `unverified`                                                                                                      |
| `TestLLMIsNotASourceOfSupplierPrices` | hallucinated supplier dropped · **`best_supplier_price` stays 0.0** · stamp `unverified`                                                                                                          |
| `TestProvenanceStamping`              | analysis fields `ai_insight` · **no `ai_insight` stamp on any factual field** · estimates state a method                                                                                          |
| `TestVerifySupplierCandidates`        | confirmed page → verified row · unreachable dropped · no price dropped · no title dropped · `javascript:` dropped · dupes collapsed · **capped at 7** · malformed skipped · domain classification |
| `TestSystemPromptProhibitsFacts`      | no `ebay_top_sellers`, no `suppliers`, has `supplier_candidates`, has the NEVER-return rule                                                                                                       |
| `TestJsonExportProvenance`            | block present · profit labelled estimate **with method** · supplier rows carry source · **missing stamp → unverified** · garbage stamp coerced                                                    |
| `TestCsvExportProvenance`             | headers · labels in the row · bulk · unstamped → unverified                                                                                                                                       |
| `TestResolveSupplierChoice`           | exact / case-insensitive / compound resolve · **invented name dropped** · empty dropped · **`"a"` cannot match everything**                                                                       |
| `TestAnalyzePromptCannotAssumeNew`    | missing condition → `unknown` not `New` · real condition passed through · system prompt forbids invention · choice bound to list                                                                  |
| `TestAnnotateShim`                    | key attachment, optional fields omitted                                                                                                                                                           |

### Deliberate regression targets

Every one of these asserts against a bug that existed before this phase:

- `assert "TOTALLY_MADE_UP_STORE" not in names`
- `assert offline_deep_search.best_supplier_price == 0.0` ← the PASS-forger
- `assert bare.field_provenance == {} → "unverified"`
- `assert ds._SYSTEM_PROMPT` contains no `"ebay_top_sellers"`

Deep Search tests run **fully offline**: `get_sold_data`, `_web_search`,
`_fetch_page_text`, `_ollama_generate` and `_verify_supplier_candidates` are all
monkeypatched, so the suite makes no network calls.

---

## 10. Files changed

### New

| File                            | Purpose                                                 |
| ------------------------------- | ------------------------------------------------------- |
| `backend/engine/provenance.py`  | `Provenance`, `Fact`, guards, `FACT_FIELDS`, `annotate` |
| `backend/engine/source_type.py` | shared supplier classifier (leaf module)                |
| `tests/test_provenance.py`      | 81 tests                                                |

### Modified

| File                           | Change                                                                                                                                                                                                                                                           |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `backend/deep_search.py`       | prompt rewrite · 2 unconditional `pop()`s · `_verify_supplier_candidates` + `_extract_price` + `_extract_title` · provenance stamping (full + fast) · `field_provenance` + `set_fact_provenance` on `DeepSearchResult` · shared classifier · dead helper removed |
| `backend/pipeline.py`          | new `_resolve_supplier_choice()` · verified/insight split on `best_supplier_match`                                                                                                                                                                               |
| `backend/analysis_pipeline.py` | fabricated DB constants → derived/`None` · explicit `verified`                                                                                                                                                                                                   |
| `backend/llm/prompts.py`       | system-prompt prohibition · choice bound to list · `condition` default `"New"` → `"unknown"`                                                                                                                                                                     |
| `backend/export/format.py`     | `provenance` block · per-row provenance · `_prov_of` coercion                                                                                                                                                                                                    |
| `backend/export/csv_export.py` | 4 (+2 bulk) provenance columns · shared `_prov_of`                                                                                                                                                                                                               |

### Imports added

`deep_search` ← `engine.provenance`, `engine.source_type` · `analysis_pipeline`
← `engine.source_type` · `export/format` + `export/csv_export` ← `engine.provenance`

---

## 11. Notes / follow-ups

- **`SupplierMatch.match_score` and `.confidence` are now `NULL`** in the DB for
  rows saved by `analysis_pipeline`. `engine/match.py` (P4) supplies real values;
  until then they correctly read as unknown.
- The **`supplier_candidates`** path only runs on the **full** Deep Search
  (the LLM path). `deep_search_fast()` never called the LLM, so it was never
  affected — it builds rows only from real scraper responses, each now stamped
  `verified` with its own `source_url`.
- `history` / saved-analysis readers were not modified; they surface whatever
  `provenance` keys are present, and absent keys degrade to "no badge" rather
  than a wrong badge.
- **Nothing committed.** All changes are in the working tree; `git status`
  shows only intended files (the test-run artifact on
  `backend/data/custom_filters.json` was restored after P1).

---

_Phase 3 next: `engine/stores.py` — shared 4-store discovery wired into all 5 features._
