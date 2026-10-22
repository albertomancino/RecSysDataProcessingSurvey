# Recommender Systems Survey Collection

This repository collects candidate survey papers on recommender systems from
[DBLP](https://dblp.org/) and [Semantic Scholar](https://www.semanticscholar.org/),
then filters and deduplicates the collected summary. It is a retrieval and
screening utility: the generated lists should be reviewed before being treated
as a definitive bibliography.

## Repository contents

- `fetch_papers.py` queries DBLP and Semantic Scholar for one selected keyword
  set, applies the collection-time filters and title-based deduplication, and
  writes TSV files.
- `analyze_summary.py` reads a collection summary TSV, removes records with
  required metadata missing, deduplicates it further, applies fixed year and
  citation filters, and writes a cleaned TSV plus YAML statistics.
- `keywords.py` defines the search-query lists used by `fetch_papers.py`.
- `requirements.txt` lists the Python dependencies used by the collection
  script.

## Requirements and installation

Use Python 3 and install the repository dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

`analyze_summary.py` uses only Python standard-library modules, while
`fetch_papers.py` uses `requests`, `python-dotenv`, and `tqdm`. The
`requirements.txt` file also includes `scholarly`.

## Semantic Scholar API key

`fetch_papers.py` loads environment variables with `load_dotenv()`. Set
`SEMANTIC_SCHOLAR_API_KEY` either in the shell:

```bash
export SEMANTIC_SCHOLAR_API_KEY="your_key_here"
```

or in a `.env` file in the directory from which the script is run:

```dotenv
SEMANTIC_SCHOLAR_API_KEY=your_key_here
```

If the key is missing, the script logs an error for each query and skips
Semantic Scholar; DBLP collection still runs and output files are still
created. DBLP rows have an empty `Citations` field, so they will not survive
the analysis script's required-citations filter unless that field has been
enriched outside this repository.

## Collect papers

Run the collector with a group name and one keyword set:

```bash
python3 fetch_papers.py --group graph-surveys --set graph
```

The accepted command-line options are:

```text
--group GROUP                 Required; output-folder name.
--set SET                     Required; keyword subset.
--out DIRECTORY               Output root (default: results).
--max-results INTEGER         Maximum results per source per keyword (default: 100).
--dedup-scope {group,keyword} Deduplication scope (default: group).
--log-level LEVEL             Python logging level (default: INFO).
```

`--set` accepts exactly these values:

```text
collaborative  content        sequential    session       graph
deep           knowledge      context       contrastive   multimodal
crossdomain    federated      llm
```

For example, a custom destination, result limit, deduplication mode, and log
level can be supplied as follows:

```bash
python3 fetch_papers.py \
  --group llm-surveys \
  --set llm \
  --out results \
  --max-results 50 \
  --dedup-scope group \
  --log-level INFO
```

For every query in the selected set, the collector writes:

```text
<out>/<group>/<query-with-spaces-and-quotes-normalized>.tsv
```

It also writes the concatenated run summary:

```text
<out>/<group>/<group>_summary.tsv
```

With the first example, the summary is
`results/graph-surveys/graph-surveys_summary.tsv`.

Deduplication compares only stripped, lowercased titles. With
`--dedup-scope group` (the default), the first occurrence of a title is kept
across the whole selected set; a later per-keyword TSV can therefore be empty
for titles already saved for an earlier query. With `--dedup-scope keyword`,
deduplication restarts for every query, so the same title can appear in more
than one per-query TSV and in the group summary.

## Analyze a collected summary

Pass the summary produced by the collector to `analyze_summary.py`:

```bash
python3 analyze_summary.py \
  --summary results/graph-surveys/graph-surveys_summary.tsv
```

Unless overridden, this creates files alongside the summary:

```text
results/graph-surveys/graph-surveys_summary_cleaned.tsv
results/graph-surveys/graph-surveys_summary_stats.yaml
```

Use `--out-tsv` and `--out-yaml` to choose different output paths:

```bash
python3 analyze_summary.py \
  --summary results/graph-surveys/graph-surveys_summary.tsv \
  --out-tsv results/graph-surveys/filtered.tsv \
  --out-yaml results/graph-surveys/filter-stats.yaml
```

The output TSV is sorted by citation count in descending numeric order. The
YAML file records input and missing-metadata counts, duplicate statistics,
filter counts, thresholds, and output paths. The script refuses to overwrite
the summary with its TSV output.

The analysis pipeline:

1. Discards rows without a non-empty venue, a parseable integer year, or a
   parseable integer citation count greater than zero. Citation count `0` is
   counted as missing for this policy.
2. Performs strict duplicate grouping on normalized title, normalized author
   set, and year, retaining the highest-citation record in each group.
3. Compares leftovers against retained records using normalized title and
   venue, years within ±2, and author-set Jaccard similarity of at least 0.6;
   it again prefers the higher-citation record when merging.
4. Keeps only inclusive years **2020 through 2025**.
5. Keeps only papers with at least **30 citations**.

## TSV format

Both scripts read or write tab-separated files with this header, in this
order:

```text
Source\tTitle\tAuthors\tYear\tVenue\tCitations\tRanking\tURL
```

`Ranking` is emitted but is not populated by either collector. DBLP records
also intentionally leave `Citations` and `Ranking` empty; Semantic Scholar
provides its `citationCount` for `Citations` when available.

## Collection filters and limitations

- DBLP results are saved as returned by the DBLP publication search. The
  collection step does not apply a survey or topic-content filter to DBLP
  results; the search query itself contains terms such as `"survey"` and the
  relevant topic phrase.
- Semantic Scholar results are retained only when the publication type includes
  `review`, or the title or abstract contains `survey`, **and** the result
  matches the selected topic phrase.
- In the script's existing CLI invocation, `strict_title=True` is always
  passed. Consequently, the Semantic Scholar topic check currently examines
  the **title only**, even though the helper can also inspect abstracts when
  called with `strict_title=False` programmatically.
- Title matching and survey/topic text matching are case-insensitive substring
  checks. They do not establish bibliographic completeness, topical relevance
  beyond the configured phrases, or duplicate identity in all cases.
- Because DBLP citation fields are empty, the analyzer removes DBLP-only rows
  at its first metadata filter. A DBLP row retained by the analyzer would need
  a valid positive integer citation value supplied before analysis.
- Network errors or API errors are logged and produce no results for the
  affected source/query; the run continues with any other available results.
