from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class SourceProfile:
    domain: str
    source_type: str
    trust: float


SOURCE_PROFILES = {
    "reuters.com": SourceProfile("reuters.com", "primary_news", 0.98),
    "apnews.com": SourceProfile("apnews.com", "primary_news", 0.96),
    "afp.com": SourceProfile("afp.com", "primary_news", 0.95),
    "factcheck.afp.com": SourceProfile("factcheck.afp.com", "factcheck_org", 0.95),
    "factcheck.org": SourceProfile("factcheck.org", "factcheck_org", 0.97),
    "politifact.com": SourceProfile("politifact.com", "factcheck_org", 0.95),
    "snopes.com": SourceProfile("snopes.com", "factcheck_org", 0.92),
    "boomlive.in": SourceProfile("boomlive.in", "factcheck_org", 0.90),
    "newschecker.in": SourceProfile("newschecker.in", "factcheck_org", 0.90),
    "altnews.in": SourceProfile("altnews.in", "factcheck_org", 0.90),
    "fullfact.org": SourceProfile("fullfact.org", "factcheck_org", 0.92),
    "leadstories.com": SourceProfile("leadstories.com", "factcheck_org", 0.91),
    "checkyourfact.com": SourceProfile("checkyourfact.com", "factcheck_org", 0.90),
    "africacheck.org": SourceProfile("africacheck.org", "factcheck_org", 0.91),
    "dubawa.org": SourceProfile("dubawa.org", "factcheck_org", 0.88),
    "aap.com.au": SourceProfile("aap.com.au", "factcheck_org", 0.89),
    "misbar.com": SourceProfile("misbar.com", "factcheck_org", 0.87),
    "polygraph.info": SourceProfile("polygraph.info", "factcheck_org", 0.89),
    "healthfeedback.org": SourceProfile("healthfeedback.org", "factcheck_org", 0.92),
    "newsmobile.in": SourceProfile("newsmobile.in", "factcheck_org", 0.84),
    "newsmeter.in": SourceProfile("newsmeter.in", "factcheck_org", 0.83),
    "vishvasnews.com": SourceProfile("vishvasnews.com", "factcheck_org", 0.83),
    "verafiles.org": SourceProfile("verafiles.org", "factcheck_org", 0.85),
    "ghanafact.com": SourceProfile("ghanafact.com", "factcheck_org", 0.84),
    "factcheck.thedispatch.com": SourceProfile("factcheck.thedispatch.com", "factcheck_org", 0.87),
    "factcheckni.org": SourceProfile("factcheckni.org", "factcheck_org", 0.86),
    "covid19facts.ca": SourceProfile("covid19facts.ca", "factcheck_org", 0.84),
    "who.int": SourceProfile("who.int", "institutional", 0.97),
    "cdc.gov": SourceProfile("cdc.gov", "institutional", 0.97),
    "nih.gov": SourceProfile("nih.gov", "institutional", 0.96),
    "nasa.gov": SourceProfile("nasa.gov", "institutional", 0.96),
    "europa.eu": SourceProfile("europa.eu", "institutional", 0.95),
    "un.org": SourceProfile("un.org", "institutional", 0.95),
    "bbc.com": SourceProfile("bbc.com", "major_news", 0.86),
    "bbc.co.uk": SourceProfile("bbc.co.uk", "major_news", 0.86),
    "npr.org": SourceProfile("npr.org", "major_news", 0.84),
    "aljazeera.com": SourceProfile("aljazeera.com", "major_news", 0.80),
    "dw.com": SourceProfile("dw.com", "major_news", 0.82),
    "france24.com": SourceProfile("france24.com", "major_news", 0.80),
    "cbsnews.com": SourceProfile("cbsnews.com", "major_news", 0.78),
    "nbcnews.com": SourceProfile("nbcnews.com", "major_news", 0.78),
    "abcnews.com": SourceProfile("abcnews.com", "major_news", 0.78),
    "abcnews.go.com": SourceProfile("abcnews.go.com", "major_news", 0.78),
    "news.sky.com": SourceProfile("news.sky.com", "major_news", 0.76),
    "nytimes.com": SourceProfile("nytimes.com", "major_news", 0.86),
    "wsj.com": SourceProfile("wsj.com", "major_news", 0.84),
    "cnn.com": SourceProfile("cnn.com", "major_news", 0.78),
    "theguardian.com": SourceProfile("theguardian.com", "major_news", 0.82),
    "washingtonpost.com": SourceProfile("washingtonpost.com", "major_news", 0.82),
    "usatoday.com": SourceProfile("usatoday.com", "major_news", 0.78),
    "abc.net.au": SourceProfile("abc.net.au", "major_news", 0.82),
    "indiatoday.in": SourceProfile("indiatoday.in", "major_news", 0.76),
    "thequint.com": SourceProfile("thequint.com", "major_news", 0.74),
    "fit.thequint.com": SourceProfile("fit.thequint.com", "major_news", 0.74),
    "rappler.com": SourceProfile("rappler.com", "major_news", 0.76),
    "thegazette.com": SourceProfile("thegazette.com", "major_news", 0.75),
    "thelogicalindian.com": SourceProfile("thelogicalindian.com", "major_news", 0.72),
}

SOCIAL_DOMAINS = {
    "x.com",
    "twitter.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "youtube.com",
    "reddit.com",
    "telegram.me",
    "t.me",
}

LOW_TRUST_DOMAINS = {
    "blogspot.com",
    "medium.com",
    "substack.com",
}

TRUSTED_SOURCE_TYPES = {"institutional", "primary_news", "factcheck_org"}


def get_domain(url: str) -> str:
    try:
        domain = urlparse(url).netloc.lower().replace("www.", "")
        return domain.strip()
    except Exception:
        return ""


def classify_source(url: str) -> SourceProfile:
    domain = get_domain(url)
    if not domain:
        return SourceProfile("", "unknown", 0.25)

    if domain in SOURCE_PROFILES:
        return SOURCE_PROFILES[domain]

    for key, profile in SOURCE_PROFILES.items():
        if domain.endswith("." + key):
            return SourceProfile(domain, profile.source_type, profile.trust)

    if domain in SOCIAL_DOMAINS or any(domain.endswith("." + item) for item in SOCIAL_DOMAINS):
        return SourceProfile(domain, "social", 0.08)

    if domain.endswith(".gov"):
        return SourceProfile(domain, "institutional", 0.94)

    if domain.endswith(".edu"):
        return SourceProfile(domain, "institutional", 0.86)

    if domain.endswith(".int"):
        return SourceProfile(domain, "institutional", 0.92)

    if domain in LOW_TRUST_DOMAINS or any(domain.endswith("." + item) for item in LOW_TRUST_DOMAINS):
        return SourceProfile(domain, "low_trust", 0.24)

    return SourceProfile(domain, "unknown", 0.45)


def is_trusted_source_type(source_type: str) -> bool:
    return source_type in TRUSTED_SOURCE_TYPES
