import re
import requests

from _factcheck_eval_adapter import fetch_article_text, run_factcheck_eval_view, set_fast_mode

# Pick 5 recent BBC article URLs from RSS (direct article pages)
feed = 'https://feeds.bbci.co.uk/news/technology/rss.xml'
r = requests.get(feed, timeout=20, headers={'User-Agent': 'Mozilla/5.0'})
links = re.findall(r'<link>(https?://[^<]+)</link>', r.text)
urls = []
for u in links[1:25]:
    u = u.replace('&amp;', '&').split('?')[0]
    if '/articles/' in u and u not in urls:
        urls.append(u)
    if len(urls) >= 5:
        break

set_fast_mode(True)

for i, u in enumerate(urls, 1):
    txt = fetch_article_text(u, timeout=12)
    if not txt:
        print(f"{i}\t{u}\tFETCH_FAIL\t0\t{{}}\t{{}}")
        continue
    out = run_factcheck_eval_view(txt[:7000])
    print(
        f"{i}\t{u}\t{out.get('article_verdict')}\t{out.get('confidence')}\t"
        f"{out.get('claims_summary')}\t{out.get('evidence_summary')}"
    )
