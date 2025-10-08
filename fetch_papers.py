import os
import csv
import argparse
from typing import List, Dict, Any, Optional
from time import perf_counter
from urllib.parse import quote_plus

import requests
from dotenv import load_dotenv
from tqdm import tqdm

import keywords  # your keywords.py module

TOPIC_PHRASES = {
    "collaborative": ["collaborative filtering"],
    "content": ["content-based", "content based"],
    "sequential": ["sequential recommendation", "sequence-aware", "sequence aware"],
    "session": ["session-based", "session based"],
    "graph": ["graph-based", "knowledge graph", "graph neural"],
    "deep": ["deep learning"],
    "knowledge": ["knowledge-aware", "knowledge aware"],
    "context": ["context-aware", "context aware"],
    "contrastive": ["contrastive learning"],
    "multimodal": ["multimodal"],
    "crossdomain": ["cross-domain", "cross domain"],
    "federated": ["federated"],
    "llm": ["large language model", "large language models", "llm"],
}

def _norm(s: str) -> str:
    return (s or "").strip().lower()

def is_survey_paper(title: str, abstract: str, publication_types: list) -> bool:
    t = _norm(title)
    a = _norm(abstract)
    types = [(_norm(x) if isinstance(x, str) else "") for x in (publication_types or [])]
    if "review" in types:
        return True
    if "survey" in t:
        return True
    if "survey" in a:
        return True
    return False

def matches_topic(title: str, abstract: str, topic_key: str, strict_title: bool) -> bool:
    phrases = TOPIC_PHRASES.get(topic_key, [])
    t = _norm(title)
    a = _norm(abstract)
    if strict_title:
        return any(p in t for p in phrases)
    return any((p in t) or (p in a) for p in phrases)


# ------------------------------
# Logging (structured but simple)
# ------------------------------
import logging
logging.basicConfig(
    format='[%(asctime)s] %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.INFO,
)
logger = logging.getLogger("fetch")


FIELDNAMES = ["Source", "Title", "Authors", "Year", "Venue", "Citations", "Ranking", "URL"]


# ------------------------------
# External lookups (DBLP, S2)
# ------------------------------

def search_dblp(keyword: str, max_results: int = 10, timeout: int = 30) -> List[Dict[str, Any]]:
    """Search for publications on DBLP; returns a list of normalized dicts."""
    url = f"https://dblp.org/search/publ/api?q={quote_plus(keyword)}&h={max_results}&format=json"
    try:
        start = perf_counter()
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        elapsed = perf_counter() - start
        hits = len(data.get("result", {}).get("hits", {}).get("hit", []))
        logger.info(f"[DBLP] {hits} hits in {elapsed:.2f}s | kw={keyword}")
    except Exception as e:
        logger.error(f"[DBLP] request error | kw={keyword} | err={e}")
        return []

    results: List[Dict[str, Any]] = []
    for hit in data.get("result", {}).get("hits", {}).get("hit", []):
        info = hit.get("info", {})
        authors_raw = info.get("authors", {}).get("author", [])
        if isinstance(authors_raw, list):
            authors = ", ".join([a["text"] if isinstance(a, dict) else str(a) for a in authors_raw])
        elif isinstance(authors_raw, dict):
            authors = authors_raw.get("text", "")
        else:
            authors = str(authors_raw)

        results.append({
            "Source": "DBLP",
            "Title": info.get("title", ""),
            "Authors": authors,
            "Year": info.get("year", ""),
            "Venue": info.get("venue", ""),
            "URL": info.get("url", ""),
            "Citations": "",
            "Ranking": ""
        })
    return results


def search_semantic_scholar(keyword: str, api_key: Optional[str], topic_key: str,
                            strict_title: bool, max_results: int = 10, timeout: int = 30) -> List[Dict[str, Any]]:
    """Search on Semantic Scholar and FILTER by (is survey) AND (topic match)."""
    if not api_key:
        logger.error("[S2] API key not set; skipping Semantic Scholar")
        return []

    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    headers = {"x-api-key": api_key}
    # add abstract & publicationTypes for filtering
    params = {
        "query": keyword,
        "limit": max_results,
        "fields": "title,abstract,authors,year,venue,citationCount,url,publicationTypes"
    }

    try:
        start = perf_counter()
        resp = requests.get(url, headers=headers, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        elapsed = perf_counter() - start
        raw_hits = len(data.get("data", []))
        logger.info(f"[S2] {raw_hits} raw hits in {elapsed:.2f}s | kw={keyword}")
    except Exception as e:
        logger.error(f"[S2] request error | kw={keyword} | err={e}")
        return []

    filtered: List[Dict[str, Any]] = []
    for paper in data.get("data", []):
        title = paper.get("title", "")
        abstract = paper.get("abstract", "") or ""
        pubtypes = paper.get("publicationTypes", []) or []

        # keep only surveys about the topic
        if not is_survey_paper(title, abstract, pubtypes):
            continue
        if not matches_topic(title, abstract, topic_key, strict_title):
            continue

        filtered.append({
            "Source": "Semantic Scholar",
            "Title": title,
            "Authors": ", ".join([a["name"] for a in paper.get("authors", [])]),
            "Year": paper.get("year", ""),
            "Venue": paper.get("venue", ""),
            "URL": paper.get("url", ""),
            "Citations": paper.get("citationCount", ""),
            "Ranking": ""
        })

    logger.info(f"[S2] {len(filtered)}/{raw_hits} kept after filtering (survey+topic={topic_key}, strict_title={strict_title})")
    return filtered


# ------------------------------
# Save utilities
# ------------------------------

def save_tsv(path: str, rows: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, delimiter="\t")
        w.writeheader()
        w.writerows(rows)
    logger.info(f"[SAVE] {len(rows)} rows -> {path}")


# ------------------------------
# Pipeline (fetch only)
# ------------------------------

def fetch_and_save(keywords_list: List[str],
                   group_name: str,
                   output_root: str,
                   s2_api_key: Optional[str],
                   max_results: int,
                   dedup_scope: str = "group",
                   topic_key: str = "",
                   strict_title: bool = True) -> None:
    """
    Fetch papers from DBLP and Semantic Scholar and save per-keyword TSV + group summary.
    dedup_scope: "group" (default) dedups across the whole run; "keyword" dedups only within keyword.
    """
    output_dir = os.path.join(output_root, group_name)
    os.makedirs(output_dir, exist_ok=True)

    seen_titles = set() if dedup_scope == "group" else None
    all_results: List[Dict[str, Any]] = []

    for kw in keywords_list:
        logger.info(f"[RUN] keyword start | {kw}")
        kw_start = perf_counter()

        dblp = search_dblp(kw, max_results=max_results)
        s2 = search_semantic_scholar(kw, api_key=s2_api_key, topic_key=topic_key, strict_title=strict_title, max_results=max_results)
        combined = dblp + s2

        unique: List[Dict[str, Any]] = []
        local_seen = set()

        for paper in tqdm(combined, desc=f"[{group_name}] {kw}", unit="paper"):
            tnorm = (paper.get("Title") or "").strip().lower()
            if not tnorm:
                continue

            # dedup logic
            if dedup_scope == "group":
                if tnorm in seen_titles:
                    continue
                seen_titles.add(tnorm)
            else:
                if tnorm in local_seen:
                    continue
                local_seen.add(tnorm)

            unique.append(paper)
            all_results.append(paper)

        safe_kw = kw.replace('"', '').replace(" ", "_").replace("/", "_")
        out_file = os.path.join(output_dir, f"{safe_kw}.tsv")
        save_tsv(out_file, unique)

        elapsed = perf_counter() - kw_start
        logger.info(f"[RUN] keyword done in {elapsed:.2f}s | saved={len(unique)} | {out_file}")

    summary_path = os.path.join(output_dir, f"{group_name}_summary.tsv")
    save_tsv(summary_path, all_results)
    logger.info(f"[FINAL] total saved={len(all_results)} | {summary_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch papers from DBLP and Semantic Scholar.")
    parser.add_argument("--group", required=True, help="Group name (used for output folder).")
    parser.add_argument("--set", required=True, choices=[
        "collaborative", "content", "sequential", "session", "graph",
        "deep", "knowledge", "context",
        "contrastive", "multimodal", "crossdomain", "federated", "llm"
    ], help="Which keyword subset to use (from keywords.py).")
    parser.add_argument("--out", default="results", help="Output root directory.")
    parser.add_argument("--max-results", type=int, default=100, help="Max results per source per keyword.")
    parser.add_argument("--dedup-scope", choices=["group", "keyword"], default="group",
                        help="Deduplicate across the whole group run or per keyword.")
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING...).")
    return parser.parse_args()


def select_keywords(which: str) -> List[str]:
    m = {
        "collaborative": keywords.collaborative_keywords,
        "content": keywords.content_based_keywords,
        "sequential": keywords.sequential_keywords,
        "session": keywords.session_based_keywords,
        "graph": keywords.graph_based_keywords,
        "deep": keywords.deep_learning_keywords,
        "knowledge": keywords.knowledge_aware_keywords,
        "context": keywords.context_aware_keywords,
        "contrastive": keywords.contrastive_keywords,
        "multimodal": keywords.multimodal_keywords,
        "crossdomain": keywords.cross_domain_keywords,
        "federated": keywords.federated_keywords,
        "llm": keywords.llm_keywords,
    }
    return m[which]


if __name__ == "__main__":
    load_dotenv()
    args = parse_args()
    logging.getLogger().setLevel(getattr(logging, args.log_level.upper(), logging.INFO))

    s2_api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    kw_list = select_keywords(args.set)

    fetch_and_save(
        keywords_list=kw_list,
        group_name=args.group,
        output_root=args.out,
        s2_api_key=s2_api_key,
        max_results=args.max_results,
        dedup_scope=args.dedup_scope,
        topic_key=args.set,
        strict_title=True
    )