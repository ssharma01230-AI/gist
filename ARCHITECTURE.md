# Gist — pipeline architecture

Gist turns many news feeds into a swipeable deck of stories, each with an
AI-reworded 2–3 minute read, generated cover art, and — the differentiator —
links to how *multiple outlets* covered the same story.

The backend is an **orchestration layer** driving an eight-stage **data
pipeline**. Every stage is swappable behind an interface, so the system is
adaptable (new source types, new queue/store backends, new models) and robust
(one bad feed or one failed stage never takes the run down).

```
ingest → queue → store → select → create → check → deploy → learn
  ▲        │                          │
  │        └── ArticleSink            └── diffusion art + LLM rewrite
  └── Fetcher (HTTP | fixture)
```

## Orchestration layer

`pipeline/orchestrator.py`

- **`Stage`** — a protocol: `name` + `run(ctx) -> detail dict`.
- **`Orchestrator`** — runs a list of stages in order, hands each a shared
  **`PipelineContext`**, records a `StageResult` per stage, and halts on a
  `StageError`. Adding a stage is: write one class, register it. No orchestrator
  edits.
- **`PipelineContext.blackboard`** — the inter-stage handoff. A stage writes what
  the next reads (ingestion drops the article sink + run summary there).

Every run returns a JSON-able `RunReport` — the raw material the **learn** stage
will later score (which sources delivered, what failed, how fresh).

## The eight stages

| Stage | Role | Status |
|-------|------|--------|
| **ingest** | Pull every source, normalize to `Article`, dedup, emit to the queue | **built** |
| **queue** | Buffer between ingest and processing (in-mem/JSONL now; Redis/SQS later) | interface built (`ArticleSink`) |
| **store** | Durable article store + history | planned |
| **select** | Cluster same-story coverage across outlets (embeddings), pick what's worth publishing | planned |
| **create** | Diffusion cover art per story + LLM rewrite to a 2–3 min read | planned |
| **check** | Quality/safety gates on generated text + image before it ships | planned |
| **deploy** | Publish approved cards to the app/API | planned |
| **learn** | Score outcomes (engagement, source reliability) and feed back into select | planned |

## Ingestion (the built foundation)

`pipeline/ingest.py`, `fetch.py`, `parse.py`, `normalize.py`, `sinks.py`, `state.py`

Data flow for one run:

```
sources.json ─► SourceConfig[]
                    │  (fetchable = rss*; api sources deferred until keys/quota)
                    ▼
              Fetcher.fetch()            ── HTTP (prod) or Fixture (tests/offline)
                    │  FetchResult(body | 304 not-modified | error)
                    ▼
              parse_feed()               ── feedparser → normalized fields
                    │  Article[]  (stable per-source id, UTC dates, plain summary, image)
                    ▼
              ArticleSink.put()          ── dedup via .seen(); InMemory | JSONL now
```

### The key seam: `Fetcher`

`pipeline/fetch.py` is the *only* code that touches the network. Everything above
it is deterministic. That single boundary is what makes the pipeline testable:

- **`HttpFetcher`** — production. Timeouts, retry-with-backoff on 5xx/429/network
  errors, redirect following, and **conditional GET** (`If-None-Match` /
  `If-Modified-Since` → `304` means "unchanged, no body", polite + cheap).
- **`FixtureFetcher`** — tests and offline runs. Serves saved feed bytes by
  source id or URL, and can simulate per-source errors.

The whole ingestion path is proven here against fixtures because this
environment's egress policy blocks live news domains; swap in `HttpFetcher` on a
network with access and nothing else changes.

### The `Article` schema

Canonical shape every downstream stage consumes (`pipeline/models.py`):

`id` · `source_id` · `topic` · `title` · `url` · `summary` · `published_at`
(ISO-8601 UTC) · `fetched_at` · `image_url` · `authors` · `tags`

`id` is `sha256(source_id + guid|link)[:16]` — **stable across runs** (re-fetch
dedups) but **per-source** (the same story from two outlets keeps two ids; pairing
them is the *select* stage's job, via embeddings).

### Robustness contract

- A source failure (timeout, 404, malformed XML) is caught, recorded as a
  `SourceReport(status="error")`, and the run continues.
- Re-running is idempotent: already-seen ids are skipped, in memory and against
  an existing JSONL file.
- `304 Not Modified` is a success with zero new articles, not an error.

## Feed health — testing all 50 sources, continuously

Feeds rot: they go 404, or worse, keep returning HTTP 200 with stale content
after the publisher abandons them (how the original CNN and Axios feeds died).
`pipeline/health.py` + `scripts/health_check.py` catch both. Each source gets a
verdict:

- **pass** — reachable, has items, newest item is fresh (< `--max-age-hours`)
- **warn** — reachable with items but stale, or has no dates to judge
- **fail** — unreachable, errored, or zero items
- **skip** — API sources (need keys/quota), not checked here

The command prints a worst-first table and exits non-zero on any FAIL
(`--strict` also fails on WARN), so it gates CI.

```bash
# Locally, wherever you have internet:
python scripts/health_check.py                       # table + exit code
python scripts/health_check.py --json report.json    # machine-readable too
python scripts/health_check.py --strict              # stale = failure
```

**Automated "each time":** two GitHub Actions workflows (`.github/workflows/`).
GitHub's runners have open internet, so that's where the live 50-source test
runs — the dev sandbox can't reach the feed domains.

- **`feed-health.yml`** — live health check every 6h, on demand, and whenever
  `sources.json`/`pipeline/**` change. A broken or stale feed turns the run red
  and uploads a JSON report artifact. (Scheduled runs only fire once the
  workflow is on the default branch; `workflow_dispatch` and push work on any
  branch.)
- **`tests.yml`** — the hermetic fixture tests on every push/PR.

## Running it

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"

# Unit + integration tests (no network needed)
.venv/bin/python -m pytest -q

# Offline smoke test (bundled fixtures, no network)
.venv/bin/python scripts/run_ingest.py \
    --sources examples/offline_sources.json \
    --fixtures examples/offline_fixtures \
    --out data/articles.jsonl

# Live run (needs network access to the feeds)
.venv/bin/python scripts/run_ingest.py --out data/articles.jsonl --state data/feed_state.json
.venv/bin/python scripts/run_ingest.py --topic science --verbose
```

## What's next

**store** and **select** are the natural next builds: persist articles, then
cluster same-story coverage with embeddings so a card can show "covered by N
outlets." Ingestion already emits the clean, deduped `Article` stream those
stages need.
