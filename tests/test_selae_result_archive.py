from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from scripts.discover_selae_result_archive import (
    ENGLISH_INDEX_URL,
    INDEX_URL,
    _is_official_url,
    build_component_page_url,
    discover_archive,
    extract_pagination_template,
    extract_result_links,
    probe_alternative_sources,
)


def test_result_link_parses_spanish_date_from_official_slug() -> None:
    document = """
    <a href="/es/la-quiniela/resultados/la-quiniela-resultados-del-23-de-noviembre-de-2025">
      23/11/2025 La Quiniela: resultados del 23 de noviembre de 2025
    </a>
    """

    links = extract_result_links(document)

    assert len(links) == 1
    assert links[0]["draw_date"] == "2025-11-23"
    assert links[0]["date_source"] == "slug"
    assert links[0]["slug_date_available"] is True
    assert links[0]["status"] == "dated_slug"


def test_english_result_link_parses_same_official_spanish_date_slug() -> None:
    document = """
    <a href="/en/la-quiniela/resultados/la-quiniela-resultados-del-26-de-abril-de-2026">
      27/04/2026 La Quiniela: results on 26 April 2026
    </a>
    """

    links = extract_result_links(document, base_url=ENGLISH_INDEX_URL)

    assert len(links) == 1
    assert links[0]["draw_date"] == "2026-04-26"
    assert links[0]["date_source"] == "slug"
    assert links[0]["status"] == "dated_slug"


def test_placeholder_slug_keeps_label_date_unverified() -> None:
    document = """
    <a href="/es/la-quiniela/resultados/la-quiniela-resultados-del-val-dia-semana-val-dia-de-val-mes-de-val-anyo">
      15/04/2011 La Quiniela: resultados del [VAL_DIA_SEMANA] [VAL_DIA]
    </a>
    """

    links = extract_result_links(document)

    assert len(links) == 1
    assert links[0]["draw_date"] == "2011-04-15"
    assert links[0]["date_source"] == "label_only"
    assert links[0]["slug_date_available"] is False
    assert links[0]["status"] == "label_date_only"


def test_invalid_or_missing_dates_are_not_invented() -> None:
    document = """
    <a href="/es/la-quiniela/resultados/la-quiniela-resultados-del-31-de-febrero-de-2025">
      La Quiniela: resultados
    </a>
    <a href="/es/la-quiniela/resultados/la-quiniela-resultados-del-val-dia">
      La Quiniela: resultados
    </a>
    """

    links = extract_result_links(document)

    assert len(links) == 2
    assert all(item["draw_date"] is None for item in links)
    assert all(item["date_source"] == "unresolved" for item in links)


def test_pagination_template_extracts_component_and_builds_page_url() -> None:
    document = """
    <a href="https://www.loteriasyapuestas.es/vgn-ext-templating/render/component?lang=es_ES&amp;page=1&amp;vgnextcomponentid=component&amp;vgnextdisplayincontextedit=false&amp;vgnextoid=oid&amp;vgnextxhr=true">2</a>
    <a href="https://www.loteriasyapuestas.es/vgn-ext-templating/render/component?lang=es_ES&amp;page=79&amp;vgnextcomponentid=component&amp;vgnextdisplayincontextedit=false&amp;vgnextoid=oid&amp;vgnextxhr=true">80</a>
    """

    template, maximum = extract_pagination_template(document)
    page_url = build_component_page_url(template, 2)

    assert maximum == 79
    assert parse_qs(urlsplit(page_url).query)["page"] == ["2"]
    assert "vgnextcomponentid=component" in page_url
    assert "vgnextoid=oid" in page_url


def test_pagination_rejects_external_or_incomplete_component_links() -> None:
    document = """
    <a href="https://example.com/vgn-ext-templating/render/component?page=79">80</a>
    <a href="https://www.loteriasyapuestas.es/vgn-ext-templating/render/component?page=1">2</a>
    """

    with pytest.raises(ValueError, match="no validated pagination links"):
        extract_pagination_template(document)


class _FakeResponse:
    def __init__(self, url: str, status_code: int) -> None:
        self.url = url
        self.status_code = status_code
        self.headers = {
            "Content-Type": "application/xml",
            "Server": "cloudflare",
            "CF-Ray": "test-ray-id",
            "CF-Cache-Status": "DYNAMIC",
            "Retry-After": "30",
        }
        self.content = b"<rss/>" if status_code == 200 else b"forbidden"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None


class _FakeSession:
    def get(self, url: str, **kwargs):
        status_code = 200 if ".formatoRSS" in url else 403
        return _FakeResponse(url, status_code)


def test_alternative_official_endpoints_are_probed_without_interpreting_payloads() -> (
    None
):
    results = probe_alternative_sources(_FakeSession())

    assert len(results) == 5
    assert results[0]["name"] == "results_rss_es"
    assert results[0]["accessible"] is True
    assert results[0]["sha256"]
    assert all(item["official_redirect"] for item in results)
    assert all(item["accessible"] is False for item in results[1:])


def test_component_page_builder_rejects_invalid_parameters_and_hosts() -> None:
    template = (
        "https://www.loteriasyapuestas.es/vgn-ext-templating/render/component"
        "?page=1&vgnextcomponentid=component&vgnextoid=oid"
    )

    with pytest.raises(ValueError, match="positive integer"):
        build_component_page_url(template, 0)

    with pytest.raises(ValueError, match="official HTTPS"):
        build_component_page_url(
            "https://example.com/vgn-ext-templating/render/component"
            "?page=1&vgnextcomponentid=component&vgnextoid=oid",
            2,
        )

    assert INDEX_URL.startswith("https://www.loteriasyapuestas.es/")


def test_official_url_requires_https_standard_port_and_no_userinfo() -> None:
    assert _is_official_url(INDEX_URL)
    assert not _is_official_url(INDEX_URL.replace("https://", "http://"))
    assert not _is_official_url(
        "https://www.loteriasyapuestas.es:8443/es/la-quiniela/resultados"
    )
    assert not _is_official_url(
        "https://user@www.loteriasyapuestas.es/es/la-quiniela/resultados"
    )
    assert not _is_official_url(
        "https://www.loteriasyapuestas.es.evil.example/es/la-quiniela/resultados"
    )


class _AllForbiddenSession:
    def get(self, url: str, **kwargs):
        return _FakeResponse(url, 403)


def test_archive_failure_preserves_safe_transport_diagnostics() -> None:
    report = discover_archive(_AllForbiddenSession())

    assert report["success"] is False
    first_attempt = report["index_attempts"][0]
    diagnostics = first_attempt["response_diagnostics"]
    assert diagnostics["http_status"] == 403
    assert diagnostics["server"] == "cloudflare"
    assert diagnostics["cf_ray"] == "test-ray-id"
    assert diagnostics["cf_cache_status"] == "DYNAMIC"
    assert diagnostics["retry_after"] == "30"

    rss_probe = report["alternative_source_probes"][0]
    assert rss_probe["http_status"] == 403
    assert rss_probe["cf_ray"] == "test-ray-id"
    assert rss_probe["sha256"]
    assert "body" not in rss_probe
