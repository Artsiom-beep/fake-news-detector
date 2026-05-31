# Quality Pack v3 Live Report

- Created: `2026-05-29T15:27:38+00:00`
- Dataset: `quality_pack_v3_live`
- Pipeline: `best_accuracy_v2`
- Total: `17`
- Passed: `17`
- Failed: `0`
- Errors: `0`

## Data Sources
- `bbc_world`: BBC World RSS from https://feeds.bbci.co.uk/news/world/rss.xml status=ok items=1
- `npr_news`: NPR News RSS from https://feeds.npr.org/1001/rss.xml status=ok items=1
- `guardian_world`: The Guardian World RSS from https://www.theguardian.com/world/rss status=ok items=1
- `aljazeera_all`: Al Jazeera RSS from https://www.aljazeera.com/xml/rss/all.xml status=ok items=1
- `cbs_latest`: CBS News latest RSS from https://www.cbsnews.com/latest/rss/main status=ok items=1
- `nbc_news`: NBC News RSS from https://feeds.nbcnews.com/nbcnews/public/news status=ok items=1
- `dw_all`: DW RSS from https://rss.dw.com/rdf/rss-en-all status=ok items=0
- `france24_en`: France24 RSS from https://www.france24.com/en/rss status=ok items=1
- `abc_top`: ABC News top stories RSS from https://abcnews.go.com/abcnews/topstories status=ok items=1
- `sky_world`: Sky News world RSS from https://feeds.skynews.com/feeds/rss/world.xml status=ok items=1
- `ap_top`: AP News top news RSS from https://apnews.com/hub/ap-top-news?output=rss status=html_fallback items=1 error=not well-formed (invalid token): line 3, column 239
- Manual guardrails: BBC listing, Reuters homepage, Medium homepage, YouTube video.
- Manual fact-check seed: PolitiFact explicit-ruling page.
- Manual simple facts: arithmetic and common taste/property checks.

## Summary
- By case type: `{"listing_guardrail": 2, "low_trust_guardrail": 1, "social_guardrail": 1, "factcheck_url": 1, "simple_fact": 2, "trusted_news_article": 10}`
- By source type: `{"major_news": 10, "primary_news": 2, "low_trust": 1, "social": 1, "factcheck_org": 1, "unknown": 2}`
- By credibility label: `{"low": 1, "unknown": 3, "none": 3, "medium": 9, "high": 1}`
- By verdict: `{"uncertain": 14, "fake": 2, "true": 1}`

## Failed / Needs Review
- None.

## Slowest Cases
- `nbc_news_01` runtime=22.904s label=medium verdict=uncertain url=https://www.nbcnews.com/politics/justice-department/judge-halts-trump-anti-weaponization-fund-jan-6-prosecutor-files-suit-rcna347539
- `aljazeera_all_01` runtime=22.901s label=medium verdict=uncertain url=https://www.aljazeera.com/sports/2026/5/29/psg-vs-arsenal-champions-league-final-teams-start-time-lineups-kickoff?traffic_source=rss
- `npr_news_01` runtime=21.674s label=medium verdict=uncertain url=https://www.npr.org/2026/05/29/g-s1-124788/asia-defense-summit-opens-amid-doubts-over-u-s-priorities
- `cbs_latest_01` runtime=21.538s label=medium verdict=uncertain url=https://www.cbsnews.com/news/cd-account-moves-savers-make-before-june-2026-fed-meeting
- `bbc_world_01` runtime=19.58s label=medium verdict=uncertain url=https://www.bbc.com/news/articles/c70vg7glglyo?at_medium=RSS&at_campaign=rss
- `guardian_world_01` runtime=16.375s label=medium verdict=uncertain url=https://www.theguardian.com/world/2026/may/29/who-chief-tedros-adhanom-ghebreyesus-drc-ebola-outbreak-epidemic
- `ap_top_01` runtime=15.5s label=high verdict=uncertain url=https://apnews.com/article/russia-putin-ukraine-war-zelenskyy-0c31bbbf0d06c457c00d046bc7ba99f7
- `sky_world_01` runtime=14.898s label=medium verdict=uncertain url=https://news.sky.com/story/canadian-man-admits-aiding-8204suicide-by-selling-8204deadly-chemicals-online-13549071
- `abc_top_01` runtime=14.701s label=medium verdict=uncertain url=https://abcnews.com/US/judge-temporary-freezes-payments-trump-administrations-anti-weaponization/story?id=133418762
- `france24_en_01` runtime=10.696s label=medium verdict=uncertain url=https://www.france24.com/en/europe/20260529-eu-to-unlock-16-billion-euros-for-hungary-as-magyar-pushes-ahead-with-post-orban-reforms

## Full Rows
See JSON output for evidence, queries, timings and risk flags.
