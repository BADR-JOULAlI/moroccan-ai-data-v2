"""Offline catalogue -> human review fixture -> WARC -> real HTML pipeline.

HTTP replies and human decisions are test fixtures. WARC parsing, text
extraction, quality filters, token counting and MinHash run without stubs.
"""

from argparse import Namespace
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlparse

import httpx
import pandas as pd
import pytest
from tokenizers import Tokenizer, models, pre_tokenizers
from warcio.statusandheaders import StatusAndHeaders
from warcio.warcwriter import WARCWriter
import zstandard


CRAWLER = Path(__file__).resolve().parents[1]
REPOSITORY = CRAWLER.parents[1]
TEXTS = [
    "الثقافة المغربية كتجمع بين تاريخ المدن وتجارب الناس في القرى. الحرف التقليدية بحال الزليج والنسيج كتحتاج الصبر والمعرفة والتعاون بين المعلمين والتلاميذ. فكل منطقة كاينة طرق خاصة لصناعة الأدوات وتزيين البيوت والمحافظة على التراث المحلي. المتاحف والجمعيات كتنظم لقاءات باش الشباب يتعرفو على قصص الأجداد ويتعلمو مهارات جديدة. هاد المبادرات كتقرب المعرفة من العائلات وكتفتح نقاش على مستقبل الصناعة التقليدية في المغرب.",
    "الزراعة المستدامة كتعاون الفلاحين يستعملو الماء بطريقة معقولة ويحافظو على جودة التربة. فالمناطق الجبلية كيتبادلو السكان الخبرة حول أشجار الزيتون والفواكه الموسمية. التعاونيات كتجمع المنتجات وكتسهل النقل والتسويق في الأسواق القريبة. الباحثون كيدرسو تأثير الطقس وكيقدمو اقتراحات عملية لتحسين المحاصيل بدون إتلاف البيئة. التكوين المستمر والمراقبة المحلية كيساعدو الأسر تخطط للموسم وتواجه الصعوبات وتوفر غذاء متنوع للسكان.",
]


def read_jsonl_zstd(path):
    with path.open("rb") as raw, zstandard.ZstdDecompressor().stream_reader(raw) as decoded:
        return [json.loads(line) for line in decoded.read().decode("utf-8").splitlines() if line]


@pytest.mark.parametrize("workers", [1, 2])
def test_catalogue_to_deduplicated_html_corpus(tmp_path, monkeypatch, workers):
    monkeypatch.syspath_prepend(str(REPOSITORY / "moroccan_sources_collector"))
    from src import main
    from src.discovery import catalog_crawler
    from src.storage.jsonl_exporter import load_jsonl
    from src.validation.robots_checker import clear_robots_cache

    pages = [f'<html lang="ar"><body><article><h1>نص تجريبي محلي</h1><p>{text}</p></article></body></html>' for text in TEXTS]
    pages += [pages[0], "<html><body><p>tiny</p></body></html>"]
    urls = [f"https://fixture.example.test/page-{index}" for index in range(len(pages))]
    bodies = dict(zip(urls, pages))
    requests = []
    real_client = httpx.Client

    def handle(request):
        url = str(request.url)
        requests.append(url)
        if url == "https://fixture.example.test/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /blocked\n")
        assert url in bodies, f"Unexpected request outside local fixtures: {url}"
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=bodies[url])

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs))
    monkeypatch.setattr(catalog_crawler, "get_registered_domain", lambda url: urlparse(url).hostname)
    settings = {"max_depth": 0, "delay_between_requests_seconds": 0, "request_timeout_seconds": 1}
    monkeypatch.setattr(main, "load_yaml", lambda path: settings if path.name == "settings.yaml" else {})
    seeds = [{"name": "Local test source", "url": url, "category": "Darija"} for url in urls]
    seeds += [
        {"name": "Excluded fixture", "url": "https://youtube.com/watch?v=fixture"},
        {"name": "Robots fixture", "url": "https://fixture.example.test/blocked"},
    ]
    monkeypatch.setattr(main, "load_seed_sources", lambda *args: seeds)
    data = tmp_path / "collector"
    monkeypatch.setattr(main, "DATA", data)
    monkeypatch.setattr(main, "LOGS", data / "logs")
    paths = {
        "CANDIDATES_PATH": "intermediate/candidates.jsonl", "VERIFIED_PATH": "intermediate/verified.jsonl",
        "BLOCKED_PATH": "intermediate/blocked.jsonl", "REJECTED_LINGUISTIC_PATH": "intermediate/rejected.jsonl",
        "JSONL_PATH": "output/catalogue.jsonl", "CSV_PATH": "output/catalogue.csv",
        "XLSX_PATH": "output/catalogue.xlsx", "REVIEW_CSV_PATH": "output/review.csv",
    }
    for name, relative in paths.items():
        monkeypatch.setattr(main, name, data / relative)
    clear_robots_cache()
    try:
        summary = main.run_mvp_etl(Namespace(max_links=10, min_darija_density=0, force=True))
    finally:
        clear_robots_cache()
    assert summary["exported_records"] == 4
    assert not any("youtube.com" in url or url.endswith("/blocked") for url in requests)

    review = pd.read_csv(main.REVIEW_CSV_PATH, keep_default_na=False)
    review["Decision_validation"] = "accept"  # Simulated reviewer, fixture data only.
    review.to_csv(main.REVIEW_CSV_PATH, index=False, encoding="utf-8-sig")
    seeds_file = tmp_path / "urls.txt"
    manifest_file = tmp_path / "manifest.jsonl"
    exported = main.export_crawler_input_from_review(main.REVIEW_CSV_PATH, seeds_file, manifest_file)
    assert exported["accepted_links"] == 4
    accepted = seeds_file.read_text(encoding="utf-8").splitlines()
    assert {row["url"] for row in load_jsonl(manifest_file)} == set(urls)

    site = tmp_path / "input" / "fixture"
    site.mkdir(parents=True)
    with (site / "pages.warc.gz").open("wb") as raw:
        writer = WARCWriter(raw, gzip=True)
        for url in accepted:
            writer.write_record(writer.create_warc_record(
                url, "response", payload=BytesIO(bodies[url].encode("utf-8")),
                http_headers=StatusAndHeaders("200 OK", [("Content-Type", "text/html; charset=utf-8")], protocol="HTTP/1.1"),
            ))
    tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.save(str(tmp_path / "tokenizer.json"))
    config = {
        "mode": "html", "segment": "offline-fixture", "word_tokenizer": "unicode",
        "input_dir": "input", "output_dir": "dataset", "tokenizer_path": "tokenizer.json",
        "workers_io": workers, "workers_cpu": workers, "workers_heavy": workers,
    }
    configuration = tmp_path / "config.json"
    configuration.write_text(json.dumps(config), encoding="utf-8")
    env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    run = subprocess.run(
        [sys.executable, str(CRAWLER / "datatrove_extraction/process.py"), "--config", str(configuration), "--validate-warc"],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=90,
    )
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-4000:]
    assert "Pipeline completed successfully" in run.stdout
    assert "UnicodeDecodeError" not in run.stderr
    records = [
        row for path in (tmp_path / "dataset/final_data/html").glob("*.jsonl.zst")
        for row in read_jsonl_zstd(path)
    ]
    assert len(records) == 2
    assert len({row["text"] for row in records}) == 2
    assert all(row["metadata"]["segment"] == "offline-fixture" for row in records)
    assert all(row["metadata"]["token_count"] > 0 for row in records)
    assert all(row["media"][0]["url"] in urls for row in records)
    # Arabic character normalization is intentional; assert distinguishing
    # passages and the final words survive rather than expecting byte identity.
    for start, end in [
        ("الثقافة المغربية كتجمع بين تاريخ المدن", "الصناعة التقليدية في المغرب."),
        ("الزراعة المستدامة كتعاون الفلاحين", "وتوفر غذاء متنوع للسكان."),
    ]:
        assert any(start in row["text"] and end in row["text"] for row in records)
    stored = json.loads((tmp_path / "dataset/run_config.json").read_text(encoding="utf-8"))
    assert stored["word_tokenizer"] == "unicode"
