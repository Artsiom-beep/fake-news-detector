import os
import sys
import json
import importlib.util
import subprocess
import unittest
import zipfile
from datetime import date
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
from PIL.PngImagePlugin import PngInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from factcheck.claims import extract_claims, is_low_specificity_meta_claim
from factcheck.claim_prior import has_uncertainty_markers
from factcheck.config import FACTCHECK_ONLY_DOMAINS, PipelineConfig, RESEARCH_DOMAINS, build_config
from factcheck.decision import decide_claim, finalize_result
from factcheck.domain_parsers import parse_page, parse_text_fallback
from factcheck.evidence import score_evidence_for_claim
from factcheck.ingest import is_likely_article_url
from factcheck.image_analysis import (
    ImageModelSignal,
    OCRLine,
    OCRResult,
    _join_ocr_lines_in_reading_order,
    detect_ai_image,
    run_ai_image_check,
    run_screenshot_factcheck,
)
from factcheck.news_credibility import (
    _article_quality_score,
    _credibility_label,
    _risk_score,
    analyze_news_credibility,
    clean_news_title,
)
from factcheck.retrieval import build_queries
from factcheck.schemas import ClaimCandidate, ClaimDecision, EvidenceItem, FactCheckTrace, RetrievedDocument
from factcheck.service import run_factcheck
from factcheck.source_registry import classify_source
from nli import classify_claim_vs_evidence, set_fast_mode
from src.api_factcheck import app as api_app
from src.desktop_app import (
    APP_IMPORT,
    DEFAULT_AI_IMAGE_MODEL,
    build_local_url,
    enable_default_ai_image_model,
    find_free_port,
    is_frozen,
    resource_root,
)
from src.ui import _render_result, app as ui_app, render_page
from scripts.run_ai_image_detector_eval import DEFAULT_MANIFEST, _load_manifest, _metrics


def _internal_factcheck_config() -> PipelineConfig:
    return PipelineConfig(mode="factcheck_only", fast_mode=False, targeted_domains=list(FACTCHECK_ONLY_DOMAINS))


def _internal_research_config() -> PipelineConfig:
    return PipelineConfig(mode="research", fast_mode=False, targeted_domains=list(RESEARCH_DOMAINS))


def _png_bytes(text_metadata: dict[str, str] | None = None) -> bytes:
    image = Image.new("RGB", (512, 512), "white")
    buffer = BytesIO()
    pnginfo = None
    if text_metadata:
        pnginfo = PngInfo()
        for key, value in text_metadata.items():
            pnginfo.add_text(key, value)
    image.save(buffer, format="PNG", pnginfo=pnginfo)
    return buffer.getvalue()


def _fixed_date_class(year: int, month: int, day: int) -> type[date]:
    class FixedDate(date):
        @classmethod
        def today(cls) -> "FixedDate":
            return cls(year, month, day)

    return FixedDate


def _jpeg_bytes(width: int = 610, height: int = 385) -> bytes:
    image = Image.new("RGB", (width, height), (190, 180, 160))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


class FactCheckCoreTests(unittest.TestCase):
    def test_extract_claims_prefers_factual_sentences(self):
        text = (
            "People feel uncertain about technology. "
            "Reuters reported Google tested search-result changes in the EU under antitrust pressure in 2026."
        )
        claims = extract_claims(text, max_claims=2)
        self.assertTrue(claims)
        self.assertIn("Google", claims[0].normalized_text)
        joined = extract_claims(
            "US policy teams debated localization and sovereignty requirements for data platforms.",
            max_claims=4,
        )
        self.assertTrue(any("sovereignty requirements" in item.normalized_text for item in joined))

    def test_extract_claims_combines_short_fragment_with_next_sentence(self):
        text = (
            "More than 225,000 people dead, 225,000. "
            "The estimates are, if we'd have acted responsibly, there'd be 160,000 fewer dead because of covid-19."
        )
        claims = extract_claims(text, max_claims=3)
        self.assertTrue(any("160,000 fewer dead" in item.normalized_text for item in claims))

    def test_extract_claims_preserves_us_abbreviation_in_short_claims(self):
        claims = extract_claims("Donald Trump is the U.S. president", max_claims=1)
        self.assertTrue(claims)
        self.assertEqual(claims[0].normalized_text, "Donald Trump is the US president")

    def test_extract_claims_accepts_short_declarative_claims(self):
        self.assertEqual(
            extract_claims("Water is red", max_claims=1)[0].normalized_text,
            "Water is red",
        )
        self.assertEqual(
            extract_claims("Grass is purple", max_claims=1)[0].normalized_text,
            "Grass is purple",
        )
        self.assertEqual(extract_claims("Who is president?", max_claims=1), [])

    def test_extract_claims_filters_sentence_initial_fake_entities(self):
        claim = extract_claims("Wearing face masks will stop the spread of covid 19", max_claims=1)[0]
        self.assertNotIn("Wearing", claim.entities)
        claim = extract_claims("Says electric cars are banned in Canada by 2027", max_claims=1)[0]
        self.assertNotIn("Says", claim.entities)

    def test_low_specificity_meta_claim_is_not_checkable(self):
        claim = extract_claims("The claim has no reliable source and cannot be verified yet.", max_claims=1)[0]
        self.assertTrue(is_low_specificity_meta_claim(claim))

    def test_article_url_heuristic(self):
        self.assertTrue(is_likely_article_url("https://example.com/2026/04/08/google-search-results-antitrust-update"))
        self.assertTrue(is_likely_article_url("https://factcheck.afp.com/doc.afp.com.99HR8G4"))
        self.assertFalse(is_likely_article_url("https://example.com/news"))
        self.assertFalse(is_likely_article_url("https://leadstories.com/cgi-bin/mt/mt-search.fcgi?IncludeBlogs=1&archive_type=Index&page=3"))

    def test_source_registry_assigns_types(self):
        self.assertEqual(classify_source("https://www.reuters.com/world/europe/story").source_type, "primary_news")
        self.assertEqual(classify_source("https://apnews.com/article/example").source_type, "primary_news")
        self.assertEqual(classify_source("https://www.bbc.com/news/articles/c4g6nyvl29po").source_type, "major_news")
        self.assertEqual(classify_source("https://www.npr.org/2026/04/26/example").source_type, "major_news")
        self.assertEqual(classify_source("https://www.theguardian.com/world/2026/apr/26/example").source_type, "major_news")
        self.assertEqual(classify_source("https://www.aljazeera.com/news/2026/4/26/example").source_type, "major_news")
        self.assertEqual(classify_source("https://abcnews.com/US/example/story?id=123").source_type, "major_news")
        self.assertEqual(classify_source("https://example.int/report").source_type, "institutional")
        self.assertEqual(classify_source("https://x.com/some-post").source_type, "social")

    def test_news_article_quality_scores_direct_article_over_listing(self):
        article_score, article_flags = _article_quality_score(
            "https://www.bbc.com/news/articles/c4g6nyvl29po",
            {
                "title": "UN agency releases climate report after record heat",
                "published_at": "2026-04-26T10:00:00Z",
                "author": "BBC News",
                "fetch_source": "direct",
            },
            "A factual news article paragraph. " * 35,
        )
        listing_score, listing_flags = _article_quality_score(
            "https://www.bbc.com/news",
            {"title": "", "published_at": "", "author": "", "fetch_source": "direct"},
            "",
        )
        self.assertGreater(article_score, 0.75)
        self.assertNotIn("listing_or_non_article_url", article_flags)
        self.assertLess(listing_score, 0.4)
        self.assertIn("listing_or_non_article_url", listing_flags)

    def test_news_article_quality_uses_inline_publication_date(self):
        article_score, article_flags = _article_quality_score(
            "https://www.bbc.com/sport/football/articles/c8094vem2e2o",
            {
                "title": "Champions League final: PSG join greatest of all time",
                "published_at": "",
                "author": "BBC Sport",
                "fetch_source": "direct",
            },
            (
                "Champions League final: PSG join greatest of all time. "
                "Published 30 May 2026. "
                "Paris St-Germain retained the Champions League after a penalty shootout. "
            )
            * 12,
        )
        self.assertGreaterEqual(article_score, 0.95)
        self.assertNotIn("missing_date", article_flags)

    def test_news_risk_flags_unknown_and_sensational_sources(self):
        risk_score, flags = _risk_score(
            "https://example-unknown-news.test/2026/04/26/story",
            "Shocking secret plot exposed",
            ["missing_date"],
        )
        self.assertGreaterEqual(risk_score, 0.45)
        self.assertIn("unknown_source", flags)
        self.assertIn("sensational_language", flags)

    def test_news_credibility_label_thresholds(self):
        self.assertEqual(_credibility_label(0.72), "high")
        self.assertEqual(_credibility_label(0.50), "medium")
        self.assertEqual(_credibility_label(0.30), "low")
        self.assertEqual(_credibility_label(0.29), "unknown")

    @patch("factcheck.news_credibility.search_web")
    def test_news_credibility_scores_corroboration(self, mock_search):
        article_text = (
            "UN climate agency releases major report after record heat. "
            "The agency said global temperatures remained elevated and urged governments to improve preparedness. "
        ) * 10
        fetched = {
            "text": article_text,
            "title": "UN climate agency releases major report after record heat",
            "url": "https://www.bbc.com/news/articles/c4g6nyvl29po",
            "published_at": "2026-04-26T10:00:00Z",
            "author": "BBC News",
            "fetch_source": "direct",
        }
        mock_search.return_value = [
            {
                "url": "https://www.reuters.com/world/climate-report-record-heat-2026-04-26/",
                "source_url": "https://www.reuters.com/world/climate-report-record-heat-2026-04-26/",
                "title": "UN climate agency releases major report after record heat",
                "snippet": "The UN climate agency released a major report after record heat.",
            },
            {
                "url": "https://apnews.com/article/climate-report-record-heat",
                "source_url": "https://apnews.com/article/climate-report-record-heat",
                "title": "UN climate agency releases report after record heat",
                "snippet": "The agency said global temperatures remained elevated.",
            },
        ]
        payload = analyze_news_credibility(
            article_text,
            fetched["url"],
            fetched,
            build_config(),
            FactCheckTrace(mode="best_accuracy"),
        ).to_public_dict()
        self.assertEqual(payload["verdict"], "uncertain")
        self.assertIn(payload["credibility"]["label"], {"medium", "high"})
        self.assertEqual(payload["credibility"]["corroboration_score"], 0.76)
        self.assertEqual(len(payload["credibility"]["matched_sources"]), 2)

    @patch("factcheck.news_credibility.search_web")
    def test_trusted_news_article_without_corroboration_can_still_be_medium(self, mock_search):
        article_text = (
            "NPR reported on a diplomatic meeting and energy market developments. "
            "The article provides named context, publication metadata, and enough article text for a direct news credibility assessment. "
        ) * 8
        fetched = {
            "text": article_text,
            "title": "Iran reviews U.S. proposal and Rubio to meet Pope Leo",
            "url": "https://www.npr.org/2026/05/07/g-s1-120673/up-first-newsletter-iran-trump-oil-production-pope-leo-marco-rubio-prediction-markets",
            "published_at": "2026-05-07T10:00:00Z",
            "author": "",
            "fetch_source": "direct",
        }
        mock_search.return_value = []
        payload = analyze_news_credibility(
            article_text,
            fetched["url"],
            fetched,
            build_config(),
            FactCheckTrace(mode="best_accuracy"),
        ).to_public_dict()
        self.assertEqual(payload["verdict"], "uncertain")
        self.assertEqual(payload["credibility"]["label"], "medium")
        self.assertEqual(payload["credibility"]["score"], 0.5)
        self.assertIn("trusted_article_source_quality_floor=0.500", payload["credibility"]["reasons"])
        self.assertIn("no_independent_corroboration", payload["credibility"]["risk_flags"])

    @patch("factcheck.news_credibility.search_web")
    def test_strong_major_news_article_can_be_high_without_external_corroboration(self, mock_search):
        article_text = (
            "Champions League final: PSG join greatest of all time with back-to-back wins. "
            "Published 30 May 2026. "
            "Paris St-Germain retained the Champions League after a penalty shootout and matched a rare European achievement. "
        ) * 8
        fetched = {
            "text": article_text,
            "title": "Champions League final: PSG join 'greatest of all time' with back-to-back wins",
            "url": "https://www.bbc.com/sport/football/articles/c8094vem2e2o",
            "published_at": "",
            "author": "BBC Sport",
            "fetch_source": "direct",
        }
        mock_search.return_value = []
        payload = analyze_news_credibility(
            article_text,
            fetched["url"],
            fetched,
            build_config(),
            FactCheckTrace(mode="best_accuracy"),
        ).to_public_dict()
        self.assertEqual(payload["verdict"], "uncertain")
        self.assertEqual(payload["credibility"]["label"], "high")
        self.assertEqual(payload["credibility"]["score"], 0.72)
        self.assertIn("strong_trusted_article_floor=0.720", payload["credibility"]["reasons"])

    @patch("factcheck.news_credibility.search_web")
    def test_institutional_article_without_corroboration_can_still_be_high(self, mock_search):
        article_text = (
            "The Federal Reserve announced a leadership action through an official press release. "
            "The release includes publication metadata, direct agency context, and enough article body text for a source credibility assessment. "
        ) * 8
        fetched = {
            "text": article_text,
            "title": "Federal Reserve Board announces chair pro tempore action",
            "url": "https://www.federalreserve.gov/newsevents/pressreleases/other20260515a.htm",
            "published_at": "2026-05-15T10:00:00Z",
            "author": "",
            "fetch_source": "direct",
        }
        mock_search.return_value = []
        payload = analyze_news_credibility(
            article_text,
            fetched["url"],
            fetched,
            build_config(),
            FactCheckTrace(mode="best_accuracy"),
        ).to_public_dict()
        self.assertEqual(payload["verdict"], "uncertain")
        self.assertEqual(payload["credibility"]["label"], "high")
        self.assertEqual(payload["credibility"]["score"], 0.72)
        self.assertIn("trusted_article_source_quality_floor=0.720", payload["credibility"]["reasons"])
        self.assertIn("no_independent_corroboration", payload["credibility"]["risk_flags"])

    @patch("factcheck.news_credibility.requests.get")
    @patch("factcheck.news_credibility.search_web")
    def test_news_credibility_resolves_google_news_proxy_instead_of_root_source_url(self, mock_search, mock_get):
        article_text = "UN climate agency releases major report after record heat. " * 20
        fetched = {
            "text": article_text,
            "title": "UN climate agency releases major report after record heat | BBC News",
            "url": "https://www.bbc.com/news/articles/c4g6nyvl29po",
            "published_at": "2026-04-26T10:00:00Z",
            "author": "BBC News",
            "fetch_source": "direct",
        }
        mock_search.return_value = [
            {
                "url": "https://news.google.com/rss/articles/CBMiExample",
                "source_url": "https://www.reuters.com",
                "title": "UN climate agency releases major report after record heat - Reuters",
                "snippet": "The UN climate agency released a major report after record heat.",
            }
        ]
        mock_get.return_value = SimpleNamespace(
            url="https://www.reuters.com/world/climate-report-record-heat-2026-04-26/"
        )
        payload = analyze_news_credibility(
            article_text,
            fetched["url"],
            fetched,
            build_config(),
            FactCheckTrace(mode="best_accuracy"),
        ).to_public_dict()
        self.assertEqual(payload["evidence"][0]["domain"], "reuters.com")
        self.assertEqual(
            payload["evidence"][0]["url"],
            "https://www.reuters.com/world/climate-report-record-heat-2026-04-26",
        )
        self.assertNotEqual(payload["evidence"][0]["url"], "https://www.reuters.com")

    def test_news_title_cleanup_removes_source_suffixes_and_boilerplate(self):
        self.assertEqual(clean_news_title("2 min read UN report released | AP News"), "UN report released")
        self.assertEqual(clean_news_title("Climate report released - BBC News"), "Climate report released")
        self.assertEqual(clean_news_title("Militants launch attacks across Mali | Mali"), "Militants launch attacks across Mali")
        self.assertEqual(
            clean_news_title("Iran shifts focus to essentials | US-Israel war on Iran News"),
            "Iran shifts focus to essentials",
        )
        self.assertEqual(
            clean_news_title("Photos: Aftermath of the dinner shooting : The Picture Show : NPR"),
            "Aftermath of the dinner shooting",
        )

    def test_news_title_fallback_from_article_url_slug(self):
        from factcheck.news_credibility import _title_from_url

        self.assertEqual(
            _title_from_url(
                "https://news.sky.com/story/a-lone-wolf-whack-job-what-we-know-so-far-about-the-suspected-gunman-13536655"
            ),
            "a lone wolf whack job what we know so far about the suspected gunman",
        )

    def test_public_entrypoints_do_not_expose_modes(self):
        ui_source = (ROOT / "src" / "ui.py").read_text(encoding="utf-8")
        cli_source = (ROOT / "src" / "predict_factcheck.py").read_text(encoding="utf-8")
        api_source = (ROOT / "src" / "api_factcheck.py").read_text(encoding="utf-8")
        self.assertNotIn('name="mode"', ui_source)
        self.assertNotIn("2+2 true", ui_source)
        self.assertNotIn("Apple false", ui_source)
        self.assertIn(".file-input {{\n      display:none;", ui_source)
        for flag in ("--auto", "--fast", "--news", "--general", "--research", "--accurate"):
            self.assertNotIn(flag, cli_source)
        self.assertNotIn("fast_mode", api_source)
        self.assertNotIn("research:", api_source)

    def test_legacy_ml_inventory_keeps_old_model_out_of_product_entrypoints(self):
        inventory = ROOT / "docs" / "legacy_ml_inventory.md"
        self.assertTrue(inventory.exists())
        inventory_text = inventory.read_text(encoding="utf-8")
        self.assertIn("archive/legacy_multimodal/src/models.py", inventory_text)
        self.assertIn("archive/legacy_multimodal/src/train.py", inventory_text)
        self.assertIn("archive/legacy_multimodal/src/evaluate.py", inventory_text)
        self.assertIn("src/predict.py", inventory_text)
        self.assertIn("default product path", inventory_text)
        self.assertIn("requirements.optional-ai.txt", inventory_text)
        self.assertIn("requirements.legacy-train.txt", inventory_text)

        archived_files = [
            "dataset.py",
            "models.py",
            "train.py",
            "evaluate.py",
            "fetch_news_dataset.py",
            "fetch_text_dataset.py",
        ]
        archive_root = ROOT / "archive" / "legacy_multimodal" / "src"
        self.assertTrue((ROOT / "archive" / "legacy_multimodal" / "README.md").exists())
        for filename in archived_files:
            self.assertFalse((ROOT / "src" / filename).exists(), f"{filename} should be outside src")
            self.assertTrue((archive_root / filename).exists(), f"{filename} should be preserved in the archive")

        product_files = [
            ROOT / "src" / "api_factcheck.py",
            ROOT / "src" / "ui.py",
            ROOT / "src" / "desktop_app.py",
            ROOT / "src" / "predict_factcheck.py",
            ROOT / "apps" / "fake_news_detector_flutter" / "lib" / "api_client.dart",
            ROOT / "apps" / "fake_news_detector_flutter" / "lib" / "main.dart",
        ]
        forbidden = [
            "MultimodalFakeNewsModel",
            "AutoTokenizer.from_pretrained",
            "from .models",
            "from models",
            "import models",
            "from .dataset",
            "from dataset",
            "import dataset",
        ]
        for path in product_files:
            source = path.read_text(encoding="utf-8")
            for needle in forbidden:
                self.assertNotIn(needle, source, f"{path} should not import legacy ML code")

        runtime_requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        locked_runtime_requirements = (ROOT / "requirements.lock.txt").read_text(encoding="utf-8")
        optional_ai_requirements = (ROOT / "requirements.optional-ai.txt").read_text(encoding="utf-8")
        legacy_train_requirements = (ROOT / "requirements.legacy-train.txt").read_text(encoding="utf-8")

        for runtime_text in (runtime_requirements, locked_runtime_requirements):
            self.assertIn("fastapi", runtime_text)
            self.assertIn("pywebview", runtime_text)
            self.assertIn("rapidocr-onnxruntime", runtime_text)
            self.assertIn("Pillow", runtime_text)
            for heavy_package in ("torch", "torchvision", "transformers", "datasets", "pandas", "scikit-learn"):
                self.assertNotIn(heavy_package, runtime_text)

        self.assertIn("torch", optional_ai_requirements)
        self.assertIn("transformers", optional_ai_requirements)
        self.assertNotIn("torchvision", optional_ai_requirements)
        self.assertIn("torchvision", legacy_train_requirements)
        self.assertIn("datasets", legacy_train_requirements)
        self.assertIn("pandas", legacy_train_requirements)

    def test_api_cors_preflight_supports_flutter_web(self):
        client = TestClient(api_app)
        response = client.options(
            "/factcheck",
            headers={
                "origin": "https://fake-news-detector-demo.onrender.com",
                "access-control-request-method": "POST",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "*")
        self.assertIn("POST", response.headers["access-control-allow-methods"])

    def test_legacy_api_predict_delegates_to_canonical_engine(self):
        from src.api import app as legacy_api_app

        api_source = (ROOT / "src" / "api.py").read_text(encoding="utf-8")
        self.assertNotIn("MultimodalFakeNewsModel", api_source)
        self.assertNotIn("AutoTokenizer.from_pretrained", api_source)

        client = TestClient(legacy_api_app)
        response = client.post("/predict", json={"text": "Elephants are insects."})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["verdict"], "fake")
        self.assertEqual(payload["label"], "fake")
        self.assertEqual(payload["compatibility"], "legacy_predict_delegates_to_factcheck")

    def test_legacy_predict_cli_delegates_to_canonical_engine(self):
        predict_source = (ROOT / "src" / "predict.py").read_text(encoding="utf-8")
        self.assertNotIn("MultimodalFakeNewsModel", predict_source)
        self.assertNotIn("AutoTokenizer.from_pretrained", predict_source)
        self.assertNotIn("torch.load", predict_source)

        completed = subprocess.run(
            [sys.executable, "-m", "src.predict", "--text", "Elephants are insects.", "--model-path", "unused.pt"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["verdict"], "fake")
        self.assertEqual(payload["label"], "fake")
        self.assertEqual(payload["compatibility"], "legacy_predict_cli_delegates_to_factcheck")

    def test_eval_scripts_use_canonical_adapter_not_legacy_wrappers(self):
        adapter_path = ROOT / "scripts" / "_factcheck_eval_adapter.py"
        self.assertTrue(adapter_path.exists())
        spec = importlib.util.spec_from_file_location("_factcheck_eval_adapter", adapter_path)
        adapter = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(adapter)
        payload = adapter.run_factcheck_eval_view("Elephants are insects.")
        self.assertEqual(payload["article_verdict"], "fake")
        self.assertIn("claims_summary", payload)
        self.assertIn("evidence_summary", payload)

        script_paths = [
            ROOT / "scripts" / "eval_extended_safe.py",
            ROOT / "scripts" / "eval_decision_calibration.py",
            ROOT / "scripts" / "hardcases_eval.py",
            ROOT / "scripts" / "retest_articles.py",
            ROOT / "scripts" / "run_links_batch_safe.py",
            ROOT / "scripts" / "run_links_batch_stable.py",
        ]
        forbidden = [
            "from fact_pipeline",
            "import fact_pipeline",
            "from src.fact_pipeline",
            "from src.retrieval",
            "fact_pipeline_v3",
        ]
        for path in script_paths:
            source = path.read_text(encoding="utf-8")
            self.assertIn("_factcheck_eval_adapter", source)
            for needle in forbidden:
                self.assertNotIn(needle, source, f"{path} should use canonical eval adapter")

    def test_legacy_root_modules_are_archived_outside_runtime_src(self):
        archived_multimodal = ROOT / "archive" / "legacy_multimodal" / "src"
        archived_factcheck = ROOT / "archive" / "legacy_factcheck_v1" / "src"
        moved_modules = {
            "build_manifest.py": archived_multimodal,
            "callbacks.py": archived_multimodal,
            "prepare_data.py": archived_multimodal,
            "split_data.py": archived_multimodal,
            "utils.py": archived_multimodal,
            "cache.py": archived_factcheck,
            "claims.py": archived_factcheck,
            "eval_factcheck.py": archived_factcheck,
            "fact_pipeline.py": archived_factcheck,
            "fact_pipeline_v3.py": archived_factcheck,
            "retrieval.py": archived_factcheck,
            "seed_evidence.py": archived_factcheck,
            "source_scoring.py": archived_factcheck,
        }
        for module_name, archive_dir in moved_modules.items():
            self.assertFalse((ROOT / "src" / module_name).exists(), f"{module_name} should not be in runtime src")
            self.assertTrue((archive_dir / module_name).exists(), f"{module_name} should be archived")

    def test_desktop_app_builds_local_url_and_selects_free_port(self):
        port = find_free_port(preferred_port=0)
        self.assertIsInstance(port, int)
        self.assertGreater(port, 0)
        self.assertEqual(build_local_url("127.0.0.1", port), f"http://127.0.0.1:{port}/")
        self.assertEqual(build_local_url("127.0.0.1", port, "check"), f"http://127.0.0.1:{port}/check")
        self.assertEqual(APP_IMPORT, "src.ui:app")
        self.assertFalse(is_frozen())
        self.assertEqual(resource_root(), ROOT)
        self.assertEqual(DEFAULT_AI_IMAGE_MODEL, "metadata_only")
        with patch.dict(os.environ, {}, clear=True):
            enable_default_ai_image_model()
            self.assertEqual(os.environ["FACTCHECK_AI_IMAGE_MODEL"], "metadata_only")

    def test_desktop_app_smoke_mode_starts_ui_server(self):
        completed = subprocess.run(
            [sys.executable, "-m", "src.desktop_app", "--smoke", "--port", "0"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Smoke OK:", completed.stdout)

    def test_windows_desktop_build_pipeline_files_exist(self):
        spec = ROOT / "packaging" / "FakeNewsDetector.spec"
        build_script = ROOT / "scripts" / "build_windows.ps1"
        icon_script = ROOT / "scripts" / "make_windows_icon.py"
        icon_svg = ROOT / "assets" / "app_icon.svg"
        self.assertTrue(spec.exists())
        self.assertTrue(build_script.exists())
        self.assertTrue(icon_script.exists())
        self.assertTrue(icon_svg.exists())

        spec_text = spec.read_text(encoding="utf-8")
        build_text = build_script.read_text(encoding="utf-8")
        self.assertIn("desktop_app.py", spec_text)
        self.assertIn('"src.factcheck.service"', spec_text)
        self.assertIn('"src.factcheck.claim_prior"', spec_text)
        self.assertIn("excludes = [", spec_text)
        for package in ("torch", "torchvision", "transformers", "datasets", "pandas", "pyarrow"):
            self.assertIn(f'"{package}"', spec_text)
        self.assertNotIn('safe_collect_submodules("src")', spec_text)
        self.assertNotIn('"huggingface_hub",\n    "tokenizers"', spec_text)
        self.assertIn("FakeNewsDetector.exe", build_text)
        self.assertIn("FakeNewsDetector-Windows-Portable.zip", build_text)
        self.assertIn("Compress-Archive", build_text)
        self.assertIn("--smoke --port 0", build_text)
        self.assertIn("make_windows_icon.py", build_text)
        verify_desktop_script = (ROOT / "scripts" / "verify_desktop_package.ps1").read_text(encoding="utf-8")
        self.assertIn("FakeNewsDetector-Windows-Portable.zip", verify_desktop_script)
        self.assertIn("FakeNewsDetector.exe", verify_desktop_script)
        self.assertIn("--smoke", verify_desktop_script)
        self.assertIn("DESKTOP_PACKAGE_VERIFICATION.md", verify_desktop_script)
        self.assertIn("torch", verify_desktop_script)

    def test_flutter_mobile_project_and_render_files_exist(self):
        flutter_dir = ROOT / "apps" / "fake_news_detector_flutter"
        self.assertTrue((flutter_dir / "pubspec.yaml").exists())
        self.assertTrue((flutter_dir / "lib" / "main.dart").exists())
        self.assertTrue((flutter_dir / "lib" / "api_client.dart").exists())
        self.assertTrue((flutter_dir / "test" / "widget_test.dart").exists())
        self.assertTrue((flutter_dir / "tool" / "create_platforms.ps1").exists())
        self.assertTrue((ROOT / "render.yaml").exists())
        self.assertTrue((ROOT / ".dockerignore").exists())
        self.assertTrue((ROOT / "docs" / "mobile_flutter_render.md").exists())
        self.assertTrue((ROOT / "requirements.api.txt").exists())
        self.assertTrue((ROOT / "scripts" / "build_phone_for_cloud.ps1").exists())
        self.assertTrue((ROOT / "scripts" / "build_phone_for_lan.ps1").exists())
        self.assertTrue((ROOT / "scripts" / "verify_cloud_api.ps1").exists())
        self.assertTrue((ROOT / "scripts" / "verify_render_deploy_config.py").exists())
        self.assertTrue((ROOT / "scripts" / "make_render_backend_bundle.ps1").exists())
        self.assertTrue((ROOT / "scripts" / "smoke_render_backend_bundle.ps1").exists())
        self.assertTrue((ROOT / "scripts" / "cloud_url_policy.ps1").exists())
        self.assertTrue((ROOT / "scripts" / "make_source_bundle.ps1").exists())
        self.assertTrue((ROOT / "scripts" / "verify_submission_bundle.ps1").exists())
        self.assertTrue((ROOT / "scripts" / "check_final_external_prereqs.ps1").exists())
        self.assertTrue((ROOT / "scripts" / "audit_project_goal_completion.ps1").exists())
        self.assertTrue((ROOT / "scripts" / "finalize_cloud_phone_submission.ps1").exists())
        self.assertTrue((ROOT / "scripts" / "smoke_phone_emulator.ps1").exists())
        self.assertTrue((ROOT / "scripts" / "smoke_phone_on_device.ps1").exists())
        self.assertTrue((ROOT / "scripts" / "path_safety.ps1").exists())
        self.assertTrue((ROOT / "scripts" / "write_cloud_deployment_status.ps1").exists())

        pubspec = (flutter_dir / "pubspec.yaml").read_text(encoding="utf-8")
        api_client = (flutter_dir / "lib" / "api_client.dart").read_text(encoding="utf-8")
        main = (flutter_dir / "lib" / "main.dart").read_text(encoding="utf-8")
        widget_test = (flutter_dir / "test" / "widget_test.dart").read_text(encoding="utf-8")
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        render_yaml = (ROOT / "render.yaml").read_text(encoding="utf-8")
        api_requirements = (ROOT / "requirements.api.txt").read_text(encoding="utf-8")
        cloud_build_script = (ROOT / "scripts" / "build_phone_for_cloud.ps1").read_text(encoding="utf-8")
        cloud_policy_script = (ROOT / "scripts" / "cloud_url_policy.ps1").read_text(encoding="utf-8")
        cloud_verify_script = (ROOT / "scripts" / "verify_cloud_api.ps1").read_text(encoding="utf-8")
        lan_build_script = (ROOT / "scripts" / "build_phone_for_lan.ps1").read_text(encoding="utf-8")
        internet_build_script = (flutter_dir / "tool" / "build_internet_apk.ps1").read_text(encoding="utf-8")
        flutter_source_stamp_script = (flutter_dir / "tool" / "flutter_source_stamp.ps1").read_text(encoding="utf-8")
        bundle_script = (ROOT / "scripts" / "make_render_backend_bundle.ps1").read_text(encoding="utf-8")
        render_config_script = (ROOT / "scripts" / "verify_render_deploy_config.py").read_text(encoding="utf-8")
        bundle_smoke_script = (ROOT / "scripts" / "smoke_render_backend_bundle.ps1").read_text(encoding="utf-8")
        tunnel_script = (ROOT / "scripts" / "start_public_api_tunnel.ps1").read_text(encoding="utf-8")
        localtunnel_script = (ROOT / "scripts" / "start_localtunnel_api.ps1").read_text(encoding="utf-8")
        readiness_script = (ROOT / "scripts" / "check_phone_readiness.ps1").read_text(encoding="utf-8")
        apk_verify_script = (ROOT / "scripts" / "verify_phone_apk.ps1").read_text(encoding="utf-8")
        install_page_script = (ROOT / "scripts" / "prepare_phone_install_page.ps1").read_text(encoding="utf-8")
        phone_emulator_smoke_script = (ROOT / "scripts" / "smoke_phone_emulator.ps1").read_text(encoding="utf-8")
        phone_device_smoke_script = (ROOT / "scripts" / "smoke_phone_on_device.ps1").read_text(encoding="utf-8")
        release_gate_script = (ROOT / "scripts" / "run_release_gate.ps1").read_text(encoding="utf-8")
        submission_script = (ROOT / "scripts" / "make_submission_bundle.ps1").read_text(encoding="utf-8")
        submission_verify_script = (ROOT / "scripts" / "verify_submission_bundle.ps1").read_text(encoding="utf-8")
        final_external_preflight_script = (ROOT / "scripts" / "check_final_external_prereqs.ps1").read_text(
            encoding="utf-8"
        )
        goal_audit_script = (ROOT / "scripts" / "audit_project_goal_completion.ps1").read_text(encoding="utf-8")
        source_bundle_script = (ROOT / "scripts" / "make_source_bundle.ps1").read_text(encoding="utf-8")
        path_safety_script = (ROOT / "scripts" / "path_safety.ps1").read_text(encoding="utf-8")
        cloud_status_script = (ROOT / "scripts" / "write_cloud_deployment_status.ps1").read_text(encoding="utf-8")
        cloud_finalize_script = (ROOT / "scripts" / "finalize_cloud_deploy.ps1").read_text(encoding="utf-8")
        final_submission_script = (ROOT / "scripts" / "finalize_cloud_phone_submission.ps1").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
        mobile_render_doc = (ROOT / "docs" / "mobile_flutter_render.md").read_text(encoding="utf-8")
        android_gradle_script = (flutter_dir / "android" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
        main_activity_path = (
            flutter_dir
            / "android"
            / "app"
            / "src"
            / "main"
            / "kotlin"
            / "app"
            / "veritylens"
            / "mobile"
            / "MainActivity.kt"
        )
        legacy_main_activity_path = (
            flutter_dir
            / "android"
            / "app"
            / "src"
            / "main"
            / "kotlin"
            / "com"
            / "fakenewsdetector"
            / "fake_news_detector_flutter"
            / "MainActivity.kt"
        )
        main_activity = main_activity_path.read_text(encoding="utf-8")
        retrieval_script = (ROOT / "src" / "factcheck" / "retrieval.py").read_text(encoding="utf-8")

        self.assertIn("file_picker:", pubspec)
        self.assertIn("String.fromEnvironment", api_client)
        self.assertIn("API_BASE_URL", api_client)
        self.assertIn("NavigationBar", main)
        self.assertIn("validateApiBaseUrl", main)
        self.assertIn("API URL must start with http:// or https://", main)
        self.assertIn("Enter a full API URL", main)
        self.assertIn("API settings reject incomplete backend URLs", widget_test)
        self.assertIn("/factcheck-image", api_client)
        self.assertIn("requirements.api.txt", dockerfile)
        self.assertIn("${PORT:-8001}", dockerfile)
        self.assertIn("archive/", dockerignore)
        self.assertIn("outputs/", dockerignore)
        self.assertIn("apps/", dockerignore)
        self.assertIn("FACTCHECK_CORS_ORIGINS", render_yaml)
        self.assertIn("FACTCHECK_AI_IMAGE_MODEL", render_yaml)
        self.assertIn("metadata_only", render_yaml)
        self.assertIn("rapidocr-onnxruntime", api_requirements)
        self.assertNotIn("pywebview", api_requirements)
        self.assertNotIn("torchvision", api_requirements)
        self.assertIn("/health", cloud_build_script)
        self.assertIn("VerityLens-cloud.apk", cloud_build_script)
        self.assertIn("cloud_url_policy.ps1", cloud_build_script)
        self.assertIn("Assert-PermanentCloudApiUrl", cloud_build_script)
        self.assertIn("Assert-ApkOutputName", cloud_build_script)
        self.assertIn('[string]$Mode = "release"', cloud_build_script)
        self.assertIn("cloud_url_policy.ps1", cloud_verify_script)
        self.assertIn("Assert-PermanentCloudApiUrl", cloud_verify_script)
        self.assertIn("Test-PrivateOrLocalHost", cloud_policy_script)
        self.assertIn("Test-TemporaryTunnelHost", cloud_policy_script)
        self.assertIn("Assert-PermanentCloudApiUrl", cloud_policy_script)
        self.assertIn("trycloudflare.com", cloud_policy_script)
        self.assertIn("loca.lt", cloud_policy_script)
        self.assertIn("localhost", cloud_policy_script)
        self.assertIn("192.168", cloud_policy_script)
        self.assertIn("172.16-31", cloud_policy_script)
        self.assertIn("10.x.x.x", cloud_policy_script)
        self.assertIn("VerityLens-lan.apk", lan_build_script)
        self.assertIn("Get-DefaultLanIp", lan_build_script)
        self.assertIn("phone connected to the same Wi-Fi", lan_build_script)
        self.assertIn('[string]$Mode = "release"', lan_build_script)
        self.assertIn("APK SHA256", lan_build_script)
        self.assertIn("$PowerShell = Get-ChildPowerShellCommand", lan_build_script)
        self.assertNotIn("& powershell", lan_build_script)
        self.assertIn("GetFileNameWithoutExtension($OutputName)", internet_build_script)
        self.assertIn("Assert-ApkOutputName", internet_build_script)
        self.assertIn('$ApkBaseName-api-url.txt', internet_build_script)
        self.assertIn("PHONE_BUILD_STATUS.md", internet_build_script)
        self.assertIn('$ApkBaseName-status.md', internet_build_script)
        self.assertIn("APK SHA256", internet_build_script)
        self.assertIn("flutter_source_stamp.ps1", internet_build_script)
        self.assertIn("Flutter source SHA256", internet_build_script)
        self.assertIn('$ApkBaseName-flutter-source-stamp.json', internet_build_script)
        self.assertIn("SortedSet[string]", flutter_source_stamp_script)
        self.assertIn("StringComparer]::Ordinal", flutter_source_stamp_script)
        self.assertNotIn("Sort-Object -Unique", flutter_source_stamp_script)
        self.assertIn("verity-lens-render-backend.zip", bundle_script)
        self.assertIn("requirements.api.txt", bundle_script)
        self.assertIn(".dockerignore", bundle_script)
        self.assertIn("path_safety.ps1", bundle_script)
        self.assertIn("Remove-PathInsideProject", bundle_script)
        self.assertIn("__pycache__", bundle_script)
        self.assertIn("src\\api_factcheck.py", bundle_script)
        self.assertIn("Render bundle zip is missing required file", bundle_script)
        self.assertIn("render_deploy_config_latest.json", render_config_script)
        self.assertIn("yaml.safe_load", render_config_script)
        self.assertIn("healthCheckPath", render_config_script)
        self.assertIn("requirements.api.txt excludes desktop/training packages", render_config_script)
        self.assertIn("Render deploy config verification", release_gate_script)
        self.assertIn("render_deploy_config", release_gate_script)
        self.assertIn("ExtractToDirectory", bundle_smoke_script)
        self.assertIn("path_safety.ps1", bundle_smoke_script)
        self.assertIn("FreshVenv", bundle_smoke_script)
        self.assertIn("requirements.api.txt", bundle_smoke_script)
        self.assertIn("pip install", bundle_smoke_script)
        self.assertIn("src.api_factcheck:app", bundle_smoke_script)
        self.assertIn("/health", bundle_smoke_script)
        self.assertIn("/ready", bundle_smoke_script)
        self.assertIn("/factcheck", bundle_smoke_script)
        self.assertIn("RENDER_BUNDLE_SMOKE.md", bundle_smoke_script)
        self.assertIn("Wait-PublicApi", tunnel_script)
        self.assertIn("VerifyTimeoutSeconds", tunnel_script)
        self.assertIn("KeepProcessesOnFailure", tunnel_script)
        self.assertIn("failed_public_verification", tunnel_script)
        self.assertIn("active_verified", tunnel_script)
        self.assertIn("Last error", tunnel_script)
        self.assertIn("PHONE_BUILD_STATUS.md", tunnel_script)
        self.assertIn("Phone APK build failed", tunnel_script)
        self.assertIn("$PowerShell = Get-ChildPowerShellCommand", tunnel_script)
        self.assertNotIn("& powershell", tunnel_script)
        self.assertIn("Flutter source SHA256", tunnel_script)
        self.assertIn("npx.cmd", localtunnel_script)
        self.assertIn("localtunnel", localtunnel_script)
        self.assertIn("active_verified", localtunnel_script)
        self.assertIn("Assert-ApkOutputName", localtunnel_script)
        self.assertIn("VerityLens-internet.apk", localtunnel_script)
        self.assertIn("ApkMode", localtunnel_script)
        self.assertIn("release", localtunnel_script)
        self.assertIn("$PowerShell = Get-ChildPowerShellCommand", localtunnel_script)
        self.assertNotIn("& powershell", localtunnel_script)
        self.assertIn("Flutter source SHA256", localtunnel_script)
        self.assertIn("PHONE_READINESS.md", readiness_script)
        self.assertIn("cloud_url_policy.ps1", readiness_script)
        self.assertIn("Assert-PermanentCloudApiUrl", readiness_script)
        self.assertIn("phone_permanent_cloud", readiness_script)
        self.assertIn("phone_temporary_tunnel", readiness_script)
        self.assertIn("verified", readiness_script)
        self.assertIn("last_checked_at", readiness_script)
        self.assertIn("active_probe_failed", readiness_script)
        self.assertIn("RetryDelaySeconds", readiness_script)
        self.assertIn("Test-FactcheckProbe", readiness_script)
        self.assertIn("is_temporary_tunnel", readiness_script)
        self.assertIn("/ready", readiness_script)
        self.assertIn("RequireCloud", readiness_script)
        self.assertIn("Render backend bundle", readiness_script)
        self.assertIn("PHONE_INSTALL_PAGE.json", readiness_script)
        self.assertIn("phone_install_download", readiness_script)
        self.assertIn("PHONE_APK_VERIFICATION.json", readiness_script)
        self.assertIn("internet_apk_verification", readiness_script)
        self.assertIn("Internet APK Verification", readiness_script)
        self.assertIn("Matches quick tunnel URL", readiness_script)
        self.assertIn("PHONE_LAN_APK_VERIFICATION.json", readiness_script)
        self.assertIn("lan_apk_verification", readiness_script)
        self.assertIn("LAN APK Verification", readiness_script)
        self.assertIn("PHONE_CLOUD_APK_VERIFICATION.json", readiness_script)
        self.assertIn("Read-ApkVerification", readiness_script)
        self.assertIn("is_release_mode", readiness_script)
        self.assertIn("$ApkVerification.is_release_mode", readiness_script)
        self.assertIn("$LanApkVerification.is_release_mode", readiness_script)
        self.assertIn("$CloudApkVerification.is_release_mode", readiness_script)
        self.assertIn("embedded_api_url_found", readiness_script)
        self.assertIn("Matches requested cloud URL", readiness_script)
        self.assertIn("Download content length", readiness_script)
        self.assertIn("Invoke-BasicHttpRequest", readiness_script)
        self.assertIn("System.Net.HttpWebRequest", readiness_script)
        self.assertIn("Method HEAD", readiness_script)
        self.assertIn("PHONE_APK_VERIFICATION.md", apk_verify_script)
        self.assertIn("Get-FileHash", apk_verify_script)
        self.assertIn("SHA256", apk_verify_script)
        self.assertIn("ExpectedMode", apk_verify_script)
        self.assertIn("flutter_source_stamp.ps1", apk_verify_script)
        self.assertIn("matches_current_source", apk_verify_script)
        self.assertIn("matches_flutter_source_stamp", apk_verify_script)
        self.assertIn("cloud_url_policy.ps1", apk_verify_script)
        self.assertIn("Assert-PermanentCloudApiUrl", apk_verify_script)
        self.assertIn("AllowTemporaryTunnelApiFailure", apk_verify_script)
        self.assertIn("temporary_tunnel_api_failure_allowed", apk_verify_script)
        self.assertIn("binary_evidence_ok", apk_verify_script)
        self.assertIn("/factcheck", apk_verify_script)
        self.assertIn("API probe attempts", apk_verify_script)
        self.assertIn("RetryDelaySeconds", apk_verify_script)
        self.assertIn("GetFileNameWithoutExtension($ResolvedApk)", apk_verify_script)
        self.assertIn('$ApkBaseName-api-url.txt', apk_verify_script)
        self.assertIn("Find-ApkApiUrlMatches", apk_verify_script)
        self.assertIn("libapp.so", apk_verify_script)
        self.assertIn("embedded_api_url", apk_verify_script)
        self.assertIn("APK contains expected API URL", apk_verify_script)
        self.assertIn("PHONE_INSTALL_PAGE.md", install_page_script)
        self.assertIn("index.html", install_page_script)
        self.assertIn("http.server", install_page_script)
        self.assertIn("VerityLens-internet.apk", install_page_script)
        self.assertIn("VerityLens-cloud.apk", install_page_script)
        self.assertIn("PHONE_CLOUD_APK_VERIFICATION.json", install_page_script)
        self.assertIn("VerityLens-cloud-api-url.txt", install_page_script)
        self.assertIn("Cloud APK available", install_page_script)
        self.assertIn("Cloud APK download ready", install_page_script)
        self.assertIn("$CloudApkDownloadReady", install_page_script)
        self.assertIn("$CloudVerificationSourceFresh", install_page_script)
        self.assertIn("Download Permanent Cloud APK", install_page_script)
        self.assertIn("APK SHA256", install_page_script)
        self.assertIn("adb", phone_device_smoke_script)
        self.assertIn("PHONE_DEVICE_SMOKE.md", phone_device_smoke_script)
        self.assertIn("app.veritylens.mobile", phone_device_smoke_script)
        self.assertIn("am", phone_device_smoke_script)
        self.assertIn("dumpsys", phone_device_smoke_script)
        self.assertIn("Limit-Text", phone_device_smoke_script)
        self.assertIn("RequireDevice", phone_device_smoke_script)
        self.assertIn("RequirePhysicalDevice", phone_device_smoke_script)
        self.assertIn("ProcessStartInfo", phone_device_smoke_script)
        self.assertIn("RedirectStandardOutput", phone_device_smoke_script)
        self.assertIn("adb timed out", phone_device_smoke_script)
        self.assertIn("adb_not_accessible", phone_device_smoke_script)
        self.assertIn("devices_exit_code", phone_device_smoke_script)
        self.assertIn("ADB executable accessible", phone_device_smoke_script)
        self.assertIn("180000", phone_device_smoke_script)
        self.assertIn("selected_device_is_emulator", phone_device_smoke_script)
        self.assertIn("device_identity", phone_device_smoke_script)
        self.assertIn("ro.product.manufacturer", phone_device_smoke_script)
        self.assertIn("ro.product.model", phone_device_smoke_script)
        self.assertIn("ro.hardware", phone_device_smoke_script)
        self.assertIn("Device identity recorded", phone_device_smoke_script)
        self.assertIn("ro.kernel.qemu", phone_device_smoke_script)
        self.assertIn("no_authorized_physical_android_device", phone_device_smoke_script)
        self.assertIn("PHONE_DEVICE_SCREENSHOT.png", phone_device_smoke_script)
        self.assertIn("Invoke-AdbBinaryToFile", phone_device_smoke_script)
        self.assertIn("Get-PngFileInfo", phone_device_smoke_script)
        self.assertIn("png_signature_ok", phone_device_smoke_script)
        self.assertIn("valid_png", phone_device_smoke_script)
        self.assertIn("screencap", phone_device_smoke_script)
        self.assertIn("Screenshot captured", phone_device_smoke_script)
        self.assertIn("Screenshot valid PNG", phone_device_smoke_script)
        self.assertIn("emulator", phone_emulator_smoke_script)
        self.assertIn("PHONE_EMULATOR_SMOKE.md", phone_emulator_smoke_script)
        self.assertIn("PHONE_EMULATOR_SMOKE.json", phone_emulator_smoke_script)
        self.assertIn("PHONE_EMULATOR_SCREENSHOT.png", phone_emulator_smoke_script)
        self.assertIn("$PowerShell = Get-ChildPowerShellCommand", phone_emulator_smoke_script)
        self.assertNotIn("& powershell", phone_emulator_smoke_script)
        self.assertIn("-no-window", phone_emulator_smoke_script)
        self.assertIn("sys.boot_completed", phone_emulator_smoke_script)
        self.assertIn("smoke_phone_on_device.ps1", phone_emulator_smoke_script)
        self.assertIn("Install page", readiness_script)
        self.assertIn("PHONE_DEVICE_SMOKE.json", readiness_script)
        self.assertIn("phone_device_smoke", readiness_script)
        self.assertIn("PHONE_EMULATOR_SMOKE.json", readiness_script)
        self.assertIn("phone_emulator_smoke", readiness_script)
        self.assertIn("Android emulator smoke", readiness_script)
        self.assertIn("SUBMISSION_MANIFEST.md", submission_script)
        self.assertIn("path_safety.ps1", submission_script)
        self.assertIn("VerityLens-submission.zip", submission_script)
        self.assertIn("SUBMISSION_BUNDLE_VERIFICATION.json", submission_script)
        self.assertIn("SUBMISSION_BUNDLE_VERIFICATION.md", submission_script)
        self.assertIn("-OutJson", submission_script)
        self.assertIn("-OutMarkdown", submission_script)
        self.assertIn("verify_submission_bundle.ps1", submission_script)
        self.assertIn("SUBMISSION_BUNDLE_VERIFICATION", submission_verify_script)
        self.assertIn("quality/product_acceptance_latest.json", submission_verify_script)
        self.assertIn("Product acceptance section has fewer than required cases", submission_verify_script)
        self.assertIn("min_cases_by_section", submission_verify_script)
        self.assertIn("quality/quality_pack_v3_live.json", submission_verify_script)
        self.assertIn("quality/release_gate_latest.json", submission_verify_script)
        self.assertIn("skip_fresh_render_venv", submission_verify_script)
        self.assertIn("fresh_venv_requirements_ok", submission_verify_script)
        self.assertIn("Release gate report contains non-passed steps", submission_verify_script)
        self.assertIn("Release gate report is missing required step", submission_verify_script)
        self.assertIn("Release gate report is missing required phone device smoke step", submission_verify_script)
        self.assertIn("Read-NestedZipEntryInfo", submission_verify_script)
        self.assertIn("Test-GatedSourceEntry", submission_verify_script)
        self.assertIn("Release gate report is older than gated source entries", submission_verify_script)
        self.assertIn("temporary tunnel phone readiness is false", submission_verify_script)
        self.assertNotIn('"phone_temporary_tunnel", "render_deploy_package"', submission_verify_script)
        self.assertIn("Phone readiness report refresh", submission_verify_script)
        self.assertIn("Test-EntryMatchesArtifactStatus", submission_verify_script)
        self.assertIn("Release gate artifact", submission_verify_script)
        self.assertIn("Release gate LAN API server summary is missing", submission_verify_script)
        self.assertIn("Release gate LAN API server summary is not healthy", submission_verify_script)
        self.assertIn("Cloud deployment status", submission_verify_script)
        self.assertIn("SHA256 mismatch for", submission_verify_script)
        self.assertIn("PHONE_DEVICE_SMOKE.json", submission_verify_script)
        self.assertIn("Phone device smoke APK SHA256 does not match any packaged phone APK", submission_verify_script)
        self.assertIn("Phone readiness embedded device smoke", submission_verify_script)
        self.assertIn("ReleaseGate.artifacts.device_smoke", submission_verify_script)
        self.assertIn("Read-ZipEntryPngInfo", submission_verify_script)
        self.assertIn("Phone device smoke screenshot is not recorded as a valid PNG", submission_verify_script)
        self.assertIn("phone/PHONE_DEVICE_SCREENSHOT.png is not a valid PNG screenshot", submission_verify_script)
        self.assertIn("Phone device smoke screenshot dimensions do not match", submission_verify_script)
        self.assertIn("PHONE_EMULATOR_SMOKE.json", submission_verify_script)
        self.assertIn("PHONE_APK_VERIFICATION.json", submission_verify_script)
        self.assertIn("VerityLens-internet-flutter-source-stamp.json", submission_script)
        self.assertIn("VerityLens-lan-flutter-source-stamp.json", submission_script)
        self.assertIn("VerityLens-cloud-flutter-source-stamp.json", submission_script)
        self.assertIn("Test-ApkSourceStampEntry", submission_verify_script)
        self.assertIn("Internet APK verification is not OK", submission_verify_script)
        self.assertIn("Internet APK verification expected mode is not release", submission_verify_script)
        self.assertIn("temporary_tunnel_api_failure_allowed", submission_verify_script)
        self.assertIn("temporary tunnel is unavailable", submission_verify_script)
        self.assertIn("Internet APK verification SHA256 does not match", submission_verify_script)
        self.assertIn("ReleaseGate.artifacts.internet_apk_verification", submission_verify_script)
        self.assertIn("bundled Flutter source stamp SHA256 does not match APK verification", submission_verify_script)
        self.assertIn("Internet APK verification Flutter source stamp does not match", submission_verify_script)
        self.assertIn("Internet APK verification status file does not match the Flutter source stamp", submission_verify_script)
        self.assertIn("PHONE_LAN_APK_VERIFICATION.json", submission_verify_script)
        self.assertIn("LAN APK verification is not OK", submission_verify_script)
        self.assertIn("LAN APK verification expected mode is not release", submission_verify_script)
        self.assertIn("LAN APK verification Flutter source stamp does not match", submission_verify_script)
        self.assertIn("Cloud APK verification Flutter source stamp does not match", submission_verify_script)
        self.assertIn("Cloud APK verification expected mode is not release", submission_verify_script)
        self.assertIn("Phone install page exposes cloud APK download before permanent cloud readiness", submission_verify_script)
        self.assertIn("Phone install page marks cloud APK download ready before phone_permanent_cloud is true", submission_verify_script)
        self.assertIn("Phone install page marks cloud APK download ready without release cloud APK verification", submission_verify_script)
        self.assertIn("Cloud deployment status says verification OK, but cloud APK verification JSON is not OK", submission_verify_script)
        self.assertIn("Cloud deployment status says readiness OK, but phone_permanent_cloud is false", submission_verify_script)
        self.assertIn("Cloud deployment status says verification OK without publish-ready cloud APK evidence", submission_verify_script)
        self.assertIn("Cloud deployment status outcome is permanent_cloud_phone_ready but readiness_ok is false", submission_verify_script)
        self.assertIn("Release gate cloud APK mode is not release", submission_verify_script)
        self.assertIn("Phone emulator smoke artifacts are partial", submission_verify_script)
        self.assertIn("Phone emulator wrapper is OK but nested device smoke is not OK", submission_verify_script)
        self.assertIn("Phone emulator smoke APK SHA256 does not match", submission_verify_script)
        self.assertIn("ReleaseGate.artifacts.emulator_smoke", submission_verify_script)
        self.assertIn("source/verity-lens-source.zip", submission_verify_script)
        self.assertIn("Permanent cloud phone readiness is false", submission_verify_script)
        self.assertIn("Temporary tunnel phone readiness is false", submission_verify_script)
        self.assertIn("FakeNewsDetector-Windows-Portable.zip", submission_script)
        self.assertIn("VerityLens-cloud.apk", submission_script)
        self.assertIn("DESKTOP_PACKAGE_VERIFICATION.md", submission_script)
        self.assertIn("verity_lens_report.pdf", submission_script)
        self.assertIn("CLOUD_DEPLOYMENT_STATUS.md", submission_script)
        self.assertIn("PHONE_CLOUD_APK_VERIFICATION.md", submission_script)
        self.assertIn("PHONE_CLOUD_APK_VERIFICATION.json", submission_script)
        self.assertIn("PHONE_LAN_APK_VERIFICATION.md", submission_script)
        self.assertIn("PHONE_LAN_APK_VERIFICATION.json", submission_script)
        self.assertIn("PHONE_EMULATOR_SMOKE.md", submission_script)
        self.assertIn("PHONE_EMULATOR_SMOKE.json", submission_script)
        self.assertIn("PHONE_EMULATOR_SCREENSHOT.png", submission_script)
        self.assertIn("PHONE_DEVICE_SMOKE.md", submission_script)
        self.assertIn("PHONE_DEVICE_SMOKE.json", submission_script)
        self.assertIn("PHONE_DEVICE_SCREENSHOT.png", submission_script)
        self.assertIn("Phone device smoke screenshot SHA256 does not match", submission_verify_script)
        self.assertIn("Phone device smoke is OK but was not run with -RequirePhysicalDevice", submission_verify_script)
        self.assertIn("Phone device smoke physical device identity is incomplete", submission_verify_script)
        self.assertIn("Phone device smoke physical device identity is missing", submission_verify_script)
        self.assertIn("final proof requires a physical Android device", submission_verify_script)
        self.assertIn("Phone emulator smoke screenshot SHA256 does not match", submission_verify_script)
        self.assertIn("VerityLens-cloud-status.md", submission_script)
        self.assertIn("VerityLens-cloud-api-url.txt", submission_script)
        self.assertIn("RENDER_BUNDLE_SMOKE.md", submission_script)
        self.assertIn("Get-FileHash", submission_script)
        self.assertIn("make_source_bundle.ps1", submission_script)
        self.assertIn("verity-lens-source.zip", submission_script)
        self.assertIn("reports\\product_acceptance_latest.md", submission_script)
        self.assertIn("reports\\product_acceptance_latest.json", submission_script)
        self.assertIn("reports\\quality_pack_v3_live.md", submission_script)
        self.assertIn("reports\\quality_pack_v3_live.json", submission_script)
        self.assertIn("reports\\render_deploy_config_latest.md", submission_script)
        self.assertIn("reports\\render_deploy_config_latest.json", submission_script)
        self.assertIn("quality/render_deploy_config_latest.json", submission_verify_script)
        self.assertIn("Render deploy config verification is not OK", submission_verify_script)
        self.assertIn("Render deploy config does not prove Dockerfile uses the Render PORT", submission_verify_script)
        self.assertIn("reports\\release_gate_latest.md", submission_script)
        self.assertIn("reports\\release_gate_latest.json", submission_script)
        self.assertIn("reports\\final_external_preflight_latest.md", submission_script)
        self.assertIn("reports\\final_external_preflight_latest.json", submission_script)
        self.assertIn("reports\\final_cloud_phone_submission_latest.md", submission_script)
        self.assertIn("reports\\final_cloud_phone_submission_latest.json", submission_script)
        self.assertIn("Test-FinalCloudPhoneSubmissionReportReady", submission_script)
        self.assertIn("make_submission_bundle.ps1 only packages successful final reports", submission_verify_script)
        self.assertIn("final_cloud_phone_submission_report", submission_verify_script)
        self.assertIn("packaged_only_when_ok", submission_verify_script)
        self.assertIn("Final cloud phone submission report status", submission_verify_script)
        self.assertIn("final/final_external_preflight_latest.json", submission_verify_script)
        self.assertIn("Final external preflight artifacts are partial", submission_verify_script)
        self.assertIn("Final external preflight is not ready to run finalizer", submission_verify_script)
        self.assertIn("final/final_cloud_phone_submission_latest.json", submission_verify_script)
        self.assertIn("Final cloud phone submission artifacts are partial", submission_verify_script)
        self.assertIn("Final cloud phone submission report is present but not OK", submission_verify_script)
        self.assertIn("Final cloud phone submission OK report has false or missing evidence field", submission_verify_script)
        self.assertIn("Final cloud phone submission OK report does not record the physical phone device id", submission_verify_script)
        self.assertIn("Final cloud phone submission OK report does not record the immutable final packaging contract", submission_verify_script)
        self.assertIn("Final cloud phone submission OK report is missing required post-report packaging check", submission_verify_script)
        self.assertIn("pre_final_report_bundle_snapshot", submission_verify_script)
        self.assertIn("Goal Completion Audit", goal_audit_script)
        self.assertIn("estimated_completion_percent", goal_audit_script)
        self.assertIn("phone_permanent_cloud", goal_audit_script)
        self.assertIn("CloudApkReleaseModeOk", goal_audit_script)
        self.assertIn("CloudApkVerificationOk", goal_audit_script)
        self.assertIn("CloudApkApiOk", goal_audit_script)
        self.assertIn("CloudApkApiPermanentUrl", goal_audit_script)
        self.assertIn("CloudApkEmbeddedMatchesApiUrl", goal_audit_script)
        self.assertIn("CloudApkStatusMatchesUrl", goal_audit_script)
        self.assertIn("CloudApkStatusMatchesMode", goal_audit_script)
        self.assertIn("CloudApkEmbeddedUrlOk", goal_audit_script)
        self.assertIn("CloudApkSourceFresh", goal_audit_script)
        self.assertIn("CloudStatusVerificationOk", goal_audit_script)
        self.assertIn("CloudStatusReadinessOk", goal_audit_script)
        self.assertIn("CloudStatusReadyToPublish", goal_audit_script)
        self.assertIn("Cloud APK API permanent URL", goal_audit_script)
        self.assertIn("Cloud APK embedded URL matches API", goal_audit_script)
        self.assertIn("Cloud APK status file matches URL", goal_audit_script)
        self.assertIn("Cloud APK status file matches mode", goal_audit_script)
        self.assertIn("physical_phone_proof", goal_audit_script)
        self.assertIn("selected_device_is_emulator", goal_audit_script)
        self.assertIn("DeviceSmokeHasSelectedDevice", goal_audit_script)
        self.assertIn("DeviceSmokeIdentityRecorded", goal_audit_script)
        self.assertIn("device_identity.hardware", goal_audit_script)
        self.assertIn("DeviceScreenshotShaMatches", goal_audit_script)
        self.assertIn("DeviceScreenshotValidPng", goal_audit_script)
        self.assertIn("screenshot.sha256", goal_audit_script)
        self.assertIn("Screenshot SHA256 matches file", goal_audit_script)
        self.assertIn("Screenshot valid PNG with dimensions", goal_audit_script)
        self.assertIn("Selected device id", goal_audit_script)
        self.assertIn("require_physical_device", goal_audit_script)
        self.assertIn("SUBMISSION_BUNDLE_VERIFICATION.json", goal_audit_script)
        self.assertIn("Final External Preflight", final_external_preflight_script)
        self.assertIn("final_external_preflight_latest", final_external_preflight_script)
        self.assertIn("Assert-PermanentCloudApiUrl", final_external_preflight_script)
        self.assertIn("ready_to_run_finalizer", final_external_preflight_script)
        self.assertIn("RequireReady", final_external_preflight_script)
        self.assertIn("RetryDelaySeconds", final_external_preflight_script)
        self.assertIn("Test-FactcheckProbe", final_external_preflight_script)
        self.assertIn("health_attempts", final_external_preflight_script)
        self.assertIn("fake_probe_attempts", final_external_preflight_script)
        self.assertIn("final_evidence_contract", final_external_preflight_script)
        self.assertIn("Final Evidence Contract", final_external_preflight_script)
        self.assertIn("next_actions", final_external_preflight_script)
        self.assertIn("Next Actions", final_external_preflight_script)
        self.assertIn("Deploy the Render backend", final_external_preflight_script)
        self.assertIn("After the missing items are fixed", final_external_preflight_script)
        self.assertIn("cloud_status_ready_to_publish", final_external_preflight_script)
        self.assertIn("cloud_apk_api_permanent_url", final_external_preflight_script)
        self.assertIn("cloud_apk_api_not_temporary_tunnel", final_external_preflight_script)
        self.assertIn("cloud_apk_embedded_api_matches_base_url", final_external_preflight_script)
        self.assertIn("cloud_apk_status_matches_flutter_source_stamp", final_external_preflight_script)
        self.assertIn("phone_device_screenshot_sha256_matches", final_external_preflight_script)
        self.assertIn("phone_device_screenshot_valid_png", final_external_preflight_script)
        self.assertIn("phone_device_identity_recorded", final_external_preflight_script)
        self.assertIn("reports\\final_cloud_phone_submission_latest.json", final_external_preflight_script)
        self.assertIn("AllowEmulator", final_external_preflight_script)
        self.assertIn("-CloudApkOutputName", final_external_preflight_script)
        self.assertIn("-PhoneDeviceId", final_external_preflight_script)
        self.assertIn("-AdbPath", final_external_preflight_script)
        self.assertIn("Assert-ApkOutputName", final_external_preflight_script)
        self.assertIn("New-FinalizerCommand", final_external_preflight_script)
        self.assertIn("ConvertTo-PowerShellSingleQuotedArgument", final_external_preflight_script)
        self.assertIn("authorized physical USB Android device", final_external_preflight_script)
        self.assertIn("selected_physical_device_authorized", final_external_preflight_script)
        self.assertIn("adb_accessible", final_external_preflight_script)
        self.assertIn("adb_requested_path", final_external_preflight_script)
        self.assertIn("adb_devices_command", final_external_preflight_script)
        self.assertIn("adb_devices_output", final_external_preflight_script)
        self.assertIn("unauthorized_devices", final_external_preflight_script)
        self.assertIn("offline_devices", final_external_preflight_script)
        self.assertIn("authorized_emulator_devices", final_external_preflight_script)
        self.assertIn("requested_device_state", final_external_preflight_script)
        self.assertIn("ADB executable access permission", final_external_preflight_script)
        self.assertIn("ADB executable accessible", final_external_preflight_script)
        self.assertIn("Fix the requested -AdbPath", final_external_preflight_script)
        self.assertIn("Raw ADB Devices Output", final_external_preflight_script)
        self.assertIn("Authorize Android USB debugging", final_external_preflight_script)
        self.assertIn("adb kill-server", final_external_preflight_script)
        self.assertIn("Only emulator device", final_external_preflight_script)
        self.assertIn("No Android devices are listed by adb devices", final_external_preflight_script)
        self.assertIn("ro.kernel.qemu", final_external_preflight_script)
        self.assertIn("adb devices", final_external_preflight_script)
        self.assertIn("ProcessStartInfo", final_external_preflight_script)
        self.assertIn("RedirectStandardOutput", final_external_preflight_script)
        self.assertIn("adb timed out", final_external_preflight_script)
        self.assertIn("finalize_cloud_phone_submission.ps1", final_external_preflight_script)
        self.assertIn("/health", final_external_preflight_script)
        self.assertIn("/ready", final_external_preflight_script)
        self.assertIn("/factcheck", final_external_preflight_script)
        for doc_text in (readme, runbook, mobile_render_doc):
            self.assertIn("USB debugging", doc_text)
            self.assertIn("adb devices", doc_text)
            self.assertIn("-RequireReady", doc_text)
            self.assertIn("-PhoneDeviceId", doc_text)
            self.assertIn("-AdbPath", doc_text)
            self.assertIn("Final Evidence Contract", doc_text)
        self.assertIn("scripts\\check_final_external_prereqs.ps1", source_bundle_script)
        self.assertIn("scripts\\audit_project_goal_completion.ps1", source_bundle_script)
        self.assertIn("scripts/check_final_external_prereqs.ps1", submission_verify_script)
        self.assertIn("scripts/audit_project_goal_completion.ps1", submission_verify_script)
        self.assertIn("source-bundle", submission_script)
        self.assertIn("src\\api_factcheck.py", source_bundle_script)
        self.assertIn("scripts\\cloud_url_policy.ps1", source_bundle_script)
        self.assertIn("scripts\\path_safety.ps1", source_bundle_script)
        self.assertIn("scripts\\finalize_cloud_phone_submission.ps1", source_bundle_script)
        self.assertIn("scripts\\write_cloud_deployment_status.ps1", source_bundle_script)
        self.assertIn("scripts\\smoke_phone_emulator.ps1", source_bundle_script)
        self.assertIn("apps\\fake_news_detector_flutter\\lib\\main.dart", source_bundle_script)
        self.assertIn("tests\\test_factcheck_core.py", source_bundle_script)
        self.assertIn("__pycache__", source_bundle_script)
        self.assertIn(".dart_tool", source_bundle_script)
        self.assertIn("outputs/*", source_bundle_script)
        self.assertIn('namespace = "app.veritylens.mobile"', android_gradle_script)
        self.assertIn('applicationId = "app.veritylens.mobile"', android_gradle_script)
        self.assertTrue(main_activity_path.exists())
        self.assertFalse(legacy_main_activity_path.exists())
        self.assertIn("package app.veritylens.mobile", main_activity)
        self.assertNotIn("com.fakenewsdetector.fake_news_detector_flutter", android_gradle_script)
        self.assertNotIn("TODO:", android_gradle_script)
        self.assertIn("_query_relevance_score", retrieval_script)
        self.assertNotIn("_result_relevance_stub", retrieval_script)
        self.assertIn("CLOUD_DEPLOYMENT_STATUS.md", cloud_finalize_script)
        self.assertIn("build_phone_for_cloud.ps1", cloud_finalize_script)
        self.assertIn("smoke_render_backend_bundle.ps1", cloud_finalize_script)
        self.assertIn("-FreshVenv", cloud_finalize_script)
        self.assertIn("CLOUD_DEPLOYMENT_STATUS.json", cloud_status_script)
        self.assertIn("render_bundle_requirements_ok", cloud_status_script)
        self.assertIn("File-Status", cloud_status_script)
        self.assertIn("PHONE_CLOUD_APK_VERIFICATION.json", cloud_status_script)
        self.assertIn("cloud_apk_source_stamp", cloud_status_script)
        self.assertIn("Read-CloudApkSourceStampStatus", cloud_status_script)
        self.assertIn("Read-CloudApkVerificationStatus", cloud_status_script)
        self.assertIn("cloud_apk_verification_status", cloud_status_script)
        self.assertIn("verification_requested_ok", cloud_status_script)
        self.assertIn("readiness_requested_ok", cloud_status_script)
        self.assertIn("ready_to_publish", cloud_status_script)
        self.assertIn("Permanent cloud phone readiness was requested, but cloud APK verification evidence is incomplete", cloud_status_script)
        self.assertIn("matches_current_source", cloud_status_script)
        self.assertIn("status_file_matches_flutter_source_stamp", cloud_status_script)
        self.assertIn("write_cloud_deployment_status.ps1", cloud_finalize_script)
        self.assertIn("$WriteCloudDeploymentStatus", cloud_finalize_script)
        self.assertNotIn("function File-Status", cloud_finalize_script)
        self.assertIn("verify_phone_apk.ps1", cloud_finalize_script)
        self.assertIn("RequireCloud", cloud_finalize_script)
        self.assertIn("cloud_url_policy.ps1", cloud_finalize_script)
        self.assertIn("Assert-PermanentCloudApiUrl", cloud_finalize_script)
        self.assertIn("Assert-ApkOutputName", cloud_finalize_script)
        self.assertIn("$PowerShell = Get-ChildPowerShellCommand", cloud_finalize_script)
        self.assertNotIn("& powershell", cloud_finalize_script)
        self.assertIn("run_release_gate.ps1", final_submission_script)
        self.assertIn("-BuildCloudApk", final_submission_script)
        self.assertIn("-RequirePhoneDevice", final_submission_script)
        self.assertIn("-RequirePhysicalPhoneDevice", final_submission_script)
        self.assertIn("-PhoneDeviceApkPath", final_submission_script)
        self.assertIn("-AdbPath", final_submission_script)
        self.assertIn("check_final_external_prereqs.ps1", final_submission_script)
        self.assertIn("Final external preflight", final_submission_script)
        self.assertIn("-RequireReady", final_submission_script)
        self.assertIn("make_submission_bundle.ps1", final_submission_script)
        self.assertIn("verify_submission_bundle.ps1", final_submission_script)
        self.assertIn("audit_project_goal_completion.ps1", final_submission_script)
        self.assertIn("Final cloud phone evidence check", final_submission_script)
        self.assertIn("Final submission bundle with final report", final_submission_script)
        self.assertIn("Final submission verifier with final report", final_submission_script)
        self.assertIn("Goal completion audit refresh", final_submission_script)
        self.assertIn("Final cloud phone evidence recheck", final_submission_script)
        self.assertIn("Write-FinalReport -Ok $true", final_submission_script)
        self.assertIn("$FinalReportPackaged", final_submission_script)
        self.assertIn("packaging_contract", final_submission_script)
        self.assertIn("immutable_success_report", final_submission_script)
        self.assertIn("submission_zip_artifact_scope", final_submission_script)
        self.assertIn("submission_verification_artifact_scope", final_submission_script)
        self.assertIn("post_report_checks_required_after_snapshot", final_submission_script)
        self.assertIn("pre_final_report_bundle_snapshot", final_submission_script)
        self.assertIn("if (-not ($Ok -and $FinalReportPackaged))", final_submission_script)
        self.assertIn("Assert-FinalEvidenceReady", final_submission_script)
        self.assertIn("goal_audit_complete", final_submission_script)
        self.assertIn("final_cloud_phone_submission_latest", final_submission_script)
        self.assertIn("Final cloud phone submission requires -CloudApkMode release", final_submission_script)
        self.assertIn("debug-only local diagnostics", final_submission_script)
        self.assertIn("Assert-PermanentCloudApiUrl", final_submission_script)
        self.assertIn("Assert-PathInsideDirectory", final_submission_script)
        self.assertIn("Assert-ApkOutputName", final_submission_script)
        self.assertIn("$PowerShell = Get-ChildPowerShellCommand", final_submission_script)
        self.assertNotIn("& powershell", final_submission_script)
        self.assertIn("$PowerShell = Get-ChildPowerShellCommand", submission_script)
        self.assertNotIn("& powershell", submission_script)
        self.assertIn("PHONE_DEVICE_SCREENSHOT.png", final_submission_script)
        self.assertIn("phone_permanent_cloud", final_submission_script)
        self.assertIn("cloud_status_outcome_ready", final_submission_script)
        self.assertIn("cloud_status_verification_ok", final_submission_script)
        self.assertIn("cloud_status_readiness_ok", final_submission_script)
        self.assertIn("cloud_status_ready_to_publish", final_submission_script)
        self.assertIn("cloud_apk_release_mode", final_submission_script)
        self.assertIn("cloud_apk_api_permanent_url", final_submission_script)
        self.assertIn("cloud_apk_api_not_temporary_tunnel", final_submission_script)
        self.assertIn("cloud_apk_api_matches_requested_url", final_submission_script)
        self.assertIn("cloud_apk_embedded_api_url_found", final_submission_script)
        self.assertIn("cloud_apk_embedded_api_matches_base_url", final_submission_script)
        self.assertIn("cloud_apk_status_matches_url", final_submission_script)
        self.assertIn("cloud_apk_status_matches_mode", final_submission_script)
        self.assertIn("cloud_apk_status_matches_flutter_source_stamp", final_submission_script)
        self.assertIn("Cloud APK API not temporary tunnel", final_submission_script)
        self.assertIn("Cloud APK status matches Flutter source stamp", final_submission_script)
        self.assertIn("cloud_deployment_status_json", final_submission_script)
        self.assertIn("phone_device_requires_physical", final_submission_script)
        self.assertIn("phone_device_selected_id", final_submission_script)
        self.assertIn("phone_device_selected_physical", final_submission_script)
        self.assertIn("phone_device_screenshot_sha256_recorded", final_submission_script)
        self.assertIn("phone_device_screenshot_sha256_matches", final_submission_script)
        self.assertIn("phone_device_screenshot_valid_png", final_submission_script)
        self.assertIn("Phone screenshot valid PNG", final_submission_script)
        self.assertIn("phone_device_identity_recorded", final_submission_script)
        self.assertIn("device_identity.hardware", final_submission_script)
        self.assertIn("selected_device_is_emulator", final_submission_script)
        self.assertIn("Get-FileHash -LiteralPath $DeviceScreenshot", final_submission_script)
        self.assertIn("Test-PathInsideDirectory", path_safety_script)
        self.assertIn("Assert-PathInsideDirectory", path_safety_script)
        self.assertIn("Remove-PathInsideDirectory", path_safety_script)
        self.assertIn("Assert-ApkOutputName", path_safety_script)
        self.assertIn("Assert-FileNameOnly", path_safety_script)
        self.assertIn("Get-ChildPowerShellCommand", path_safety_script)
        self.assertIn("$PSHOME", path_safety_script)
        self.assertIn("[System.IO.Path]::DirectorySeparatorChar", path_safety_script)
        self.assertNotIn("StartsWith($ProjectRoot", source_bundle_script)
        self.assertNotIn("StartsWith($Root", bundle_script)

    def test_source_bundle_contains_reproducible_source_without_generated_outputs(self):
        output_path = ROOT / "outputs" / "submission" / "test-source-bundle.zip"
        if output_path.exists():
            output_path.unlink()
        report_aux_files = [
            ROOT / "docs" / "report" / "verity_lens_report.aux",
            ROOT / "docs" / "report" / "verity_lens_report.log",
            ROOT / "docs" / "report" / "verity_lens_report.out",
            ROOT / "docs" / "report" / "verity_lens_report.toc",
            ROOT / "docs" / "report" / "verity_lens_report.fls",
            ROOT / "docs" / "report" / "verity_lens_report.fdb_latexmk",
            ROOT / "docs" / "report" / "verity_lens_report.synctex.gz",
        ]
        for aux_file in report_aux_files:
            aux_file.write_text("generated report byproduct\n", encoding="utf-8")

        try:
            completed = subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(ROOT / "scripts" / "make_source_bundle.ps1"),
                    "-OutputPath",
                    str(output_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=90,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            self.assertTrue(output_path.exists())
            with zipfile.ZipFile(output_path) as source_zip:
                entries = {name.replace("\\", "/") for name in source_zip.namelist()}

            for required in {
                "README.md",
                "src/api_factcheck.py",
                "src/factcheck/service.py",
                "scripts/cloud_url_policy.ps1",
                "scripts/path_safety.ps1",
                "scripts/verify_render_deploy_config.py",
                "scripts/run_release_gate.ps1",
                "scripts/finalize_cloud_phone_submission.ps1",
                "scripts/smoke_phone_emulator.ps1",
                "scripts/smoke_phone_on_device.ps1",
                "scripts/verify_submission_bundle.ps1",
                "requirements.optional-ai.txt",
                "requirements.legacy-train.txt",
                "tests/test_factcheck_core.py",
                "docs/report/verity_lens_report.tex",
                "apps/fake_news_detector_flutter/pubspec.yaml",
                "apps/fake_news_detector_flutter/lib/main.dart",
                "apps/fake_news_detector_flutter/tool/flutter_source_stamp.ps1",
                "apps/fake_news_detector_flutter/test/widget_test.dart",
            }:
                self.assertIn(required, entries)

            forbidden = [
                entry
                for entry in entries
                if entry.startswith((".venv/", "outputs/", "dist/", "build/", "archive/"))
                or "__pycache__" in entry
                or entry.endswith((".pyc", ".pyo", ".iml", ".log"))
                or entry.endswith(
                    (
                        "GeneratedPluginRegistrant.java",
                        "GeneratedPluginRegistrant.h",
                        "GeneratedPluginRegistrant.m",
                    )
                )
                or entry.startswith("apps/fake_news_detector_flutter/build/")
                or entry.startswith("apps/fake_news_detector_flutter/.dart_tool/")
                or entry == "apps/fake_news_detector_flutter/android/local.properties"
                or entry == "docs/report/verity_lens_report.pdf"
                or (
                    entry.startswith("docs/report/")
                    and entry.endswith(
                        (
                            ".aux",
                            ".out",
                            ".toc",
                            ".fls",
                            ".fdb_latexmk",
                            ".synctex.gz",
                            ".xdv",
                            ".bbl",
                            ".blg",
                            ".nav",
                            ".snm",
                            ".vrb",
                        )
                    )
                )
            ]
            self.assertEqual(forbidden, [])
        finally:
            if output_path.exists():
                output_path.unlink()
            for aux_file in report_aux_files:
                if aux_file.exists():
                    aux_file.unlink()

    def test_permanent_cloud_url_policy_rejects_local_private_and_tunnel_hosts(self):
        policy_path = str(ROOT / "scripts" / "cloud_url_policy.ps1").replace("'", "''")
        script = f"""
$ErrorActionPreference = 'Stop'
. '{policy_path}'
$Allowed = Assert-PermanentCloudApiUrl -Value 'https://example.onrender.com/' -Purpose 'test'
if ($Allowed -ne 'https://example.onrender.com') {{
  throw "unexpected normalization: $Allowed"
}}
$BadUrls = @(
  'http://example.onrender.com',
  'https://localhost:8001',
  'https://127.0.0.1:8001',
  'https://192.168.1.16:8001',
  'https://10.0.0.5',
  'https://172.16.0.5',
  'https://foo.local',
  'https://grumpy-doors-obey.loca.lt',
  'https://x.trycloudflare.com',
  'https://singlelabel'
)
foreach ($Url in $BadUrls) {{
  $Accepted = $false
  try {{
    [void](Assert-PermanentCloudApiUrl -Value $Url -Purpose 'test')
    $Accepted = $true
  }} catch {{
  }}
  if ($Accepted) {{
    throw "accepted invalid permanent cloud URL: $Url"
  }}
}}
Write-Output 'policy ok'
"""
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertIn("policy ok", completed.stdout)

    def test_apk_output_name_policy_rejects_paths(self):
        policy_path = str(ROOT / "scripts" / "path_safety.ps1").replace("'", "''")
        script = f"""
$ErrorActionPreference = 'Stop'
. '{policy_path}'
$Allowed = Assert-ApkOutputName -Name 'VerityLens-cloud.apk'
if ($Allowed -ne 'VerityLens-cloud.apk') {{
  throw "unexpected apk name normalization: $Allowed"
}}
$BadNames = @(
  '',
  'VerityLens-cloud.zip',
  '..\\evil.apk',
  'nested\\evil.apk',
  'C:\\temp\\evil.apk',
  '.',
  '..'
)
foreach ($Name in $BadNames) {{
  $Accepted = $false
  try {{
    [void](Assert-ApkOutputName -Name $Name)
    $Accepted = $true
  }} catch {{
  }}
  if ($Accepted) {{
    throw "accepted invalid APK output name: $Name"
  }}
}}
Write-Output 'apk name policy ok'
"""
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertIn("apk name policy ok", completed.stdout)

    def test_final_external_preflight_quotes_copy_paste_command(self):
        out_json = ROOT / "reports" / "test_final_external_preflight_command.json"
        out_md = ROOT / "reports" / "test_final_external_preflight_command.md"
        for path in (out_json, out_md):
            if path.exists():
                path.unlink()
        try:
            completed = subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(ROOT / "scripts" / "check_final_external_prereqs.ps1"),
                    "-CloudApkOutputName",
                    "My Cloud.apk",
                    "-PhoneDeviceId",
                    "USB DEVICE 1",
                    "-AdbPath",
                    "C:\\ADB Tools\\adb.exe",
                    "-OutJson",
                    str(out_json),
                    "-OutMarkdown",
                    str(out_md),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            report = json.loads(out_json.read_text(encoding="utf-8-sig"))
            self.assertEqual(
                report["finalizer_command"],
                ".\\scripts\\finalize_cloud_phone_submission.ps1 "
                "-ApiBaseUrl 'https://<render-app>.onrender.com' "
                "-CloudApkOutputName 'My Cloud.apk' "
                "-PhoneDeviceId 'USB DEVICE 1' "
                "-AdbPath 'C:\\ADB Tools\\adb.exe'",
            )
        finally:
            for path in (out_json, out_md):
                if path.exists():
                    path.unlink()

    def test_release_gate_covers_pc_mobile_and_cloud_paths(self):
        gate = ROOT / "scripts" / "run_release_gate.ps1"
        self.assertTrue(gate.exists())

        gate_text = gate.read_text(encoding="utf-8")
        self.assertIn('[string]$CloudApkMode = "release"', gate_text)
        self.assertIn("cloud_url_policy.ps1", gate_text)
        self.assertIn("Assert-PermanentCloudApiUrl", gate_text)
        self.assertIn("$PowerShell = Get-ChildPowerShellCommand", gate_text)
        self.assertNotIn("& powershell", gate_text)
        self.assertIn("py_compile", gate_text)
        self.assertIn("unittest discover -s tests -v", gate_text)
        self.assertIn("run_product_acceptance.py", gate_text)
        self.assertIn("build_report.ps1", gate_text)
        self.assertIn("verify_render_deploy_config.py", gate_text)
        self.assertIn("Render deploy config verification", gate_text)
        self.assertIn("render_deploy_config", gate_text)
        self.assertIn("make_render_backend_bundle.ps1", gate_text)
        self.assertIn("smoke_render_backend_bundle.ps1", gate_text)
        self.assertIn("Render backend bundle smoke", gate_text)
        self.assertIn("-FreshVenv", gate_text)
        self.assertIn("SkipFreshRenderVenv", gate_text)
        self.assertIn("prepare_phone_install_page.ps1", gate_text)
        self.assertIn("Internet APK verification", gate_text)
        self.assertIn("AllowTemporaryTunnelApiFailure", gate_text)
        self.assertIn("PHONE_APK_VERIFICATION.json", gate_text)
        self.assertIn("Phone install page server", gate_text)
        self.assertIn("-StartServer", gate_text)
        self.assertIn("LAN API server", gate_text)
        self.assertIn("Ensure-LanApiServer", gate_text)
        self.assertIn("Get-LanApiStatus", gate_text)
        self.assertIn("lan_api_server", gate_text)
        self.assertIn("health_url", gate_text)
        self.assertIn("phone-lan-api-release-gate-pid.txt", gate_text)
        self.assertIn("src.api_factcheck:app", gate_text)
        self.assertIn("LAN APK verification", gate_text)
        self.assertIn("PHONE_LAN_APK_VERIFICATION.json", gate_text)
        self.assertIn("emulator_smoke", gate_text)
        self.assertIn("check_phone_readiness.ps1", gate_text)
        self.assertIn("Phone readiness report", gate_text)
        self.assertIn("Cloud phone readiness report", gate_text)
        self.assertIn("src.desktop_app --smoke --port 0", gate_text)
        self.assertIn("verify_desktop_package.ps1", gate_text)
        self.assertIn("Desktop package verification", gate_text)
        self.assertIn("flutter analyze", gate_text)
        self.assertIn("flutter test", gate_text)
        self.assertIn("verify_cloud_api.ps1", gate_text)
        self.assertIn("build_phone_for_cloud.ps1", gate_text)
        self.assertIn("verify_phone_apk.ps1", gate_text)
        self.assertIn("smoke_phone_on_device.ps1", gate_text)
        self.assertIn("[string]$AdbPath", gate_text)
        self.assertIn("-AdbPath", gate_text)
        self.assertIn("PhoneDeviceSmoke", gate_text)
        self.assertIn("RequirePhoneDevice", gate_text)
        self.assertIn("RequirePhysicalPhoneDevice", gate_text)
        self.assertIn("Phone device smoke", gate_text)
        self.assertIn("Phone device smoke availability", gate_text)
        self.assertIn("Phone readiness report refresh", gate_text)
        self.assertIn("ExistingDeviceSmoke", gate_text)
        self.assertIn("device_smoke", gate_text)
        self.assertIn("Cloud APK verification", gate_text)
        self.assertIn("PHONE_CLOUD_APK_VERIFICATION.json", gate_text)
        self.assertIn("PermanentCloud", gate_text)
        self.assertIn("BuildCloudApk", gate_text)
        self.assertIn("write_cloud_deployment_status.ps1", gate_text)
        self.assertIn("Cloud deployment status report", gate_text)
        self.assertIn("release_gate_latest.json", gate_text)
        self.assertIn("release_gate_latest.md", gate_text)
        self.assertIn("Write-ReleaseGateReport", gate_text)
        self.assertIn("ReleaseSteps", gate_text)
        self.assertIn("fresh_venv_requirements_ok", gate_text)

    def test_product_acceptance_gate_covers_mobile_api_contract(self):
        gate = ROOT / "scripts" / "run_product_acceptance.py"
        gate_text = gate.read_text(encoding="utf-8")
        self.assertIn("api_contract", gate_text)
        self.assertIn("TestClient", gate_text)
        self.assertIn("/health", gate_text)
        self.assertIn("/ready", gate_text)
        self.assertIn("/factcheck", gate_text)
        self.assertIn("/factcheck-image", gate_text)
        self.assertIn("api_cors_preflight_ok", gate_text)
        self.assertIn("api_factcheck_empty_rejected", gate_text)
        self.assertIn("api_image_invalid_analysis_rejected", gate_text)
        self.assertIn("fact_moon_cheese", gate_text)
        self.assertIn("screenshot_ocr_moon_false", gate_text)
        self.assertIn("image_firefly_metadata_marker", gate_text)
        self.assertIn("news_institutional_fda_high_with_matches", gate_text)
        self.assertIn("news_social_reddit_guardrail", gate_text)
        self.assertIn("screenshot_ocr_numeric_true", gate_text)
        self.assertIn("image_leonardo_metadata_marker", gate_text)
        self.assertIn("api_image_missing_file_rejected", gate_text)
        self.assertIn("api_factcheck_get_method_rejected", gate_text)
        self.assertIn("MIN_CASES_BY_SECTION", gate_text)
        self.assertIn('"facts": 40', gate_text)
        self.assertIn('"news": 15', gate_text)
        self.assertIn('"screenshots": 12', gate_text)
        self.assertIn('"images": 11', gate_text)
        self.assertIn('"api_contract": 11', gate_text)
        self.assertIn("min_cases_by_section", gate_text)

    def test_university_latex_report_has_required_structure_and_results(self):
        report = ROOT / "docs" / "report" / "verity_lens_report.tex"
        report_readme = ROOT / "docs" / "report" / "README.md"
        report_build = ROOT / "scripts" / "build_report.ps1"
        self.assertTrue(report.exists())
        self.assertTrue(report_readme.exists())
        self.assertTrue(report_build.exists())

        text = report.read_text(encoding="utf-8")
        for required in [
            "\\section*{Streszczenie}",
            "\\section{Cel projektu}",
            "\\section{Punkt wyjścia}",
            "\\section{Co się nie udało i dlaczego zmieniono podejście}",
            "\\section{Nowe podejście projektowe}",
            "\\section{Architektura końcowa}",
            "\\section{Implementacja interfejsów}",
            "\\section{Wdrożenie chmurowe}",
            "\\section{Testy i dowody działania}",
            "\\section{Historia prac}",
            "\\section{Najważniejsze decyzje projektowe}",
            "\\section{Aktualny sposób działania}",
            "\\section{Ograniczenia}",
            "\\section{Możliwe dalsze prace}",
            "\\section{Wnioski}",
            "93/93 OK",
            "117/117 OK",
            "Facts & 44 & 44 & 100\\%",
            "News & 15 & 15 & 100\\%",
            "Screenshot OCR API & 12 & 12 & 100\\%",
            "Images & 11 & 11 & 100\\%",
            "API/mobile contract & 11 & 11 & 100\\%",
            "Flutter tests & \\path{flutter test} & 11/11 OK",
            "Release gate & release gate & OK, 25 kroków",
            "Final cloud/phone & finalizer cloud-phone & OK",
            "API/mobile contract",
            "VerityLens-cloud.apk",
            "Rozumowanie źródłowo-taksonomiczne",
            "Facts source reasoning",
            "\\texttt{e92ab8e}",
            "final_cloud_phone_submission_latest.json",
            "adb devices",
            "Weryfikator paczki sprawdził",
            "Interfejs ma trzy jasne funkcje: News, Facts, Images",
        ]:
            self.assertIn(required, text)
        self.assertNotIn("\\begin{thebibliography}", text)
        self.assertNotIn("\\section{References}", text)
        self.assertNotIn("\\section{Bibliografia}", text)

        readme_text = report_readme.read_text(encoding="utf-8")
        self.assertIn("build_report.ps1", readme_text)
        build_text = report_build.read_text(encoding="utf-8")
        self.assertIn("BootstrapTectonic", build_text)
        self.assertIn("Convert-PolishToLatexMacros", build_text)
        self.assertIn("verity_lens_report.log", build_text)

    def test_ui_news_result_renders_credibility_not_hard_truth_wording(self):
        html = _render_result(
            {
                "verdict": "uncertain",
                "confidence": 0.31,
                "summary": "This article comes from a strong source and has corroborating evidence.",
                "claim": "Example news headline",
                "evidence": [],
                "trace": {"decision_reasons": [], "fallbacks_used": [], "stage_timings_ms": {}},
                "credibility": {
                    "score": 0.82,
                    "label": "high",
                    "source_score": 0.9,
                    "article_quality_score": 0.8,
                    "corroboration_score": 0.75,
                    "risk_score": 0.0,
                    "matched_sources": [{"domain": "reuters.com"}],
                    "risk_flags": [],
                    "reasons": [],
                },
            }
        )
        self.assertIn("Credibility: high", html)
        self.assertIn("Fact-check verdict: uncertain", html)
        self.assertNotIn("Likely reliable", html)

    def test_ui_supports_pasted_images(self):
        ui_source = (ROOT / "src" / "ui.py").read_text(encoding="utf-8")
        self.assertIn("data-media-picker", ui_source)
        self.assertIn("activeMediaPicker", ui_source)
        self.assertIn("window.addEventListener('paste'", ui_source)
        self.assertIn("DataTransfer", ui_source)
        self.assertIn("pasted-image.", ui_source)

    def test_ui_renders_separate_verification_sections(self):
        html = render_page()
        self.assertIn('class="section-menu"', html)
        self.assertIn('id="toolStage"', html)
        self.assertIn('id="newsTool"', html)
        self.assertIn('id="factsTool"', html)
        self.assertIn('id="imagesTool"', html)
        self.assertNotIn('id="screenshotsTool"', html)
        self.assertNotIn('data-target="screenshotsTool"', html)
        self.assertIn('data-target="newsTool"', html)
        self.assertIn('data-panel="newsTool"', html)
        self.assertIn("activatePanel", html)
        self.assertIn("scrollIntoView", html)
        self.assertIn("hashchange", html)
        self.assertIn("data-info-toggle", html)
        self.assertIn('action="/check#factsTool"', html)
        self.assertIn('name="active_panel" value="factsTool"', html)
        self.assertIn('id="newsGuide"', html)
        self.assertIn('id="factsGuide"', html)
        self.assertIn("What this mode does", html)
        self.assertIn("Example:", html)
        self.assertIn("Check news", html)
        self.assertIn("Check fact", html)
        self.assertIn("Detect AI image", html)
        self.assertNotIn("Screenshots", html)
        self.assertNotIn("Check screenshot", html)

    def test_ui_can_render_requested_active_panel(self):
        html = render_page(active_panel="imagesTool")
        self.assertIn('data-target="imagesTool" aria-selected="true"', html)
        self.assertIn('class="tool-card image active" id="imagesTool" data-panel="imagesTool" aria-hidden="false"', html)
        self.assertIn('class="tool-card news" id="newsTool" data-panel="newsTool" aria-hidden="true"', html)

    def test_ui_scopes_input_values_to_active_panel(self):
        text = "Kevin Warsh is chair of the Federal Reserve"
        html = render_page(text_value=text, active_panel="factsTool")
        self.assertEqual(html.count(text), 1)
        self.assertIn(
            f'<textarea id="factTextInput" name="text" placeholder="Example: Elephant is a mammal">{text}</textarea>',
            html,
        )
        self.assertNotIn("imageQuestionInput", html)
        self.assertNotIn("Optional image context", html)

    @patch("src.ui.run_factcheck")
    def test_ui_preserves_active_panel_after_fact_submit(self, mock_run_factcheck):
        mock_run_factcheck.return_value = SimpleNamespace(
            to_public_dict=lambda: {
                "verdict": "true",
                "confidence": 0.96,
                "summary": "The claim is supported.",
                "claim": "Elephant is a mammal",
                "evidence": [],
                "trace": {"decision_reasons": [], "fallbacks_used": [], "stage_timings_ms": {}},
            }
        )
        client = TestClient(ui_app)
        response = client.post("/check", data={"text": "Elephant is a mammal", "active_panel": "factsTool"})
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn('data-target="factsTool" aria-selected="true"', html)
        self.assertIn('class="tool-card facts active" id="factsTool" data-panel="factsTool" aria-hidden="false"', html)
        self.assertIn('class="tool-card news" id="newsTool" data-panel="newsTool" aria-hidden="true"', html)
        mock_run_factcheck.assert_called_once_with(text="Elephant is a mammal", url="")

    @patch("factcheck.image_analysis.extract_ocr_text")
    def test_screenshot_factcheck_runs_ocr_text_through_engine(self, mock_ocr):
        mock_ocr.return_value = OCRResult(
            text="Apple is blue",
            confidence=0.96,
            lines=[],
            detected_urls=[],
            warnings=[],
        )
        payload = run_screenshot_factcheck(_png_bytes(), filename="claim.png").to_public_dict()
        self.assertEqual(payload["verdict"], "fake")
        self.assertEqual(payload["image_analysis"]["mode"], "screenshot_ocr")
        self.assertEqual(payload["image_analysis"]["ocr_text"], "Apple is blue")

    @patch("factcheck.image_analysis.extract_ocr_text")
    def test_screenshot_factcheck_uses_user_claim_as_focus_when_provided(self, mock_ocr):
        mock_ocr.return_value = OCRResult(
            text="Share now before it is deleted",
            confidence=0.88,
            lines=[],
            detected_urls=["https://example.com/social-post"],
            warnings=[],
        )
        payload = run_screenshot_factcheck(
            _png_bytes(),
            filename="claim.png",
            question="Elephants are insects.",
        ).to_public_dict()
        self.assertEqual(payload["verdict"], "fake")
        self.assertEqual(payload["claim"], "Elephants are insects")
        self.assertIn("screenshot_question_claim_used", payload["trace"]["fallbacks_used"])

    def test_ocr_reading_order_rebuilds_split_same_row_text(self):
        text = _join_ocr_lines_in_reading_order(
            [
                OCRLine(
                    text="plus 2 equals 4",
                    confidence=0.98,
                    box=[[103.0, 110.0], [760.0, 112.0], [760.0, 225.0], [103.0, 223.0]],
                ),
                OCRLine(
                    text="2",
                    confidence=0.99,
                    box=[[55.0, 129.0], [107.0, 132.0], [103.0, 199.0], [51.0, 197.0]],
                ),
            ]
        )
        self.assertEqual(text, "2 plus 2 equals 4")

    @patch("factcheck.image_analysis.extract_ocr_text")
    def test_screenshot_factcheck_abstains_without_readable_text(self, mock_ocr):
        mock_ocr.return_value = OCRResult(
            text="",
            confidence=0.0,
            lines=[],
            detected_urls=[],
            warnings=["ocr_no_text_detected"],
        )
        payload = run_screenshot_factcheck(_png_bytes(), filename="photo.png").to_public_dict()
        self.assertEqual(payload["verdict"], "uncertain")
        self.assertIn("ocr_no_text_detected", payload["image_analysis"]["warnings"])
        self.assertIn("image_ocr_no_checkable_text", payload["trace"]["fallbacks_used"])

    def test_ai_image_detection_uses_explicit_generator_metadata(self):
        payload = run_ai_image_check(
            _png_bytes({"Software": "Stable Diffusion"}),
            filename="generated.png",
        ).to_public_dict()
        self.assertEqual(payload["verdict"], "uncertain")
        self.assertEqual(payload["image_analysis"]["mode"], "ai_image_detection")
        self.assertEqual(payload["image_analysis"]["ai_label"], "likely_ai")
        self.assertGreaterEqual(payload["image_analysis"]["ai_generated_score"], 0.78)

        filename_payload = run_ai_image_check(
            _jpeg_bytes(),
            filename="ChatGPT Image 2026-05-31.jpg",
        ).to_public_dict()
        self.assertEqual(filename_payload["image_analysis"]["ai_label"], "likely_ai")
        self.assertIn("ai_filename_marker", " ".join(filename_payload["image_analysis"]["reasons"]))

        exported_payload = run_ai_image_check(
            _jpeg_bytes(width=1024, height=1024),
            filename="JPEG_20260531_192703_7711461984257405998.jpg",
        ).to_public_dict()
        self.assertEqual(exported_payload["image_analysis"]["ai_label"], "uncertain")
        self.assertGreaterEqual(exported_payload["image_analysis"]["ai_generated_score"], 0.45)
        self.assertIn("android_exported_jpeg_without_camera_metadata", exported_payload["image_analysis"]["reasons"])
        self.assertIn("limited_metadata_only_ai_check", exported_payload["image_analysis"]["warnings"])

    @patch("factcheck.image_analysis._optional_ai_model_signal")
    def test_ai_image_detection_does_not_accuse_on_model_only_ai_signal(self, mock_model):
        mock_model.return_value = ImageModelSignal(
            ai_score=0.95,
            real_score=0.05,
            predicted_label="fake",
            margin=0.90,
            reasons=["model_ai_label=fake:0.950", "model_real_label=real:0.050", "model_prediction=fake", "model_margin=0.900"],
            warnings=[],
        )
        with patch.dict(os.environ, {"FACTCHECK_AI_IMAGE_MODEL": "capcheck/ai-image-detection"}):
            payload = run_ai_image_check(_jpeg_bytes(), filename="generated.jpg").to_public_dict()
        self.assertEqual(payload["image_analysis"]["ai_label"], "uncertain")
        self.assertGreaterEqual(payload["image_analysis"]["ai_generated_score"], 0.65)
        self.assertLessEqual(payload["image_analysis"]["ai_generated_score"], 0.72)
        self.assertIn("model_strong_ai_signal", payload["image_analysis"]["reasons"])
        self.assertIn("model_strong_ai_signal_not_enough_without_metadata", payload["image_analysis"]["warnings"])

    @patch("factcheck.image_analysis._optional_ai_model_signal")
    def test_ai_image_detection_allows_whitelisted_extremely_strong_ai_signal(self, mock_model):
        mock_model.return_value = ImageModelSignal(
            ai_score=0.998,
            real_score=0.002,
            predicted_label="fake",
            margin=0.996,
            reasons=["model_ai_label=artificial:0.998", "model_real_label=real:0.002", "model_prediction=fake", "model_margin=0.996"],
            warnings=[],
        )
        with patch.dict(os.environ, {"FACTCHECK_AI_IMAGE_MODEL": "haywoodsloan/ai-image-detector-deploy"}):
            payload = run_ai_image_check(_jpeg_bytes(), filename="generated.jpg").to_public_dict()
        self.assertEqual(payload["image_analysis"]["ai_label"], "likely_ai")
        self.assertGreaterEqual(payload["image_analysis"]["ai_generated_score"], 0.80)
        self.assertLessEqual(payload["image_analysis"]["ai_generated_score"], 0.88)
        self.assertIn("model_strong_ai_signal", payload["image_analysis"]["reasons"])

    @patch("factcheck.image_analysis._optional_ai_model_signal")
    def test_ai_image_detection_keeps_ambiguous_model_only_score_uncertain(self, mock_model):
        mock_model.return_value = ImageModelSignal(
            ai_score=0.775,
            real_score=0.225,
            predicted_label="fake",
            margin=0.55,
            reasons=["model_ai_label=fake:0.775", "model_real_label=real:0.225", "model_prediction=fake", "model_margin=0.550"],
            warnings=[],
        )
        payload = run_ai_image_check(_jpeg_bytes(), filename="cat.jpg").to_public_dict()
        self.assertEqual(payload["image_analysis"]["ai_label"], "uncertain")
        self.assertGreaterEqual(payload["image_analysis"]["ai_generated_score"], 0.40)
        self.assertLessEqual(payload["image_analysis"]["ai_generated_score"], 0.65)
        self.assertIn("model_ambiguous_not_decisive", payload["image_analysis"]["warnings"])

    @patch("factcheck.image_analysis._optional_ai_model_signal")
    def test_ai_image_detection_allows_strong_model_real_signal(self, mock_model):
        mock_model.return_value = ImageModelSignal(
            ai_score=0.12,
            real_score=0.88,
            predicted_label="real",
            margin=0.76,
            reasons=["model_ai_label=fake:0.120", "model_real_label=real:0.880", "model_prediction=real", "model_margin=0.760"],
            warnings=[],
        )
        payload = run_ai_image_check(_jpeg_bytes(), filename="real-cat.jpg").to_public_dict()
        self.assertEqual(payload["image_analysis"]["ai_label"], "likely_not_ai")
        self.assertLessEqual(payload["image_analysis"]["ai_generated_score"], 0.30)
        self.assertIn("model_strong_real_signal", payload["image_analysis"]["reasons"])

    def test_ai_image_detection_does_not_call_camera_metadata_proof_of_real(self):
        with patch.dict(os.environ, {"FACTCHECK_AI_IMAGE_MODEL": "disabled"}):
            payload = run_ai_image_check(_png_bytes({"Make": "Example Camera"}), filename="metadata.png").to_public_dict()
        self.assertEqual(payload["image_analysis"]["ai_label"], "uncertain")
        self.assertIn("camera_metadata_present=make", payload["image_analysis"]["reasons"])
        self.assertIn("ai_image_detection_not_definitive", payload["image_analysis"]["warnings"])

    @patch("factcheck.image_analysis._optional_ai_model_signal")
    def test_ai_image_detection_model_failure_falls_back_without_crash(self, mock_model):
        mock_model.return_value = ImageModelSignal(
            ai_score=None,
            real_score=None,
            predicted_label="failed",
            margin=0.0,
            reasons=[],
            warnings=["optional_ai_image_model_failed:RuntimeError"],
        )
        payload = run_ai_image_check(_jpeg_bytes(), filename="fallback.jpg").to_public_dict()
        self.assertEqual(payload["image_analysis"]["ai_label"], "uncertain")
        self.assertIn("optional_ai_image_model_failed:RuntimeError", payload["image_analysis"]["warnings"])

    def test_ui_renders_ai_image_risk_status(self):
        html = _render_result(
            run_ai_image_check(
                _png_bytes({"Software": "Stable Diffusion"}),
                filename="generated.png",
            ).to_public_dict()
        )
        self.assertIn("Likely AI", html)
        self.assertIn("Image risk check", html)

    def test_image_eval_manifest_is_versioned_and_readable(self):
        cases = _load_manifest(DEFAULT_MANIFEST)
        self.assertGreaterEqual(len(cases), 13)
        for case in cases:
            self.assertIn(case["expected"], {"ai", "real"})
            self.assertTrue(case["id"])
            self.assertTrue(case["source"])
            self.assertTrue(case["license_or_origin"])
            self.assertTrue(case["notes"])
            self.assertTrue((ROOT / case["local_path"]).exists(), case["local_path"])

    def test_image_eval_metrics_track_high_risk_error_types(self):
        metrics = _metrics(
            [
                {"expected": "real", "ai_label": "likely_ai", "outcome": "wrong"},
                {"expected": "ai", "ai_label": "likely_not_ai", "outcome": "wrong"},
                {"expected": "real", "ai_label": "uncertain", "outcome": "abstained"},
                {"expected": "ai", "ai_label": "likely_ai", "outcome": "correct"},
                {"expected": "real", "ai_label": "not_run", "outcome": "missing_local_file"},
            ]
        )
        self.assertEqual(metrics["manifest_total"], 5)
        self.assertEqual(metrics["total"], 4)
        self.assertEqual(metrics["not_evaluated"], 1)
        self.assertEqual(metrics["false_positive_real_as_ai"], 1)
        self.assertEqual(metrics["false_negative_ai_as_real"], 1)
        self.assertEqual(metrics["real_abstentions"], 1)

    def test_api_factcheck_image_endpoint_returns_image_analysis(self):
        client = TestClient(api_app)
        response = client.post(
            "/factcheck-image",
            data={"analysis_type": "ai_image"},
            files={"image_file": ("generated.png", _png_bytes({"Software": "Stable Diffusion"}), "image/png")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["image_analysis"]["mode"], "ai_image_detection")
        self.assertEqual(payload["image_analysis"]["ai_label"], "likely_ai")

    def test_api_factcheck_image_rejects_unknown_analysis_type(self):
        client = TestClient(api_app)
        response = client.post(
            "/factcheck-image",
            data={"analysis_type": "unknown"},
            files={"image_file": ("image.png", _png_bytes(), "image/png")},
        )
        self.assertEqual(response.status_code, 400)

    def test_claim_prior_blocks_uncertainty_markers(self):
        self.assertTrue(has_uncertainty_markers("An anonymous post claims a secret law was signed, but no sources are provided."))
        self.assertFalse(has_uncertainty_markers("The United States has the highest corporate tax rate in the free world."))

    def test_query_builder_uses_all_targeted_domains_and_fact_check_query(self):
        claim = ClaimCandidate(
            raw_text="The United States has the highest corporate tax rate in the free world.",
            normalized_text="The United States has the highest corporate tax rate in the free world.",
            score=3.0,
            entities=["United States"],
        )
        config = _internal_factcheck_config()
        queries = build_queries(claim, config)
        self.assertTrue(any(query.endswith("site:politifact.com") for query in queries))
        self.assertTrue(any("fact check" in query for query in queries))
        self.assertFalse(any(query.endswith("site:reuters.com") for query in queries))

    def test_best_accuracy_query_builder_includes_trusted_news_domains(self):
        claim = ClaimCandidate(
            raw_text="Amy Coney Barrett was confirmed as US Supreme Court Justice on October 26, 2020.",
            normalized_text="Amy Coney Barrett was confirmed as US Supreme Court Justice on October 26, 2020.",
            score=3.2,
            entities=["Amy Coney Barrett"],
            dates=["2020"],
        )
        config = _internal_research_config()
        queries = build_queries(claim, config)
        self.assertTrue(any(query.endswith("site:reuters.com") for query in queries))
        self.assertTrue(any(query.endswith("site:apnews.com") for query in queries))
        self.assertTrue(any(query.endswith("site:bbc.com") for query in queries))

    def test_politifact_parser_extracts_explicit_verdict(self):
        html = """
        <html>
          <head><title>PolitiFact | Does the U.S. have the highest corporate tax rate in the free world?</title></head>
          <body>
            <article>
              <div class="m-statement__quote">The United States has "the highest corporate tax rate in the free world."</div>
              <p>Background paragraph.</p>
              <p><strong>Our ruling</strong></p>
              <p>Because his statement is accurate but needs clarification or additional information, we rate his claim Mostly True.</p>
            </article>
          </body>
        </html>
        """
        parsed = parse_page("https://www.politifact.com/factchecks/example", html)
        self.assertTrue(parsed["is_factcheck_article"])
        self.assertEqual(parsed["explicit_verdict"], "support")
        self.assertIn("Mostly True", parsed["ruling_text"])

    def test_fullfact_parser_extracts_claim_and_verdict(self):
        html = """
        <html>
          <head><title>Flu and Covid-19 statistics are being published in one report, but not added together - Full Fact</title></head>
          <body>
            <article>
              <div class="card-body">
                <p class="card-title">What was claimed</p>
                <p class="card-text">Covid-19 and influenza reports are being combined.</p>
              </div>
              <div class="card-body accent card-conclusion-body">
                <p class="card-title">Our verdict</p>
                <p class="card-text">This is correct, but it will have no effect on the numbers, which will still be shown separately in the document.</p>
              </div>
            </article>
          </body>
        </html>
        """
        parsed = parse_page("https://fullfact.org/health/flu-covid-phe-not-combined/", html)
        self.assertEqual(parsed["claim_text"], "Covid-19 and influenza reports are being combined.")
        self.assertEqual(parsed["explicit_verdict"], "support")

    def test_generic_factcheck_parser_reads_misrepresentation_titles(self):
        html = """
        <html>
          <head><title>Fact Check: Video Claiming To Show Iran Striking Israeli Nuclear Site Is From 2017 Blaze At Ukrainian Arms Depot</title></head>
          <body><article><h1>Fact Check: Video Claiming To Show Iran Striking Israeli Nuclear Site Is From 2017 Blaze At Ukrainian Arms Depot</h1></article></body>
        </html>
        """
        parsed = parse_page("https://newschecker.in/fact-check/example", html)
        self.assertTrue(parsed["is_factcheck_article"])
        self.assertEqual(parsed["explicit_verdict"], "refute")

    def test_text_fallback_parser_reads_factcheck_verdict_from_jina_text(self):
        parsed = parse_text_fallback(
            "https://factcheck.afp.com/doc.afp.com.99HR8G4",
            "Ukraine depot explosion misrepresented as Middle East conflict",
            "A video circulating online purportedly showing strikes on an Israeli nuclear facility is unrelated; it shows an explosion at a Ukrainian ammunition depot in 2017.",
        )
        self.assertTrue(parsed["is_factcheck_article"])
        self.assertEqual(parsed["explicit_verdict"], "refute")
        self.assertEqual(parsed["verdict_source"], "text_fallback_factcheck")

    def test_fast_nli_detects_zero_vs_strong_demand_contradiction(self):
        set_fast_mode(True)
        result = classify_claim_vs_evidence(
            "Nvidia has zero demand for AI data-center chips.",
            "Reuters reported strong demand for Nvidia AI data-center chips and revenue tied to AI infrastructure growth.",
        )
        self.assertEqual(result["label"], "refuted")

    def test_decision_blocks_weak_hard_verdict(self):
        claim = ClaimCandidate(raw_text="A claim", normalized_text="A claim", score=3.0)
        trace = FactCheckTrace()
        config = _internal_factcheck_config()
        evidence = [
            EvidenceItem(
                url="https://www.reuters.com/a",
                title="Reuters",
                stance="support",
                score=0.78,
                snippet="",
                passage="A claim was supported.",
                source_type="primary_news",
                source_trust=0.98,
                relevance=0.81,
                freshness=0.9,
                domain="reuters.com",
            )
        ]
        decision = decide_claim(claim, evidence, trace, config)
        self.assertEqual(decision.verdict, "uncertain")

    def test_decision_allows_explicit_factcheck_override(self):
        claim = ClaimCandidate(raw_text="A claim", normalized_text="A claim", score=3.0)
        trace = FactCheckTrace()
        config = _internal_factcheck_config()
        evidence = [
            EvidenceItem(
                url="https://www.politifact.com/a",
                title="PolitiFact",
                stance="refute",
                score=0.84,
                snippet="",
                passage="Our ruling: the claim is false.",
                source_type="factcheck_org",
                source_trust=0.95,
                relevance=0.88,
                freshness=0.9,
                domain="politifact.com",
                is_factcheck_article=True,
                explicit_verdict="refute",
                verdict_source="politifact_ruling",
                claim_match_score=0.82,
            )
        ]
        decision = decide_claim(claim, evidence, trace, config)
        self.assertEqual(decision.verdict, "fake")

    def test_factcheck_only_blocks_conflicting_explicit_verdicts(self):
        claim = ClaimCandidate(raw_text="A claim", normalized_text="A claim", score=3.0)
        trace = FactCheckTrace()
        config = _internal_factcheck_config()
        evidence = [
            EvidenceItem(
                url="https://www.politifact.com/a",
                title="PolitiFact",
                stance="support",
                score=0.84,
                snippet="",
                passage="The claim is mostly true.",
                source_type="factcheck_org",
                source_trust=0.95,
                relevance=0.88,
                freshness=0.9,
                domain="politifact.com",
                is_factcheck_article=True,
                explicit_verdict="support",
                verdict_source="politifact_ruling",
                claim_match_score=0.82,
            ),
            EvidenceItem(
                url="https://www.leadstories.com/b",
                title="Lead Stories",
                stance="refute",
                score=0.83,
                snippet="",
                passage="The claim is not true.",
                source_type="factcheck_org",
                source_trust=0.91,
                relevance=0.86,
                freshness=0.9,
                domain="leadstories.com",
                is_factcheck_article=True,
                explicit_verdict="refute",
                verdict_source="generic_factcheck",
                claim_match_score=0.78,
            ),
        ]
        decision = decide_claim(claim, evidence, trace, config)
        self.assertEqual(decision.verdict, "uncertain")
        self.assertIn("conflicting_explicit_factcheck_verdicts", trace.fallbacks_used)

    def test_factcheck_only_returns_uncertain_without_explicit_verdict(self):
        claim = ClaimCandidate(raw_text="A claim", normalized_text="A claim", score=3.0)
        trace = FactCheckTrace()
        config = _internal_factcheck_config()
        evidence = [
            EvidenceItem(
                url="https://www.reuters.com/a",
                title="Reuters",
                stance="support",
                score=0.82,
                snippet="",
                passage="Evidence one.",
                source_type="primary_news",
                source_trust=0.98,
                relevance=0.81,
                freshness=0.9,
                domain="reuters.com",
            )
        ]
        decision = decide_claim(claim, evidence, trace, config)
        self.assertEqual(decision.verdict, "uncertain")
        self.assertIn("no_explicit_factcheck_verdict", trace.fallbacks_used)

    def test_factcheck_only_accepts_explicit_verdict_without_parser_source_name(self):
        claim = ClaimCandidate(raw_text="A claim", normalized_text="A claim", score=3.0)
        trace = FactCheckTrace()
        config = _internal_factcheck_config()
        evidence = [
            EvidenceItem(
                url="https://www.politifact.com/a",
                title="PolitiFact",
                stance="refute",
                score=0.84,
                snippet="",
                passage="The checked claim is false.",
                source_type="factcheck_org",
                source_trust=0.95,
                relevance=0.88,
                freshness=0.9,
                domain="politifact.com",
                is_factcheck_article=True,
                explicit_verdict="refute",
                claim_match_score=0.82,
            )
        ]
        decision = decide_claim(claim, evidence, trace, config)
        self.assertEqual(decision.verdict, "fake")

    @patch("factcheck.decision.select_safe_prior_prediction")
    def test_decision_does_not_use_prior_on_neutral_only_evidence(self, mock_prior):
        mock_prior.return_value = SimpleNamespace(label="fake", confidence=0.9, margin=0.8)
        claim = ClaimCandidate(raw_text="A claim", normalized_text="A claim", score=3.0)
        trace = FactCheckTrace()
        config = _internal_factcheck_config()
        evidence = [
            EvidenceItem(
                url="https://www.politifact.com/a",
                title="PolitiFact",
                stance="neutral",
                score=0.84,
                snippet="",
                passage="No decisive evidence.",
                source_type="factcheck_org",
                source_trust=0.95,
                relevance=0.62,
                freshness=0.9,
                domain="politifact.com",
                is_factcheck_article=True,
                claim_match_score=0.45,
            )
        ]
        decision = decide_claim(claim, evidence, trace, config)
        self.assertEqual(decision.verdict, "uncertain")
        mock_prior.assert_not_called()

    @patch("factcheck.evidence.classify_claim_vs_evidence")
    def test_evidence_inverts_explicit_verdict_when_page_claim_is_opposite(self, mock_nli):
        mock_nli.side_effect = [
            {"label": "refuted", "score": 0.98},
        ]
        claim = ClaimCandidate(
            raw_text="Wearing face masks will stop the spread of covid 19",
            normalized_text="Wearing face masks will stop the spread of covid 19",
            score=3.1,
        )
        document = RetrievedDocument(
            query="masks",
            url="https://www.politifact.com/factchecks/example",
            canonical_url="https://www.politifact.com/factchecks/example",
            title="PolitiFact | Contrary to Good, masks have been shown to limit COVID spread",
            snippet="",
            content="Masks have been shown to limit COVID spread.",
            source_url="https://www.politifact.com/factchecks/example",
            source_type="factcheck_org",
            source_trust=0.95,
            domain="politifact.com",
            retrieval_score=0.91,
            fetch_source="direct",
            is_factcheck_article=True,
            explicit_verdict="refute",
            verdict_source="politifact_ruling",
            claim_text="Wearing masks has not been demonstrated to make a significant impact in preventing the spread of COVID.",
            ruling_text="The experts cited do not support that claim and masks limit spread.",
            claim_match_score=0.62,
        )
        evidence = score_evidence_for_claim(claim, [document], FactCheckTrace(), _internal_factcheck_config())
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].stance, "support")
        mock_nli.assert_not_called()

    @patch("factcheck.evidence.classify_claim_vs_evidence")
    def test_factcheck_only_drops_low_match_explicit_pages(self, mock_nli):
        claim = ClaimCandidate(
            raw_text="A totally new unverified claim with no known fact check page",
            normalized_text="A totally new unverified claim with no known fact check page",
            score=2.4,
        )
        document = RetrievedDocument(
            query="new claim",
            url="https://www.politifact.com/factchecks/unrelated",
            canonical_url="https://www.politifact.com/factchecks/unrelated",
            title="PolitiFact | Unrelated claim",
            snippet="",
            content="An unrelated fact check.",
            source_url="https://www.politifact.com/factchecks/unrelated",
            source_type="factcheck_org",
            source_trust=0.95,
            domain="politifact.com",
            retrieval_score=0.7,
            fetch_source="direct",
            is_factcheck_article=True,
            explicit_verdict="refute",
            verdict_source="politifact_ruling",
            claim_text="A different viral post made an unrelated claim.",
            ruling_text="The unrelated claim is false.",
            claim_match_score=0.24,
        )
        evidence = score_evidence_for_claim(claim, [document], FactCheckTrace(), _internal_factcheck_config())
        self.assertEqual(evidence, [])
        mock_nli.assert_not_called()

    @patch("factcheck.evidence.classify_claim_vs_evidence")
    def test_generic_news_requires_title_alignment_for_hard_stance(self, mock_nli):
        mock_nli.side_effect = [
            {"label": "refuted", "score": 0.94},
            {"label": "neutral", "score": 0.97},
        ]
        claim = ClaimCandidate(
            raw_text="Wearing face masks will stop the spread of covid 19",
            normalized_text="Wearing face masks will stop the spread of covid 19",
            score=3.1,
        )
        document = RetrievedDocument(
            query="masks",
            url="https://www.bbc.co.uk/news/example",
            canonical_url="https://www.bbc.co.uk/news/example",
            title="Covid-19: Men fined for not wearing face masks in Aldi",
            snippet="",
            content="Two men were fined for not wearing face masks in Aldi during Covid-19 restrictions.",
            source_url="https://www.bbc.co.uk/news/example",
            source_type="major_news",
            source_trust=0.86,
            domain="bbc.co.uk",
            retrieval_score=0.71,
            fetch_source="direct",
            claim_match_score=0.71,
        )
        evidence = score_evidence_for_claim(claim, [document], FactCheckTrace(), _internal_research_config())
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].stance, "neutral")

    def test_decision_emits_hard_verdict_with_independent_sources(self):
        claim = ClaimCandidate(raw_text="A claim", normalized_text="A claim", score=3.0)
        trace = FactCheckTrace()
        config = _internal_research_config()
        evidence = [
            EvidenceItem(
                url="https://www.reuters.com/a",
                title="Reuters",
                stance="support",
                score=0.82,
                snippet="",
                passage="Evidence one.",
                source_type="primary_news",
                source_trust=0.98,
                relevance=0.81,
                freshness=0.9,
                domain="reuters.com",
            ),
            EvidenceItem(
                url="https://www.factcheck.org/b",
                title="FactCheck",
                stance="support",
                score=0.79,
                snippet="",
                passage="Evidence two.",
                source_type="factcheck_org",
                source_trust=0.97,
                relevance=0.78,
                freshness=0.9,
                domain="factcheck.org",
            ),
        ]
        decision = decide_claim(claim, evidence, trace, config)
        self.assertEqual(decision.verdict, "true")

    def test_summary_lists_only_verdict_relevant_sources(self):
        claim = ClaimCandidate(raw_text="A claim", normalized_text="A claim", score=3.0)
        trace = FactCheckTrace()
        config = _internal_research_config()
        result = finalize_result(
            [
                ClaimDecision(
                    claim=claim,
                    verdict="true",
                    confidence=0.72,
                    support_score=0.82,
                    refute_score=0.0,
                    neutral_score=0.8,
                    independent_sources=1,
                    trusted_hits=1,
                    evidence=[
                        EvidenceItem(
                            url="https://www.reuters.com/a",
                            title="Reuters",
                            stance="support",
                            score=0.82,
                            snippet="",
                            passage="Evidence one.",
                            source_type="primary_news",
                            source_trust=0.98,
                            relevance=0.81,
                            freshness=0.9,
                            domain="reuters.com",
                        ),
                        EvidenceItem(
                            url="https://www.bbc.co.uk/a",
                            title="BBC",
                            stance="neutral",
                            score=0.8,
                            snippet="",
                            passage="Related background.",
                            source_type="major_news",
                            source_trust=0.86,
                            relevance=0.74,
                            freshness=0.9,
                            domain="bbc.co.uk",
                        ),
                    ],
                )
            ],
            trace=trace,
            config=config,
        )
        self.assertIn("reuters.com supports", result.summary)
        self.assertNotIn("bbc.co.uk supports", result.summary)

    @patch("factcheck.service.fetch_url_text")
    def test_best_pipeline_factcheck_url_uses_explicit_verdict(self, mock_fetch):
        mock_fetch.return_value = {
            "text": "Claim: A viral post says masks do not protect people. Our ruling: False.",
            "title": "PolitiFact | Mask claim is false",
            "url": "https://www.politifact.com/factchecks/example/mask-claim",
            "fetch_source": "direct",
            "claim_text": "A viral post says masks do not protect people.",
            "ruling_text": "The viral post says masks do not protect people. Our ruling: False.",
            "explicit_verdict": "refute",
            "explicit_verdict_label": "False",
            "verdict_source": "politifact_ruling",
            "is_factcheck_article": True,
            "published_at": "2020-05-21T10:00:00Z",
            "author": "PolitiFact",
            "canonical_article_url": "https://www.politifact.com/factchecks/example/mask-claim",
        }
        payload = run_factcheck(url="https://www.politifact.com/factchecks/example/mask-claim").to_public_dict()
        self.assertEqual(payload["trace"]["mode"], "best_accuracy")
        self.assertEqual(payload["verdict"], "fake")
        self.assertEqual(payload["evidence"][0]["source_type"], "factcheck_org")

    @patch("factcheck.service.fetch_url_text")
    def test_best_pipeline_trusted_newsroom_factcheck_url_uses_explicit_verdict(self, mock_fetch):
        mock_fetch.return_value = {
            "text": "",
            "title": "Ukraine depot blast video falsely implied show Iran striking Israeli nuclear site",
            "url": "https://www.reuters.com/fact-check/ukraine-depot-blast-video-falsely-implied-show-iran-striking-israeli-nuclear-2026-03-05",
            "fetch_source": "jina",
            "claim_text": "Ukraine depot blast video falsely implied show Iran striking Israeli nuclear site",
            "ruling_text": "",
            "explicit_verdict": "refute",
            "explicit_verdict_label": "falsely implied",
            "verdict_source": "text_fallback_factcheck",
            "is_factcheck_article": True,
            "published_at": "",
            "author": "",
            "canonical_article_url": "https://www.reuters.com/fact-check/ukraine-depot-blast-video-falsely-implied-show-iran-striking-israeli-nuclear-2026-03-05",
        }
        payload = run_factcheck(
            url="https://www.reuters.com/fact-check/ukraine-depot-blast-video-falsely-implied-show-iran-striking-israeli-nuclear-2026-03-05"
        ).to_public_dict()
        self.assertEqual(payload["verdict"], "fake")
        self.assertEqual(payload["evidence"][0]["source_type"], "primary_news")
        self.assertEqual(payload["evidence"][0]["verdict_source"], "text_fallback_factcheck")

    @patch("factcheck.news_credibility.search_web")
    @patch("factcheck.service.fetch_url_text")
    def test_best_pipeline_news_url_returns_credibility_payload(self, mock_fetch, mock_search):
        article_text = (
            "UN climate agency releases major report after record heat. "
            "The agency said global temperatures remained elevated and urged governments to improve preparedness. "
        ) * 10
        mock_fetch.return_value = {
            "text": article_text,
            "title": "UN climate agency releases major report after record heat",
            "url": "https://www.bbc.com/news/articles/c4g6nyvl29po",
            "fetch_source": "direct",
            "claim_text": "",
            "ruling_text": "",
            "explicit_verdict": "",
            "explicit_verdict_label": "",
            "verdict_source": "",
            "is_factcheck_article": False,
            "published_at": "2026-04-26T10:00:00Z",
            "author": "BBC News",
            "canonical_article_url": "https://www.bbc.com/news/articles/c4g6nyvl29po",
        }
        mock_search.return_value = [
            {
                "url": "https://www.reuters.com/world/climate-report-record-heat-2026-04-26/",
                "source_url": "https://www.reuters.com/world/climate-report-record-heat-2026-04-26/",
                "title": "UN climate agency releases major report after record heat",
                "snippet": "The UN climate agency released a major report after record heat.",
            },
            {
                "url": "https://apnews.com/article/climate-report-record-heat",
                "source_url": "https://apnews.com/article/climate-report-record-heat",
                "title": "UN climate agency releases report after record heat",
                "snippet": "The agency said global temperatures remained elevated.",
            },
        ]
        payload = run_factcheck(url="https://www.bbc.com/news/articles/c4g6nyvl29po").to_public_dict()
        self.assertEqual(payload["trace"]["mode"], "best_accuracy")
        self.assertEqual(payload["verdict"], "uncertain")
        self.assertIn("credibility", payload)
        self.assertIn(payload["credibility"]["label"], {"medium", "high"})
        self.assertEqual(len(payload["evidence"]), 2)

    def test_news_listing_url_returns_credibility_unknown_without_crash(self):
        payload = run_factcheck(url="https://www.bbc.com/news").to_public_dict()
        self.assertEqual(payload["trace"]["mode"], "best_accuracy")
        self.assertEqual(payload["verdict"], "uncertain")
        self.assertIn("credibility", payload)
        self.assertIn(payload["credibility"]["label"], {"unknown", "low"})
        self.assertIn("non_article_input_url", payload["trace"]["fallbacks_used"])

    @patch("factcheck.service.retrieve_documents")
    @patch("factcheck.service.score_evidence_for_claim")
    @patch("factcheck.service.extract_claims")
    def test_service_contract(self, mock_extract_claims, mock_score_evidence, mock_retrieve_documents):
        claim = ClaimCandidate(raw_text="A claim", normalized_text="A claim", score=3.0)
        mock_extract_claims.return_value = [claim]
        mock_retrieve_documents.return_value = []
        mock_score_evidence.return_value = [
            EvidenceItem(
                url="https://www.factcheck.org/b",
                title="FactCheck",
                stance="support",
                score=0.84,
                snippet="",
                passage="The claim is true.",
                source_type="factcheck_org",
                source_trust=0.97,
                relevance=0.78,
                freshness=0.9,
                domain="factcheck.org",
                is_factcheck_article=True,
                explicit_verdict="support",
                verdict_source="generic_factcheck",
                claim_match_score=0.82,
            ),
        ]
        payload = run_factcheck(text="A claim").to_public_dict()
        self.assertEqual(payload["verdict"], "true")
        self.assertEqual(payload["trace"]["mode"], "best_accuracy")
        self.assertIn("claim", payload)
        self.assertIn("evidence", payload)
        self.assertIn("trace", payload)

    @patch("factcheck.service.retrieve_documents")
    @patch("factcheck.service.score_evidence_for_claim")
    @patch("factcheck.service.extract_claims")
    def test_service_uses_trusted_research_after_factcheck_miss(
        self,
        mock_extract_claims,
        mock_score_evidence,
        mock_retrieve_documents,
    ):
        claim = ClaimCandidate(raw_text="A claim", normalized_text="A claim", score=3.0)
        mock_extract_claims.return_value = [claim]
        mock_retrieve_documents.side_effect = [[], []]
        mock_score_evidence.side_effect = [
            [],
            [
                EvidenceItem(
                    url="https://www.reuters.com/a",
                    title="Reuters",
                    stance="support",
                    score=0.82,
                    snippet="",
                    passage="Evidence one supports the claim.",
                    source_type="primary_news",
                    source_trust=0.98,
                    relevance=0.86,
                    freshness=0.9,
                    domain="reuters.com",
                    claim_match_score=0.82,
                ),
                EvidenceItem(
                    url="https://apnews.com/a",
                    title="AP",
                    stance="support",
                    score=0.80,
                    snippet="",
                    passage="Evidence two supports the claim.",
                    source_type="primary_news",
                    source_trust=0.96,
                    relevance=0.84,
                    freshness=0.9,
                    domain="apnews.com",
                    claim_match_score=0.80,
                ),
            ],
        ]
        payload = run_factcheck(text="A claim").to_public_dict()
        self.assertEqual(payload["verdict"], "true")
        self.assertIn("trusted_research_after_factcheck_uncertain", payload["trace"]["fallbacks_used"])
        self.assertIn("trusted_research_fallback_used", payload["trace"]["fallbacks_used"])

    @patch("factcheck.service.retrieve_documents")
    def test_service_skips_retrieval_for_low_specificity_meta_claim(self, mock_retrieve_documents):
        payload = run_factcheck(
            text="The claim has no reliable source and cannot be verified yet.",
        ).to_public_dict()
        self.assertEqual(payload["verdict"], "uncertain")
        self.assertEqual(payload["evidence"], [])
        self.assertIn("low_specificity_meta_claim", payload["trace"]["fallbacks_used"])
        mock_retrieve_documents.assert_not_called()

    def test_best_pipeline_handles_simple_true_claim(self):
        payload = run_factcheck(text="Cucumber is green and is eatable").to_public_dict()
        self.assertEqual(payload["verdict"], "true")
        self.assertEqual(payload["trace"]["mode"], "best_accuracy")
        self.assertEqual(payload["evidence"][0]["source_type"], "common_knowledge")

    def test_best_pipeline_handles_simple_false_claim(self):
        payload = run_factcheck(text="Grass is purple and is dangerous").to_public_dict()
        self.assertEqual(payload["verdict"], "fake")
        self.assertEqual(payload["trace"]["mode"], "best_accuracy")
        self.assertIn("common_knowledge_refutes", " ".join(payload["claims"][0]["reasons"]))

    def test_best_pipeline_handles_elephant_mammal_and_insect_claims(self):
        mammal_payload = run_factcheck(text="Elephants are mammals.").to_public_dict()
        self.assertEqual(mammal_payload["verdict"], "true")
        self.assertEqual(mammal_payload["evidence"][0]["source_type"], "common_knowledge")

        insect_payload = run_factcheck(text="Elephants are insects.").to_public_dict()
        self.assertEqual(insect_payload["verdict"], "fake")
        self.assertEqual(insect_payload["evidence"][0]["source_type"], "common_knowledge")

    def test_best_pipeline_handles_common_material_claims(self):
        paper_payload = run_factcheck(text="Books are made out of paper").to_public_dict()
        self.assertEqual(paper_payload["verdict"], "true")
        self.assertEqual(paper_payload["evidence"][0]["source_type"], "common_knowledge")
        self.assertIn("common_knowledge_supports", " ".join(paper_payload["claims"][0]["reasons"]))

    def test_best_pipeline_handles_capital_and_orbit_claims(self):
        capital_true = run_factcheck(text="The capital of France is Paris.").to_public_dict()
        self.assertEqual(capital_true["verdict"], "true")
        self.assertEqual(capital_true["evidence"][0]["source_type"], "common_knowledge")

        capital_false = run_factcheck(text="The capital of France is Berlin.").to_public_dict()
        self.assertEqual(capital_false["verdict"], "fake")
        self.assertEqual(capital_false["evidence"][0]["source_type"], "common_knowledge")

        usa_capital_true = run_factcheck(text="The capital of USA is Washington DC.").to_public_dict()
        self.assertEqual(usa_capital_true["verdict"], "true")
        self.assertEqual(usa_capital_true["evidence"][0]["source_type"], "common_knowledge")

        usa_capital_false = run_factcheck(text="The capital of the U.S. is New York.").to_public_dict()
        self.assertEqual(usa_capital_false["verdict"], "fake")
        self.assertEqual(usa_capital_false["evidence"][0]["source_type"], "common_knowledge")

        orbit_true = run_factcheck(text="Earth orbits the Sun.").to_public_dict()
        self.assertEqual(orbit_true["verdict"], "true")
        self.assertEqual(orbit_true["evidence"][0]["source_type"], "common_knowledge")

    def test_best_pipeline_handles_simple_taste_claims(self):
        salt_payload = run_factcheck(text="Salt is sweet").to_public_dict()
        self.assertEqual(salt_payload["verdict"], "fake")
        self.assertEqual(salt_payload["evidence"][0]["source_type"], "common_knowledge")

        sugar_payload = run_factcheck(text="Sugar is sweet").to_public_dict()
        self.assertEqual(sugar_payload["verdict"], "true")
        self.assertEqual(sugar_payload["evidence"][0]["source_type"], "common_knowledge")

    @patch("factcheck.service.retrieve_documents")
    def test_best_pipeline_uses_official_current_office_for_us_president(self, mock_retrieve_documents):
        examples = [
            "Donald Trump is president",
            "Donald Trump is the president",
            "Donald Trump is president of the United States",
            "Donald Trump is president of the United States.",
            "Donald Trump is the U.S. president",
            "President Trump is the president",
        ]
        for text in examples:
            with self.subTest(text=text):
                payload = run_factcheck(text=text).to_public_dict()
                self.assertEqual(payload["verdict"], "true")
                self.assertEqual(payload["confidence"], 0.94)
                self.assertEqual(payload["evidence"][0]["source_type"], "official_government")
                self.assertEqual(payload["evidence"][0]["domain"], "whitehouse.gov")
                self.assertIn("current_office", " ".join(payload["claims"][0]["reasons"]))
        mock_retrieve_documents.assert_not_called()

    @patch("factcheck.service.retrieve_documents")
    def test_best_pipeline_refutes_non_current_us_president_claim(self, mock_retrieve_documents):
        payload = run_factcheck(text="Joe Biden is president of the United States.").to_public_dict()
        self.assertEqual(payload["verdict"], "fake")
        self.assertEqual(payload["evidence"][0]["source_type"], "official_government")
        self.assertEqual(payload["evidence"][0]["domain"], "whitehouse.gov")
        mock_retrieve_documents.assert_not_called()

    @patch("factcheck.service.retrieve_documents")
    def test_best_pipeline_supports_negated_non_current_us_president_claim(self, mock_retrieve_documents):
        payload = run_factcheck(text="Joe Biden is not president").to_public_dict()
        self.assertEqual(payload["verdict"], "true")
        self.assertEqual(payload["evidence"][0]["source_type"], "official_government")
        self.assertEqual(payload["evidence"][0]["domain"], "whitehouse.gov")
        mock_retrieve_documents.assert_not_called()

    @patch("factcheck.service.retrieve_documents")
    def test_best_pipeline_uses_official_current_office_for_uk_prime_minister(self, mock_retrieve_documents):
        payload = run_factcheck(text="Keir Starmer is Prime Minister of the United Kingdom").to_public_dict()
        self.assertEqual(payload["verdict"], "true")
        self.assertEqual(payload["confidence"], 0.94)
        self.assertEqual(payload["evidence"][0]["source_type"], "official_government")
        self.assertEqual(payload["evidence"][0]["domain"], "gov.uk")
        self.assertIn("current_office_role=uk_prime_minister", payload["claims"][0]["reasons"])
        mock_retrieve_documents.assert_not_called()

    @patch("factcheck.service.retrieve_documents")
    def test_best_pipeline_handles_ocr_noise_in_prime_minister_title(self, mock_retrieve_documents):
        payload = run_factcheck(text="Keir Starmer is Prime eMinister of the United Kingdom").to_public_dict()
        self.assertEqual(payload["verdict"], "true")
        self.assertEqual(payload["evidence"][0]["source_type"], "official_government")
        self.assertEqual(payload["evidence"][0]["domain"], "gov.uk")
        mock_retrieve_documents.assert_not_called()

    @patch("factcheck.service.retrieve_documents")
    def test_best_pipeline_refutes_non_current_uk_prime_minister_claim(self, mock_retrieve_documents):
        payload = run_factcheck(text="Rishi Sunak is Prime Minister of the United Kingdom").to_public_dict()
        self.assertEqual(payload["verdict"], "fake")
        self.assertEqual(payload["evidence"][0]["source_type"], "official_government")
        self.assertEqual(payload["evidence"][0]["domain"], "gov.uk")
        mock_retrieve_documents.assert_not_called()

    @patch("factcheck.service.retrieve_documents")
    def test_best_pipeline_uses_official_current_office_for_fed_chair(self, mock_retrieve_documents):
        with patch("factcheck.common_knowledge.date", _fixed_date_class(2026, 5, 8)):
            payload = run_factcheck(text="Jerome Powell is chair of the Federal Reserve").to_public_dict()
        self.assertEqual(payload["verdict"], "true")
        self.assertEqual(payload["confidence"], 0.94)
        self.assertEqual(payload["evidence"][0]["source_type"], "official_government")
        self.assertEqual(payload["evidence"][0]["domain"], "federalreserve.gov")
        self.assertIn("current_office_role=federal_reserve_chair", payload["claims"][0]["reasons"])
        mock_retrieve_documents.assert_not_called()

    @patch("factcheck.service.retrieve_documents")
    def test_best_pipeline_refutes_non_current_fed_chair_claim(self, mock_retrieve_documents):
        with patch("factcheck.common_knowledge.date", _fixed_date_class(2026, 5, 8)):
            payload = run_factcheck(text="Kevin Warsh is chair of the Federal Reserve").to_public_dict()
        self.assertEqual(payload["verdict"], "fake")
        self.assertEqual(payload["evidence"][0]["source_type"], "official_government")
        self.assertEqual(payload["evidence"][0]["domain"], "federalreserve.gov")
        mock_retrieve_documents.assert_not_called()

    @patch("factcheck.service.retrieve_documents")
    def test_best_pipeline_supports_fed_chair_pro_tempore_transition(self, mock_retrieve_documents):
        with patch("factcheck.common_knowledge.date", _fixed_date_class(2026, 5, 16)):
            payload = run_factcheck(text="Jerome Powell is chair pro tempore of the Federal Reserve").to_public_dict()
        self.assertEqual(payload["verdict"], "true")
        self.assertEqual(payload["confidence"], 0.94)
        self.assertEqual(payload["evidence"][0]["source_type"], "official_government")
        self.assertEqual(payload["evidence"][0]["domain"], "federalreserve.gov")
        self.assertIn("current_office_role=federal_reserve_chair", payload["claims"][0]["reasons"])
        mock_retrieve_documents.assert_not_called()

    @patch("factcheck.service.retrieve_documents")
    def test_best_pipeline_refutes_pending_fed_chair_during_transition(self, mock_retrieve_documents):
        with patch("factcheck.common_knowledge.date", _fixed_date_class(2026, 5, 16)):
            payload = run_factcheck(text="Kevin Warsh is chair of the Federal Reserve").to_public_dict()
        self.assertEqual(payload["verdict"], "fake")
        self.assertEqual(payload["evidence"][0]["source_type"], "official_government")
        self.assertEqual(payload["evidence"][0]["domain"], "federalreserve.gov")
        mock_retrieve_documents.assert_not_called()

    @patch("factcheck.service.retrieve_documents")
    def test_best_pipeline_supports_official_artemis_ii_crew_member(self, mock_retrieve_documents):
        payload = run_factcheck(text="Artemis II crew includes Christina Koch").to_public_dict()
        self.assertEqual(payload["verdict"], "true")
        self.assertEqual(payload["confidence"], 0.94)
        self.assertEqual(payload["evidence"][0]["source_type"], "official_government")
        self.assertEqual(payload["evidence"][0]["domain"], "nasa.gov")
        self.assertIn("strategy=mission_crew", payload["claims"][0]["reasons"])
        mock_retrieve_documents.assert_not_called()

    @patch("factcheck.service.retrieve_documents")
    def test_best_pipeline_refutes_non_artemis_ii_crew_member(self, mock_retrieve_documents):
        payload = run_factcheck(text="Artemis II crew includes Elon Musk").to_public_dict()
        self.assertEqual(payload["verdict"], "fake")
        self.assertEqual(payload["evidence"][0]["source_type"], "official_government")
        self.assertEqual(payload["evidence"][0]["domain"], "nasa.gov")
        mock_retrieve_documents.assert_not_called()

    @patch("factcheck.common_knowledge.fetch_wikipedia_summary")
    def test_best_pipeline_uses_wikipedia_for_stable_fact_support(self, mock_summary):
        mock_summary.return_value = SimpleNamespace(
            title="Pangolin",
            extract="Pangolins are mammals of the order Pholidota.",
            url="https://en.wikipedia.org/wiki/Pangolin",
            source="wikipedia_summary_v1",
        )
        payload = run_factcheck(text="Pangolin is a mammal").to_public_dict()
        self.assertEqual(payload["verdict"], "true")
        self.assertEqual(payload["evidence"][0]["source_type"], "knowledge_source")
        self.assertEqual(payload["evidence"][0]["domain"], "wikipedia.org")

    @patch("factcheck.common_knowledge.fetch_wikipedia_summary")
    def test_best_pipeline_uses_wikipedia_to_refute_negated_stable_fact(self, mock_summary):
        mock_summary.return_value = SimpleNamespace(
            title="Pangolin",
            extract="Pangolins are mammals of the order Pholidota.",
            url="https://en.wikipedia.org/wiki/Pangolin",
            source="wikipedia_summary_v1",
        )
        payload = run_factcheck(text="Pangolin is not a mammal").to_public_dict()
        self.assertEqual(payload["verdict"], "fake")
        self.assertEqual(payload["evidence"][0]["source_type"], "knowledge_source")

    @patch("factcheck.common_knowledge.fetch_wikipedia_summary")
    def test_best_pipeline_uses_wikipedia_taxonomy_for_general_facts(self, mock_summary):
        summaries = {
            "mars": SimpleNamespace(
                title="Mars",
                extract="Mars is the fourth planet from the Sun. It is also known as the Red Planet.",
                url="https://en.wikipedia.org/wiki/Mars",
                source="wikipedia_summary_v1",
                categories=(),
            ),
            "spiders": SimpleNamespace(
                title="Spider",
                extract="Spiders are air-breathing arthropods. They are the largest order of arachnids.",
                url="https://en.wikipedia.org/wiki/Spider",
                source="wikipedia_summary_v1",
                categories=(),
            ),
            "whales": SimpleNamespace(
                title="Whale",
                extract="Whales are a widely distributed group of fully aquatic placental marine mammals.",
                url="https://en.wikipedia.org/wiki/Whale",
                source="wikipedia_summary_v1",
                categories=(),
            ),
            "paris": SimpleNamespace(
                title="Paris",
                extract="Paris is the capital and largest city of France, with an estimated city population of 2.04 million.",
                url="https://en.wikipedia.org/wiki/Paris",
                source="wikipedia_summary_v1",
                categories=(),
            ),
            "oxygen": SimpleNamespace(
                title="Oxygen",
                extract="Oxygen is a chemical element. It is highly reactive, a nonmetal, and is used in breathing gases.",
                url="https://en.wikipedia.org/wiki/Oxygen",
                source="wikipedia_summary_v1",
                categories=("Breathing gases",),
            ),
        }
        mock_summary.side_effect = lambda subject: summaries.get(subject.lower())

        cases = [
            ("Mars is a star", "fake", "taxonomy_refutes"),
            ("Spiders are animals", "true", "taxonomy_supports"),
            ("Spiders are insects", "fake", "taxonomy_refutes"),
            ("Whales are fish", "fake", "taxonomy_refutes"),
            ("Paris is the capital of Germany", "fake", "capital_relation_refutes"),
            ("Oxygen is a gas", "true", "wikipedia_summary_supports"),
            ("Oxygen is a metal", "fake", "taxonomy_refutes"),
        ]
        for text, expected_verdict, expected_reason in cases:
            with self.subTest(text=text):
                payload = run_factcheck(text=text).to_public_dict()
                self.assertEqual(payload["verdict"], expected_verdict)
                self.assertEqual(payload["evidence"][0]["source_type"], "knowledge_source")
                self.assertIn(expected_reason, " ".join(payload["claims"][0]["reasons"]))

    def test_best_pipeline_handles_false_numeric_comparison(self):
        payload = run_factcheck(text="15 is greater than 20").to_public_dict()
        self.assertEqual(payload["verdict"], "fake")
        self.assertEqual(payload["confidence"], 0.97)
        self.assertEqual(payload["evidence"][0]["source_type"], "local_arithmetic")

    def test_best_pipeline_handles_true_numeric_comparison(self):
        payload = run_factcheck(text="15 is less than 20").to_public_dict()
        self.assertEqual(payload["verdict"], "true")
        self.assertEqual(payload["evidence"][0]["source_type"], "local_arithmetic")

    def test_best_pipeline_handles_numeric_comparison_synonyms(self):
        payload = run_factcheck(text="100 is lower than 200").to_public_dict()
        self.assertEqual(payload["verdict"], "true")
        self.assertEqual(payload["evidence"][0]["source_type"], "local_arithmetic")

    def test_best_pipeline_handles_symbolic_numeric_comparison(self):
        payload = run_factcheck(text="20 >= 15").to_public_dict()
        self.assertEqual(payload["verdict"], "true")
        self.assertEqual(payload["evidence"][0]["source_type"], "local_arithmetic")

    def test_best_pipeline_handles_simple_arithmetic_equations(self):
        true_payload = run_factcheck(text="2 plus 2 equals 4").to_public_dict()
        self.assertEqual(true_payload["verdict"], "true")
        self.assertEqual(true_payload["evidence"][0]["source_type"], "local_arithmetic")

        fake_payload = run_factcheck(text="5 + 5 = 11").to_public_dict()
        self.assertEqual(fake_payload["verdict"], "fake")
        self.assertEqual(fake_payload["evidence"][0]["source_type"], "local_arithmetic")

    def test_best_pipeline_handles_word_number_arithmetic_and_comparison(self):
        true_payload = run_factcheck(text="Two plus two equals four").to_public_dict()
        self.assertEqual(true_payload["verdict"], "true")
        self.assertEqual(true_payload["confidence"], 0.97)
        self.assertEqual(true_payload["evidence"][0]["source_type"], "local_arithmetic")

        fake_payload = run_factcheck(text="Ten divided by two equals three").to_public_dict()
        self.assertEqual(fake_payload["verdict"], "fake")
        self.assertEqual(fake_payload["evidence"][0]["source_type"], "local_arithmetic")

        comparison_payload = run_factcheck(text="Five is greater than three").to_public_dict()
        self.assertEqual(comparison_payload["verdict"], "true")
        self.assertEqual(comparison_payload["evidence"][0]["source_type"], "local_arithmetic")

    def test_best_pipeline_handles_expanded_local_life_facts(self):
        apple_payload = run_factcheck(text="Apple is blue").to_public_dict()
        self.assertEqual(apple_payload["verdict"], "fake")
        self.assertEqual(apple_payload["evidence"][0]["source_type"], "common_knowledge")

        moon_payload = run_factcheck(text="The moon is made of cheese").to_public_dict()
        self.assertEqual(moon_payload["verdict"], "fake")
        self.assertEqual(moon_payload["evidence"][0]["source_type"], "common_knowledge")

        cat_payload = run_factcheck(text="Cats are plants").to_public_dict()
        self.assertEqual(cat_payload["verdict"], "fake")
        self.assertEqual(cat_payload["evidence"][0]["source_type"], "common_knowledge")

        with patch("factcheck.service.retrieve_documents") as mock_retrieve_documents:
            covid_virus_payload = run_factcheck(text="covid is virus").to_public_dict()
            self.assertEqual(covid_virus_payload["verdict"], "true")
            self.assertEqual(covid_virus_payload["evidence"][0]["source_type"], "official_health")
            self.assertEqual(covid_virus_payload["evidence"][0]["domain"], "who.int")
            self.assertIn("COVID-19 is the disease", covid_virus_payload["evidence"][0]["passage"])
            self.assertIn("health_terminology_supports", " ".join(covid_virus_payload["claims"][0]["reasons"]))

            covid_bacteria_payload = run_factcheck(text="covid is bacteria").to_public_dict()
            self.assertEqual(covid_bacteria_payload["verdict"], "fake")
            self.assertEqual(covid_bacteria_payload["evidence"][0]["source_type"], "official_health")

            covid_viral_cause_payload = run_factcheck(text="covid is caused by virus").to_public_dict()
            self.assertEqual(covid_viral_cause_payload["verdict"], "true")
            self.assertEqual(covid_viral_cause_payload["evidence"][0]["domain"], "who.int")

            covid_bacterial_cause_payload = run_factcheck(text="covid is caused by bacteria").to_public_dict()
            self.assertEqual(covid_bacterial_cause_payload["verdict"], "fake")
            self.assertEqual(covid_bacterial_cause_payload["evidence"][0]["domain"], "who.int")
            mock_retrieve_documents.assert_not_called()

    def test_best_pipeline_returns_no_exact_answer_for_local_unknown_property(self):
        payload = run_factcheck(text="Apple is expensive").to_public_dict()
        self.assertEqual(payload["verdict"], "uncertain")
        self.assertIn("knowledge_no_exact_answer", payload["trace"]["fallbacks_used"])
        self.assertIn("no_exact_answer", " ".join(payload["claims"][0]["reasons"]))

    @patch("factcheck.common_knowledge.fetch_wikipedia_summary")
    @patch("factcheck.service.retrieve_documents")
    def test_best_pipeline_simple_knowledge_abstains_when_source_missing(self, mock_retrieve_documents, mock_summary):
        mock_summary.return_value = None
        payload = run_factcheck(text="Zorbax is edible").to_public_dict()
        self.assertEqual(payload["verdict"], "uncertain")
        self.assertIn("knowledge_no_exact_answer", payload["trace"]["fallbacks_used"])
        mock_retrieve_documents.assert_not_called()

    @patch("factcheck.common_knowledge.fetch_wikipedia_summary")
    def test_best_pipeline_simple_knowledge_abstains_when_wikipedia_has_no_exact_answer(self, mock_summary):
        mock_summary.return_value = SimpleNamespace(
            title="Pangolin",
            extract="Pangolins are mammals of the order Pholidota.",
            url="https://en.wikipedia.org/wiki/Pangolin",
            source="wikipedia_summary_v1",
        )
        payload = run_factcheck(text="Pangolin is superconductive").to_public_dict()
        self.assertEqual(payload["verdict"], "uncertain")
        self.assertEqual(payload["evidence"][0]["source_type"], "knowledge_source")
        self.assertIn("knowledge_no_exact_answer", payload["trace"]["fallbacks_used"])

    @patch("factcheck.common_knowledge.fetch_wikipedia_summary")
    @patch("factcheck.service.retrieve_documents")
    def test_best_pipeline_abstains_on_unsupported_causal_life_claim(self, mock_retrieve_documents, mock_summary):
        mock_summary.return_value = SimpleNamespace(
            title="Coffee",
            extract="Coffee is a beverage prepared from roasted coffee beans.",
            url="https://en.wikipedia.org/wiki/Coffee",
            source="wikipedia_summary_v1",
        )
        payload = run_factcheck(text="Coffee cures cancer").to_public_dict()
        self.assertEqual(payload["verdict"], "uncertain")
        self.assertIn("No exact answer", payload["summary"])
        self.assertEqual(payload["evidence"][0]["source_type"], "knowledge_source")
        mock_retrieve_documents.assert_not_called()


if __name__ == "__main__":
    unittest.main()
