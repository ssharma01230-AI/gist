# News Source Verification Report

Verified 2026-07-21 against the uploaded `gist_free_news_sources.xlsx` (50 sources, 10 topics).
Machine-readable version with final URLs: [`sources.json`](sources.json).

**Method note:** this session's sandbox blocks outbound HTTP to news domains, so verification
was done through web research (official feed directories, outlet announcements, RSS reader
community reports) rather than live fetches. Findings marked "confirmed" have strong recent
evidence; everything should get one live smoke-test from an unrestricted network before launch.

## Verdict: 44 of 50 usable as listed, 3 need URL fixes, 3 are dead

| Status | Count | Sources |
|---|---|---|
| ✅ Usable as listed | 40 | All BBC/NPR/Guardian/NYT/Al Jazeera feeds, Politico, The Hill, Bloomberg, Forbes, CoinDesk, ESPN, Sky Sports, SI, Variety, THR, Rolling Stone, both WaPo feeds, TechCrunch, The Verge, Space.com, Nature, ARTnews, Hyperallergic, Polygon, Kotaku, Dexerto, Dot Esports, Google News wrapper |
| ⚠️ Usable with caveats | 4 | Alpha Vantage (25 req/day free), MarketAux (~100 req/day, 3 articles/req free), NYT Sports (desk closed 2023, volume uncertain), Google News wrapper (unofficial, redirect links) |
| 🔧 Wrong URL in sheet — corrected | 3 | NASA (portal page → `nasa.gov/rss/dyn/breaking_news.rss`), ScienceDaily (portal page → `sciencedaily.com/rss/all.xml`), IGN (dead FeedBurner → `ign.com/rss/v2/articles/feed`) |
| ❌ Dead | 3 | CNN US + CNN World (`rss.cnn.com` stopped updating years ago), Axios Technology (`api.axios.com` feeds dead since ~2022) |

## Dead sources — replacement options

- **CNN (Breaking + World):** CNN no longer maintains public RSS. Options:
  Google News wrapper (`news.google.com/rss/search?q=site:cnn.com+when:1d`),
  or swap outlets — ABC News (`abcnews.go.com/abcnews/topstories`),
  CBS News (`cbsnews.com/latest/rss/main`), Sky News World
  (`feeds.skynews.com/feeds/rss/world.xml`), DW (`rss.dw.com/rdf/rss-en-world`).
- **Axios Technology:** only a site-wide feed survives (`axios.com/feeds/feed.rss`).
  For tech specifically, Ars Technica (`feeds.arstechnica.com/arstechnica/index`)
  or Wired (`wired.com/feed/rss`) are reliable drop-ins.

## Notes relevant to the "multiple coverage of one story" feature

- Feeds deliver **headline + summary + link + timestamp** (The Verge and Guardian API give
  full text). Clustering the same story across outlets will mostly work off titles/summaries.
- Google News wrapper links redirect through `news.google.com` — resolve them to the
  original URL or cross-source matching will treat them as a different domain.
- Al Jazeera and BBC Entertainment & Arts each appear under two topics — fetch once, tag twice.
- The two finance APIs' free tiers are too small to poll as primary sources; the five RSS-only
  finance feeds carry the topic fine.
