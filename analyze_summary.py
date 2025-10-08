#!/usr/bin/env python3
import os
import sys
import csv
import re
import unicodedata
import argparse
from typing import List, Dict, Tuple, Optional

FIELDNAMES = ["Source", "Title", "Authors", "Year", "Venue", "Citations", "Ranking", "URL"]

# ------------------------------
# Helpers: parsing & normalization
# ------------------------------

def parse_int(val: Optional[str]) -> Tuple[bool, int]:
    """Return (is_valid_int, value_if_valid_else_0)."""
    if val is None:
        return (False, 0)
    s = str(val).strip()
    if s == "":
        return (False, 0)
    try:
        return (True, int(s))
    except Exception:
        return (False, 0)

def is_non_empty(val: Optional[str]) -> bool:
    return bool(str(val or "").strip())

def strip_diacritics(s: str) -> str:
    """Remove accents/diacritics using NFKD decomposition."""
    nkfd = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in nkfd if not unicodedata.combining(ch))

def normalize_title_key(title: str) -> str:
    """
    Normalize title for duplicate detection:
    - lowercase, remove diacritics
    - remove all non-alphanumeric characters
    """
    t = strip_diacritics(title or "").lower()
    return re.sub(r"[^a-z0-9]+", "", t)

def _tokenize_name(raw: str) -> Tuple[str, List[str]]:
    """
    Return (surname, given_tokens) from a raw author string.
    Supports 'Last, First Middle' and 'First Middle Last'.
    Also removes DBLP numeric suffixes like '0001'.
    """
    s = strip_diacritics((raw or "").strip())
    s = re.sub(r"[.\u200b]", "", s)  # remove dots & zero-width artifacts
    s = re.sub(r"\s+", " ", s)
    if not s:
        return ("", [])

    # token pass to drop trailing numeric codes (e.g., '0001', '0010')
    tokens = re.split(r"\s+|,", s)
    tokens = [t for t in tokens if t]
    while tokens and re.fullmatch(r"\d{1,4}", tokens[-1]):
        tokens.pop()
    s = " ".join(tokens)

    if "," in raw:
        parts = [p.strip() for p in s.split(",", 1)]
        last = parts[0]
        given = parts[1] if len(parts) > 1 else ""
        given_tokens = [tok for tok in given.split(" ") if tok]
        surname = last
    else:
        tokens = [tok for tok in s.split(" ") if tok]
        if len(tokens) == 1:
            return (tokens[0].lower(), [])
        surname = tokens[-1]
        given_tokens = tokens[:-1]

    return (surname.lower(), [g.lower() for g in given_tokens if g])

def initials_from_given(tokens: List[str], max_letters: int = 3) -> str:
    """Build compact initials from given-name tokens (e.g., 'joao pedro' -> 'jp')."""
    inits = []
    for tok in tokens:
        if not tok:
            continue
        inits.append(tok[0])
        if len(inits) >= max_letters:
            break
    return "".join(inits)

def normalize_author_signature(one_author: str) -> str:
    """
    Normalize one author into 'surname:initials' signature.
    Examples:
      'John Q. Public' -> 'public:jq'
      'Public, J.'     -> 'public:j'
    """
    surname, given_tokens = _tokenize_name(one_author)
    if not surname:
        return ""
    inits = initials_from_given(given_tokens, max_letters=3)
    return f"{surname}:{inits}"

def normalize_authors_set(authors_str: str) -> frozenset:
    """
    Build a set of normalized author signatures from a raw Authors field.
    Splits by comma and ' and ' (tolerant).
    """
    if not authors_str:
        return frozenset()
    # split on commas first; also split on ' and ' patterns
    parts = []
    for chunk in authors_str.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        # further split on ' and ' if present
        subparts = re.split(r"\band\b", chunk, flags=re.IGNORECASE)
        for sp in subparts:
            sp = sp.strip()
            if sp:
                parts.append(sp)

    sigs = set()
    for p in parts:
        sig = normalize_author_signature(p)
        if sig:
            sigs.add(sig)
    return frozenset(sigs)

VENUE_ALIASES = {
    "ieee trans knowl data eng": "ieee transactions on knowledge and data engineering",
    "ieee tkde": "ieee transactions on knowledge and data engineering",
}

def normalize_venue(v: str) -> str:
    """Lowercase, strip diacritics, collapse to alnum+spaces, apply common aliases."""
    v0 = strip_diacritics((v or "").lower())
    v0 = re.sub(r"[^a-z0-9]+", " ", v0).strip()
    return VENUE_ALIASES.get(v0, v0)

def jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0

# ------------------------------
# IO
# ------------------------------

def load_tsv(path: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rows.append(row)
    return rows

def save_tsv(path: str, rows: List[Dict[str, str]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

def write_yaml(path: str, stats: Dict[str, object]) -> None:
    """Minimal YAML emitter for basic dict/list/str/int content."""
    def dump(d, indent=0):
        lines = []
        sp = "  " * indent
        if isinstance(d, dict):
            for k, v in d.items():
                if isinstance(v, dict):
                    lines.append(f"{sp}{k}:")
                    lines.extend(dump(v, indent+1))
                elif isinstance(v, list):
                    lines.append(f"{sp}{k}:")
                    for item in v:
                        if isinstance(item, (dict, list)):
                            lines.append(f"{sp}-")
                            lines.extend(dump(item, indent+1))
                        else:
                            lines.append(f"{sp}- {item}")
                else:
                    lines.append(f"{sp}{k}: {v}")
        else:
            lines.append(f"{sp}{d}")
        return lines

    txt = "\n".join(dump(stats)) + "\n"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(txt)

# ------------------------------
# Core logic
# ------------------------------

def analyze_and_filter(summary_path: str, out_tsv: str, out_yaml: str) -> None:
    # Load
    rows = load_tsv(summary_path)
    total_survey = len(rows)

    # Count missing fields
    missing_venue = sum(1 for r in rows if not is_non_empty(r.get("Venue")))
    missing_year_field = sum(1 for r in rows if not is_non_empty(r.get("Year")))
    missing_year_parse = sum(1 for r in rows if is_non_empty(r.get("Year")) and not parse_int(r.get("Year"))[0])
    missing_year = missing_year_field + missing_year_parse

    missing_citations_field = sum(1 for r in rows if not is_non_empty(r.get("Citations")))
    missing_citations_parse = sum(1 for r in rows if is_non_empty(r.get("Citations")) and not parse_int(r.get("Citations"))[0])
    zero_citations = sum(1 for r in rows if parse_int(r.get("Citations"))[0] and parse_int(r.get("Citations"))[1] == 0)
    missing_citations = missing_citations_field + missing_citations_parse + zero_citations

    # Filter out rows missing any of: Venue present, Year parseable, Citations parseable > 0
    filtered1: List[Dict[str, str]] = []
    for r in rows:
        venue_ok = is_non_empty(r.get("Venue"))
        year_ok, year_val = parse_int(r.get("Year"))
        cit_ok, cit_val = parse_int(r.get("Citations"))
        cit_ok = cit_ok and cit_val > 0  # 0 counts as missing per current policy
        if venue_ok and year_ok and cit_ok:
            filtered1.append(r)
    after_missing_removed = len(filtered1)

    # --------------------------
    # Advanced deduplication (two stages)
    # --------------------------
    # Stage 1 (strict): same normalized title + same normalized authors set + same year
    groups: Dict[Tuple[str, int, frozenset], List[Dict[str, str]]] = {}
    for r in filtered1:
        year_ok, year_val = parse_int(r.get("Year"))
        if not year_ok:
            continue
        tkey = normalize_title_key(r.get("Title") or "")
        akey = normalize_authors_set(r.get("Authors") or "")
        key = (tkey, year_val, akey)
        groups.setdefault(key, []).append(r)

    dedup_stage1: List[Dict[str, str]] = []
    leftovers: List[Dict[str, str]] = []
    duplicates_removed = 0

    for key, items in groups.items():
        if len(items) == 1:
            dedup_stage1.append(items[0])
        else:
            # keep the one with highest citations (or the one that has citations if others don't)
            best = None
            best_c = -1
            for it in items:
                ok, c = parse_int(it.get("Citations"))
                c = c if ok else -1
                if c > best_c:
                    best = it
                    best_c = c
            dedup_stage1.append(best)
            leftovers.extend([it for it in items if it is not best])
            duplicates_removed += (len(items) - 1)

    # Stage 2 (fuzzy): same normalized title + same normalized venue + year within ±2 + authors Jaccard ≥ 0.6
    pool: List[Dict[str, str]] = dedup_stage1[:]
    consumed = set()
    for i, r in enumerate(leftovers):
        if i in consumed:
            continue
        tkey = normalize_title_key(r.get("Title") or "")
        vkey = normalize_venue(r.get("Venue") or "")
        y_ok, y = parse_int(r.get("Year"))
        akey = normalize_authors_set(r.get("Authors") or "")

        candidate_idx = None
        best_sim = -1.0

        for j, s in enumerate(pool):
            if normalize_title_key(s.get("Title") or "") != tkey:
                continue
            if normalize_venue(s.get("Venue") or "") != vkey:
                continue
            y_ok2, y2 = parse_int(s.get("Year"))
            if not y_ok or not y_ok2 or abs(y - y2) > 2:
                continue
            akey2 = normalize_authors_set(s.get("Authors") or "")
            sim = jaccard(akey, akey2)
            if sim >= 0.6 and sim > best_sim:
                best_sim = sim
                candidate_idx = j

        if candidate_idx is not None:
            # prefer the one with citations / higher citations
            a = pool[candidate_idx]
            ca = parse_int(a.get("Citations"))[1]
            cr = parse_int(r.get("Citations"))[1]
            if cr > ca:
                pool[candidate_idx] = r
            duplicates_removed += 1
            consumed.add(i)
        else:
            pool.append(r)

    deduped: List[Dict[str, str]] = pool
    after_dedup = len(deduped)

    # Keep only Year in [2020, 2025]
    kept_year_range: List[Dict[str, str]] = []
    count_2020_2025 = 0
    for r in deduped:
        ok, y = parse_int(r.get("Year"))
        if ok and 2020 <= y <= 2025:
            kept_year_range.append(r)
            count_2020_2025 += 1
    after_year_filter = len(kept_year_range)

    # Keep only Citations >= 30
    kept_citations: List[Dict[str, str]] = []
    count_citations_ge_30 = 0
    for r in kept_year_range:
        ok, c = parse_int(r.get("Citations"))
        if ok and c >= 30:
            kept_citations.append(r)
            count_citations_ge_30 += 1
    final_count = len(kept_citations)

    # Sort by Citations desc (numeric)
    kept_citations.sort(key=lambda r: parse_int(r.get("Citations"))[1], reverse=True)

    # Save output TSV (must not overwrite summary)
    if os.path.abspath(out_tsv) == os.path.abspath(summary_path):
        raise RuntimeError("Output TSV must not overwrite the summary file.")
    save_tsv(out_tsv, kept_citations)

    # Save YAML stats
    stats = {
        "input": {
            "summary_path": summary_path,
            "total_rows": total_survey,
        },
        "missing_counts": {
            "missing_venue": missing_venue,
            "missing_year_total": missing_year,
            "missing_year_empty": missing_year_field,
            "missing_year_unparseable": missing_year_parse,
            "missing_citations_total": missing_citations,
            "missing_citations_empty": missing_citations_field,
            "missing_citations_unparseable": missing_citations_parse,
            "citations_zero_counted_as_missing": zero_citations,
        },
        "after_missing_removed": after_missing_removed,
        "duplicates": {
            "groups_found": sum(1 for v in groups.values() if len(v) > 1),
            "duplicates_removed": duplicates_removed,
            "criterion": "Stage1: same normalized title + same normalized authors set + same year; "
                         "Stage2: same normalized title + same normalized venue + |year diff|<=2 + authors Jaccard>=0.6; "
                         "prefer record with higher citations",
        },
        "after_dedup": after_dedup,
        "year_filter": {
            "range_inclusive": [2020, 2025],
            "count_in_range": count_2020_2025,
            "after_year_filter": after_year_filter
        },
        "citations_filter": {
            "min_citations": 30,
            "count_ge_min": count_citations_ge_30,
            "final_count": final_count
        },
        "outputs": {
            "filtered_tsv": out_tsv,
            "stats_yaml": out_yaml
        }
    }
    write_yaml(out_yaml, stats)

def guess_outputs(summary_path: str) -> Tuple[str, str]:
    base_dir = os.path.dirname(os.path.abspath(summary_path))
    base_name = os.path.splitext(os.path.basename(summary_path))[0]
    out_tsv = os.path.join(base_dir, base_name + "_cleaned.tsv")
    out_yaml = os.path.join(base_dir, base_name + "_stats.yaml")
    return out_tsv, out_yaml

def main():
    ap = argparse.ArgumentParser(
        description="Analyze and filter a summary TSV of survey papers, producing a cleaned TSV and a YAML with counts."
    )
    ap.add_argument("--summary", required=True, help="Path to the summary TSV (tab-separated).")
    ap.add_argument("--out-tsv", default=None, help="Output TSV path (will NOT overwrite the summary).")
    ap.add_argument("--out-yaml", default=None, help="Output YAML stats path.")
    args = ap.parse_args()

    if not os.path.isfile(args.summary):
        print(f"Error: summary file not found: {args.summary}", file=sys.stderr)
        sys.exit(1)

    out_tsv, out_yaml = guess_outputs(args.summary)
    if args.out_tsv:
        out_tsv = args.out_tsv
    if args.out_yaml:
        out_yaml = args.out_yaml

    analyze_and_filter(args.summary, out_tsv, out_yaml)
    print(f"[OK] Saved filtered TSV -> {out_tsv}")
    print(f"[OK] Saved stats YAML  -> {out_yaml}")

if __name__ == "__main__":
    main()