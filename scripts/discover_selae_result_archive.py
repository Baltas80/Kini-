from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

INDEX_URL = "https://www.loteriasyapuestas.es/es/la-quiniela/resultados"
ENGLISH_INDEX_URL = "https://www.loteriasyapuestas.es/en/la-quiniela/resultados"
INDEX_URLS = (INDEX_URL, ENGLISH_INDEX_URL)
OFFICIAL_HOSTS = {"www.loteriasyapuestas.es", "loteriasyapuestas.es"}
RESULT_PATH_MARKER = "/la-quiniela-resultados-del-"
COMPONENT_PATH = "/vgn-ext-templating/render/component"
MAX_HTML_BYTES = 5 * 1024 * 1024
TIMEOUT = (10, 30)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}
SPANISH_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
SLUG_DATE_RE = re.compile(
    r"la-quiniela-resultados-del-(\d{1,2})-de-([a-zñ]+)-de-(\d{4})",
    re.IGNORECASE,
)
LABEL_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
ALTERNATIVE_SOURCE_PROBES = (
    (
        "results_rss_es",
        "https://www.loteriasyapuestas.es/es/la-quiniela/resultados/.formatoRSS",
        "https://www.loteriasyapuestas.es/es/canales-rss",
        "application/rss+xml,application/xml,text/xml,*/*",
    ),
    (
        "static_result_file_20261108",
        "https://www.loteriasyapuestas.es/f/loterias/resultados/quiniela.html?game_id=LAQU&fecha_sorteo=20261108",
        "https://www.loteriasyapuestas.es/es/resultados-medios/resultados-ultimos-sorteos",
        "text/html,*/*",
    ),
    (
        "press_release_pdf_20261108",
        "https://www.loteriasyapuestas.es/f/loterias/documentos/Quiniela/Notas%20de%20prensa/NOTA_DE_PRENSA_LA_QUINIELA_08_11_26.pdf",
        "https://www.loteriasyapuestas.es/es/la-quiniela/resultados",
        "application/pdf,*/*",
    ),
    (
        "archive_component_page2_es",
        "https://www.loteriasyapuestas.es/vgn-ext-templating/render/component?lang=es_ES&page=1&vgnextcomponentid=480bbe14bb6e8310VgnVCM100000e044a8c0RCRD&vgnextdisplayincontextedit=false&vgnextoid=480b32fab11a9310VgnVCM100000e044a8c0RCRD&vgnextxhr=true",
        INDEX_URL,
        "text/html,*/*",
    ),
    (
        "archive_component_page2_en",
        "https://www.loteriasyapuestas.es/vgn-ext-templating/render/component?lang=en_GB&page=1&vgnextcomponentid=480bbe14bb6e8310VgnVCM100000e044a8c0RCRD&vgnextdisplayincontextedit=false&vgnextoid=480b32fab11a9310VgnVCM100000e044a8c0RCRD&vgnextxhr=true",
        ENGLISH_INDEX_URL,
        "text/html,*/*",
    ),
)


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict[str, str]] = []
        self._current: dict[str, str | list[str]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a" and self._current is None:
            values = dict(attrs)
            self._current = {
                "href": values.get("href") or "",
                "title": values.get("title") or "",
                "text_parts": [],
            }

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            parts = self._current["text_parts"]
            if isinstance(parts, list):
                parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._current is None:
            return
        parts = self._current.pop("text_parts")
        self.links.append(
            {
                "href": str(self._current.get("href", "")),
                "title": str(self._current.get("title", "")),
                "text": " ".join(str(part) for part in parts)
                if isinstance(parts, list)
                else "",
            }
        )
        self._current = None


def _is_official_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme == "https"
            and parsed.hostname in OFFICIAL_HOSTS
            and parsed.port in {None, 443}
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False


def _anchors(document: str) -> list[dict[str, str]]:
    parser = _AnchorParser()
    parser.feed(document)
    parser.close()
    return parser.links


def _date_from_link(path: str, label: str) -> tuple[str | None, str]:
    slug_match = SLUG_DATE_RE.search(path.lower())
    if slug_match:
        day, month_name, year = slug_match.groups()
        month = SPANISH_MONTHS.get(month_name.lower())
        if month is not None:
            try:
                return date(int(year), month, int(day)).isoformat(), "slug"
            except ValueError:
                pass

    label_match = LABEL_DATE_RE.search(label)
    if label_match:
        day, month, year = map(int, label_match.groups())
        try:
            return date(year, month, day).isoformat(), "label_only"
        except ValueError:
            pass

    return None, "unresolved"


def extract_result_links(
    document: str,
    base_url: str = INDEX_URL,
    archive_page: int | None = None,
) -> list[dict[str, object]]:
    """Extract official result-detail links without treating them as parsed draws."""
    results: list[dict[str, object]] = []
    for anchor in _anchors(document):
        href = anchor["href"].strip()
        if not href:
            continue
        resolved = urljoin(base_url, href)
        parsed = urlsplit(resolved)
        if RESULT_PATH_MARKER not in parsed.path.lower():
            continue
        if not _is_official_url(resolved):
            raise ValueError(f"non-official result link in SELAE archive: {resolved}")

        label = re.sub(r"\s+", " ", anchor["text"]).strip()
        if not label:
            label = re.sub(r"\s+", " ", anchor["title"]).strip()
        draw_date, date_source = _date_from_link(parsed.path, label)
        results.append(
            {
                "url": urlunsplit(
                    (parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")
                ),
                "label": label,
                "draw_date": draw_date,
                "date_source": date_source,
                "slug_date_available": date_source == "slug",
                "status": (
                    "dated_slug"
                    if date_source == "slug"
                    else "label_date_only"
                    if date_source == "label_only"
                    else "unresolved"
                ),
                "archive_page": archive_page,
            }
        )
    return results


def extract_pagination_template(
    document: str, base_url: str = INDEX_URL
) -> tuple[str, int]:
    """Return one validated component URL and the highest observed page parameter."""
    groups: dict[tuple[str, str, str], list[tuple[int, str]]] = {}
    for anchor in _anchors(document):
        href = anchor["href"].strip()
        if not href:
            continue
        resolved = urljoin(base_url, href)
        parsed = urlsplit(resolved)
        if parsed.path.rstrip("/") != COMPONENT_PATH:
            continue
        if not _is_official_url(resolved):
            continue

        query = parse_qs(parsed.query, keep_blank_values=True)
        page_values = query.get("page", [])
        component_ids = query.get("vgnextcomponentid", [])
        component_oids = query.get("vgnextoid", [])
        languages = query.get("lang", [""])
        if not page_values or not component_ids or not component_oids:
            continue
        try:
            page_value = int(page_values[0])
        except ValueError:
            continue
        if page_value < 1:
            continue

        key = (component_ids[0], component_oids[0], languages[0])
        groups.setdefault(key, []).append((page_value, resolved))

    if not groups:
        raise ValueError("SELAE results index exposes no validated pagination links")

    ranked = sorted(
        groups.items(),
        key=lambda item: len({page for page, _ in item[1]}),
        reverse=True,
    )
    if len(ranked) > 1:
        first_count = len({page for page, _ in ranked[0][1]})
        second_count = len({page for page, _ in ranked[1][1]})
        if first_count == second_count:
            raise ValueError(
                "SELAE results index exposes ambiguous pagination components"
            )

    rows = ranked[0][1]
    template_url = rows[0][1]
    max_page_parameter = max(page for page, _ in rows)
    return template_url, max_page_parameter


def build_component_page_url(template_url: str, page_parameter: int) -> str:
    if (
        isinstance(page_parameter, bool)
        or not isinstance(page_parameter, int)
        or page_parameter < 1
    ):
        raise ValueError("component page parameter must be a positive integer")
    if not _is_official_url(template_url):
        raise ValueError("pagination template must use an official HTTPS SELAE host")

    parsed = urlsplit(template_url)
    if parsed.path.rstrip("/") != COMPONENT_PATH:
        raise ValueError("pagination template has an unexpected path")
    query = parse_qs(parsed.query, keep_blank_values=True)
    if not query.get("vgnextcomponentid") or not query.get("vgnextoid"):
        raise ValueError("pagination template is missing component identifiers")
    query["page"] = [str(page_parameter)]
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query, doseq=True),
            "",
        )
    )


def _fetch_html(
    session: requests.Session,
    url: str,
    referer: str | None = None,
) -> tuple[str, dict[str, object]]:
    if not _is_official_url(url):
        raise ValueError(f"refusing to fetch non-official URL: {url}")

    request_headers = {"Referer": referer} if referer else None
    response = session.get(
        url,
        headers=request_headers,
        timeout=TIMEOUT,
        allow_redirects=True,
    )
    with response:
        if response.status_code != 200:
            raise requests.HTTPError(
                f"SELAE returned HTTP {response.status_code} for {url}",
                response=response,
            )
        if not _is_official_url(response.url):
            raise ValueError(f"SELAE redirected to a non-official URL: {response.url}")

        content_type = response.headers.get("Content-Type", "").lower()
        if "html" not in content_type:
            raise ValueError(
                f"SELAE returned non-HTML content type {content_type!r} for {url}"
            )
        payload = response.content
        if not payload:
            raise ValueError(f"SELAE returned an empty HTML response for {url}")
        if len(payload) > MAX_HTML_BYTES:
            raise ValueError(
                f"SELAE HTML response exceeds the {MAX_HTML_BYTES}-byte safety limit"
            )

        response.encoding = response.apparent_encoding or "utf-8"
        document = response.text
        metadata = {
            "requested_url": url,
            "final_url": response.url,
            "http_status": response.status_code,
            "content_type": response.headers.get("Content-Type"),
            "downloaded_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    return document, metadata


def probe_alternative_sources(session: requests.Session) -> list[dict[str, object]]:
    """Probe documented official result endpoints without interpreting their payloads."""
    results: list[dict[str, object]] = []
    for name, url, referer, accept in ALTERNATIVE_SOURCE_PROBES:
        try:
            response = session.get(
                url,
                headers={"Referer": referer, "Accept": accept},
                timeout=TIMEOUT,
                allow_redirects=True,
            )
            with response:
                payload = response.content
                final_url = response.url
                official_redirect = _is_official_url(final_url)
                results.append(
                    {
                        "name": name,
                        "url": url,
                        "final_url": final_url,
                        "http_status": response.status_code,
                        "content_type": response.headers.get("Content-Type"),
                        "downloaded_bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest()
                        if payload
                        else None,
                        "official_redirect": official_redirect,
                        "accessible": response.status_code == 200 and official_redirect,
                    }
                )
        except requests.RequestException as exc:
            results.append(
                {
                    "name": name,
                    "url": url,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "accessible": False,
                }
            )
    return results


def discover_archive(
    session: requests.Session,
    max_archive_page: int | None = None,
) -> dict[str, object]:
    """Discover the official archive index; do not fetch or infer draw outcomes."""
    index_attempts: list[dict[str, str]] = []
    selected_index_url: str | None = None
    index_html: str | None = None
    index_metadata: dict[str, object] | None = None
    for candidate_url in INDEX_URLS:
        referer = candidate_url.split("/la-quiniela/", maxsplit=1)[0] + "/"
        try:
            index_html, index_metadata = _fetch_html(
                session,
                candidate_url,
                referer=referer,
            )
            selected_index_url = candidate_url
            break
        except (requests.RequestException, ValueError) as exc:
            index_attempts.append(
                {
                    "url": candidate_url,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )

    if selected_index_url is None or index_html is None or index_metadata is None:
        failures = " | ".join(
            f"{item['url']}: {item['error']}" for item in index_attempts
        )
        return {
            "schema_version": 1,
            "success": False,
            "source": "SELAE",
            "index_url": None,
            "retrieved_at_utc": datetime.now(UTC).isoformat(),
            "index_attempts": index_attempts,
            "alternative_source_probes": probe_alternative_sources(session),
            "error": f"all official SELAE index routes failed: {failures}",
            "interpretation_status": (
                "no historical archive inventory produced; alternative endpoint "
                "probes are transport diagnostics only"
            ),
        }

    template_url, max_component_page = extract_pagination_template(
        index_html,
        base_url=selected_index_url,
    )
    available_pages = max_component_page + 1
    target_pages = available_pages if max_archive_page is None else max_archive_page
    if isinstance(target_pages, bool) or not isinstance(target_pages, int):
        raise TypeError("max_archive_page must be an integer")
    if target_pages < 1 or target_pages > available_pages:
        raise ValueError(f"max_archive_page must be between 1 and {available_pages}")

    page_summaries: list[dict[str, object]] = []
    links: list[dict[str, object]] = []
    for archive_page in range(1, target_pages + 1):
        if archive_page == 1:
            document = index_html
            metadata = index_metadata
            page_url = selected_index_url
        else:
            page_parameter = archive_page - 1
            page_url = build_component_page_url(template_url, page_parameter)
            document, metadata = _fetch_html(
                session,
                page_url,
                referer=selected_index_url,
            )

        page_links = extract_result_links(
            document,
            base_url=page_url,
            archive_page=archive_page,
        )
        if not page_links:
            raise ValueError(
                f"SELAE archive page {archive_page} contains no result-detail links"
            )

        dated = [
            str(item["draw_date"])
            for item in page_links
            if item["date_source"] == "slug" and item["draw_date"]
        ]
        page_summaries.append(
            {
                "archive_page": archive_page,
                "url": page_url,
                "result_link_count": len(page_links),
                "dated_slug_count": len(dated),
                "first_date": min(dated) if dated else None,
                "last_date": max(dated) if dated else None,
                **metadata,
            }
        )
        links.extend(page_links)

    unique_urls = {str(item["url"]) for item in links}
    slug_dates = sorted(
        {
            str(item["draw_date"])
            for item in links
            if item["date_source"] == "slug" and item["draw_date"]
        }
    )
    label_only_dates = sorted(
        {
            str(item["draw_date"])
            for item in links
            if item["date_source"] == "label_only" and item["draw_date"]
        }
    )
    return {
        "schema_version": 1,
        "success": True,
        "source": "SELAE",
        "index_url": selected_index_url,
        "index_attempts": index_attempts,
        "retrieved_at_utc": datetime.now(UTC).isoformat(),
        "archive_pages_available": available_pages,
        "archive_pages_fetched": target_pages,
        "result_link_count": len(links),
        "unique_result_url_count": len(unique_urls),
        "duplicate_result_url_count": len(links) - len(unique_urls),
        "dated_slug_count": sum(item["date_source"] == "slug" for item in links),
        "label_date_only_count": sum(
            item["date_source"] == "label_only" for item in links
        ),
        "unresolved_date_count": sum(
            item["date_source"] == "unresolved" for item in links
        ),
        "slug_date_range": (
            {"first": min(slug_dates), "last": max(slug_dates)} if slug_dates else None
        ),
        "label_only_date_range": (
            {"first": min(label_only_dates), "last": max(label_only_dates)}
            if label_only_dates
            else None
        ),
        "page_summaries": page_summaries,
        "links": links,
        "interpretation_status": (
            "official_archive_index_discovered; detail pages and fixture outcomes "
            "have not been fetched or parsed; not a historical scenario dataset"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Discover the paginated official SELAE Quiniela results archive "
            "without inferring draw IDs or fixture outcomes."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/selae-result-archive"),
    )
    parser.add_argument(
        "--max-archive-page",
        type=int,
        default=None,
        help="Optional maximum archive page to fetch; default fetches every discovered page.",
    )
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.output_dir / "archive_discovery.json"
    links_path = args.output_dir / "archive_draw_links.jsonl"

    retry = Retry(
        total=3,
        connect=3,
        read=2,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    try:
        with requests.Session() as session:
            session.headers.update(HEADERS)
            session.mount("https://", HTTPAdapter(max_retries=retry))
            report = discover_archive(session, args.max_archive_page)

        if not report.get("success"):
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
                + "\n",
                encoding="utf-8",
            )
            print(
                f"SELAE_ARCHIVE_DISCOVERY_BLOCKED: {report['error']}", file=sys.stderr
            )
            return 2

        links = report.pop("links")
        links_path.write_text(
            "".join(
                json.dumps(item, ensure_ascii=False, allow_nan=False) + "\n"
                for item in links
            ),
            encoding="utf-8",
        )
        report["links_file"] = links_path.name
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(
            "SELAE_ARCHIVE_DISCOVERY_OK "
            f"pages={report['archive_pages_fetched']}/"
            f"{report['archive_pages_available']} "
            f"links={report['result_link_count']} "
            f"dated_slug={report['dated_slug_count']} "
            f"unresolved={report['unresolved_date_count']}"
        )
        print(f"Report: {report_path}")
        return 0
    except (OSError, requests.RequestException, TypeError, ValueError) as exc:
        failure = {
            "schema_version": 1,
            "success": False,
            "source": "SELAE",
            "index_url": INDEX_URL,
            "retrieved_at_utc": datetime.now(UTC).isoformat(),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        report_path.write_text(
            json.dumps(failure, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"SELAE_ARCHIVE_DISCOVERY_ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
