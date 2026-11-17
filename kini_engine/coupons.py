from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .core import SIGNS, KiniEngine, Match
from .team_identity import normalize_team_name

COUPON_SCHEMA_VERSION = 2
COUPON_BACKTEST_RESULT_SCHEMA_VERSION = 3
COUPON_SOURCE = "historicoquiniela.com"
SELAE_SOURCE = "loteriasyapuestas.es"
SPAIN_TIMEZONE = ZoneInfo("Europe/Madrid")
_SCORE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*(?:[-–:]\s*|\s+)(\d{1,2})(?!\d)")
_DATE_TIME_RE = re.compile(r"(\d{2}/\d{2}/\d{4},\s*\d{2}:\d{2})")


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _pleno_category(goals: int) -> str:
    return str(goals) if goals < 3 else "M"


def _score_from_text(value: str, *, context: str) -> tuple[int, int]:
    matches = _SCORE_RE.findall(value)
    if len(matches) != 1:
        raise ValueError(f"{context}: expected exactly one score, found {matches!r}")
    return tuple(int(part) for part in matches[0])


def _result_from_score(home_goals: int, away_goals: int) -> str:
    return "1" if home_goals > away_goals else ("2" if away_goals > home_goals else "X")


class _HTMLCollector(HTMLParser):
    """Small stdlib-only collector for the tables/lists used by the two sources."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[dict[str, Any]]]] = []
        self.lists: list[list[str]] = []
        self.all_text: list[str] = []
        self.anchors: list[dict[str, str]] = []
        self._table: list[list[dict[str, Any]]] | None = None
        self._row: list[dict[str, Any]] | None = None
        self._cell: dict[str, Any] | None = None
        self._anchor: dict[str, Any] | None = None
        self._ul_depth = 0
        self._list: list[str] | None = None
        self._li: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "table" and self._table is None:
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = {"text": [], "plain": [], "anchors": []}
        elif tag == "a":
            self._anchor = {"href": attributes.get("href") or "", "text": []}
        elif tag == "ul":
            if self._ul_depth == 0:
                self._list = []
            self._ul_depth += 1
        elif tag == "li" and self._ul_depth == 1:
            self._li = []
        elif tag == "br" and self._cell is not None:
            self._cell["text"].append(" ")
            if self._anchor is None:
                self._cell["plain"].append(" ")

    def handle_data(self, data: str) -> None:
        self.all_text.append(data)
        if self._cell is not None:
            self._cell["text"].append(data)
            if self._anchor is None:
                self._cell["plain"].append(data)
        if self._anchor is not None:
            self._anchor["text"].append(data)
        if self._li is not None:
            self._li.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._anchor is not None:
            anchor = {
                "href": self._anchor["href"],
                "text": _clean(" ".join(self._anchor["text"])),
            }
            self.anchors.append(anchor)
            if self._cell is not None:
                self._cell["anchors"].append(anchor["text"])
            self._anchor = None
        elif tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._cell["text"] = _clean(" ".join(self._cell["text"]))
            self._cell["plain"] = _clean(" ".join(self._cell["plain"]))
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if self._row:
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None
        elif tag == "li" and self._li is not None:
            if self._list is not None:
                self._list.append(_clean(" ".join(self._li)))
            self._li = None
        elif tag == "ul" and self._ul_depth:
            self._ul_depth -= 1
            if self._ul_depth == 0 and self._list is not None:
                if self._list:
                    self.lists.append(self._list)
                self._list = None


def _parse_local_datetime(value: str, *, context: str) -> datetime:
    match = _DATE_TIME_RE.search(value)
    if match is None:
        raise ValueError(f"{context}: invalid Spanish local date/time {value!r}")
    parsed = datetime.strptime(match.group(1), "%d/%m/%Y, %H:%M")
    return parsed.replace(tzinfo=SPAIN_TIMEZONE)


def parse_historicoquiniela_coupon_html(
    html: str,
    *,
    season: str,
    jornada: int,
    source_url: str,
    source_sha256: str,
    retrieved_at_utc: str,
) -> dict[str, Any]:
    """Parse one HistoricalQuiniela results page without fuzzy team matching."""
    collector = _HTMLCollector()
    collector.feed(html)
    header = ["#", "fecha", "encuentro", "signo"]
    selected_rows = None
    for table in collector.tables:
        for row_index, row in enumerate(table):
            values = [_clean(cell["text"]).casefold() for cell in row]
            if len(values) >= 4 and values[:4] == header:
                selected_rows = table[row_index + 1 :]
                break
        if selected_rows is not None:
            break
    if selected_rows is None:
        raise ValueError(
            "HistoricalQuiniela page has no recognized #/Fecha/Encuentro/Signo table"
        )

    fixtures = []
    for row in selected_rows:
        if len(row) < 4:
            continue
        number_match = re.search(r"\d+", row[0]["text"])
        if number_match is None:
            continue
        number = int(number_match.group())
        encounter = row[2]
        anchors = [value for value in encounter["anchors"] if value]
        if len(anchors) < 2:
            raise ValueError(
                f"coupon fixture {number}: encounter has no exact home/away anchors"
            )
        home, away = anchors[0], anchors[-1]
        candidates = anchors[1:-1] + [encounter["plain"], encounter["text"]]
        score = None
        for candidate in candidates:
            try:
                score = _score_from_text(candidate, context=f"coupon fixture {number}")
                break
            except ValueError:
                continue
        if score is None:
            raise ValueError(f"coupon fixture {number}: score could not be extracted")
        kickoff = _parse_local_datetime(
            row[1]["text"], context=f"coupon fixture {number}"
        )
        home_goals, away_goals = score
        sign_text = re.sub(r"\s+", "", row[3]["text"]).upper()
        result = _result_from_score(home_goals, away_goals)
        if number <= 14 and sign_text != result:
            raise ValueError(
                f"coupon fixture {number}: published sign {sign_text!r} conflicts with score {home_goals}-{away_goals}"
            )
        pleno_home = _pleno_category(home_goals)
        pleno_away = _pleno_category(away_goals)
        if number == 15 and sign_text.replace("-", "") != f"{pleno_home}{pleno_away}":
            raise ValueError(
                f"coupon Pleno al 15: published category {sign_text!r} conflicts with score {home_goals}-{away_goals}"
            )
        fixtures.append(
            {
                "number": number,
                "kickoff_at": kickoff.isoformat(),
                "home": home,
                "away": away,
                "home_goals": home_goals,
                "away_goals": away_goals,
                "result": result,
                "pleno_home_category": pleno_home if number == 15 else None,
                "pleno_away_category": pleno_away if number == 15 else None,
            }
        )

    fixtures.sort(key=lambda item: item["number"])
    if [item["number"] for item in fixtures] != list(range(1, 16)):
        raise ValueError(
            f"coupon must contain exactly fixtures 1..15; received {[item['number'] for item in fixtures]}"
        )
    first_kickoff = min(datetime.fromisoformat(item["kickoff_at"]) for item in fixtures)
    # HistoricalQuiniela labels this summary value "Fecha". It is a page/draw
    # date label, not evidence of when the final results were published.
    source_date_match = re.search(
        r"\bFecha\s+(\d{2}/\d{2}/\d{4},\s*\d{2}:\d{2})",
        _clean(" ".join(collector.all_text)),
        flags=re.IGNORECASE,
    )
    source_date_label_at = (
        _parse_local_datetime(
            source_date_match.group(1), context="coupon source date label"
        )
        if source_date_match
        else None
    )
    return {
        "schema_version": COUPON_SCHEMA_VERSION,
        "coupon_id": f"{season}:{jornada:02d}",
        "season": season,
        "jornada": jornada,
        "source": COUPON_SOURCE,
        "source_url": source_url,
        "source_sha256": source_sha256,
        "retrieved_at_utc": retrieved_at_utc,
        "source_date": source_date_label_at.date().isoformat()
        if source_date_label_at
        else None,
        "source_date_label_at": source_date_label_at.isoformat()
        if source_date_label_at
        else None,
        "first_kickoff_at": first_kickoff.isoformat(),
        "training_cutoff_date": (first_kickoff.date() - timedelta(days=1)).isoformat(),
        "fixtures": fixtures,
        "official_result_source": SELAE_SOURCE,
        "official_result_url": None,
        "official_result_sha256": None,
        "official_main_matches_verified": False,
        "official_pleno_verified": False,
        "official_verification_errors": ["official result page has not been checked"],
    }


def parse_selae_result_html(html: str) -> dict[str, Any]:
    """Extract the 14 ordered official results and, when present, Pleno al 15."""
    collector = _HTMLCollector()
    collector.feed(html)
    expected_numbers = [str(index) for index in range(1, 15)]
    official_rows = None
    for index in range(max(0, len(collector.lists) - 4)):
        number_values = [re.sub(r"\D", "", value) for value in collector.lists[index]]
        if number_values != expected_numbers:
            continue
        groups = collector.lists[index + 1 : index + 5]
        if len(groups) == 4 and all(len(group) == 14 for group in groups):
            homes, aways, scores, signs = groups
            official_rows = []
            for number, (home, away, score_text, sign) in enumerate(
                zip(homes, aways, scores, signs, strict=True), start=1
            ):
                home_goals, away_goals = _score_from_text(
                    score_text, context=f"SELAE official fixture {number}"
                )
                result = _result_from_score(home_goals, away_goals)
                if _clean(sign).upper() != result:
                    raise ValueError(
                        f"SELAE fixture {number}: sign {sign!r} conflicts with score {score_text!r}"
                    )
                official_rows.append(
                    {
                        "number": number,
                        "home": _clean(home),
                        "away": _clean(away),
                        "home_goals": home_goals,
                        "away_goals": away_goals,
                        "result": result,
                    }
                )
            break
    if official_rows is None:
        raise ValueError(
            "SELAE page does not expose the expected five ordered 14-item lists"
        )

    pleno = None
    for values in collector.lists:
        if len(values) >= 5 and _clean(values[0]) == "15":
            try:
                home_goals, away_goals = _score_from_text(
                    values[3], context="SELAE Pleno al 15"
                )
            except ValueError:
                continue
            home_category = _pleno_category(home_goals)
            away_category = _pleno_category(away_goals)
            official_sign = (
                re.sub(r"\s+", "", _clean(values[4])).replace("-", "").upper()
            )
            if official_sign != f"{home_category}{away_category}":
                raise ValueError(
                    "SELAE Pleno al 15 category conflicts with official score"
                )
            pleno = {
                "home": _clean(values[1]),
                "away": _clean(values[2]),
                "home_goals": home_goals,
                "away_goals": away_goals,
                "home_category": home_category,
                "away_category": away_category,
            }
            break
    return {"fixtures": official_rows, "pleno": pleno}


def verify_coupon_against_selae(
    coupon: dict[str, Any],
    official_html: str,
    *,
    official_url: str,
    official_sha256: str,
) -> dict[str, Any]:
    """Attach exact-order official verification; never fuzzy-match fixtures."""
    official = parse_selae_result_html(official_html)
    main_errors = []
    for expected, actual in zip(
        coupon["fixtures"][:14], official["fixtures"], strict=True
    ):
        number = expected["number"]
        if normalize_team_name(expected["home"]) != normalize_team_name(actual["home"]):
            main_errors.append(
                f"fixture {number}: home mismatch {expected['home']!r} != {actual['home']!r}"
            )
        if normalize_team_name(expected["away"]) != normalize_team_name(actual["away"]):
            main_errors.append(
                f"fixture {number}: away mismatch {expected['away']!r} != {actual['away']!r}"
            )
        for field in ("home_goals", "away_goals", "result"):
            if expected[field] != actual[field]:
                main_errors.append(
                    f"fixture {number}: {field} mismatch {expected[field]!r} != {actual[field]!r}"
                )

    expected_pleno = coupon["fixtures"][14]
    official_pleno = official["pleno"]
    pleno_errors = []
    if official_pleno is not None:
        if normalize_team_name(expected_pleno["home"]) != normalize_team_name(
            official_pleno["home"]
        ):
            pleno_errors.append("Pleno home team mismatch")
        if normalize_team_name(expected_pleno["away"]) != normalize_team_name(
            official_pleno["away"]
        ):
            pleno_errors.append("Pleno away team mismatch")
        if expected_pleno["home_goals"] != official_pleno["home_goals"]:
            pleno_errors.append("Pleno home score mismatch")
        if expected_pleno["away_goals"] != official_pleno["away_goals"]:
            pleno_errors.append("Pleno away score mismatch")
    else:
        pleno_errors.append("SELAE page does not expose Pleno al 15 result")

    coupon["official_result_url"] = official_url
    coupon["official_result_sha256"] = official_sha256
    coupon["official_main_matches_verified"] = not main_errors
    coupon["official_pleno_verified"] = not pleno_errors
    coupon["official_verification_errors"] = main_errors + pleno_errors
    return coupon


def validate_coupon_record(coupon: dict[str, Any]) -> None:
    if coupon.get("schema_version") != COUPON_SCHEMA_VERSION:
        raise ValueError("unsupported coupon schema_version")
    if not isinstance(coupon.get("coupon_id"), str) or not coupon["coupon_id"]:
        raise ValueError("coupon_id is required")
    fixtures = coupon.get("fixtures")
    if not isinstance(fixtures, list) or len(fixtures) != 15:
        raise ValueError(f"{coupon.get('coupon_id')}: exactly 15 fixtures are required")
    if [fixture.get("number") for fixture in fixtures] != list(range(1, 16)):
        raise ValueError(f"{coupon['coupon_id']}: fixtures must be ordered 1..15")
    kickoffs = []
    for fixture in fixtures:
        kickoff = datetime.fromisoformat(fixture["kickoff_at"])
        if kickoff.tzinfo is None or kickoff.utcoffset() is None:
            raise ValueError(
                f"{coupon['coupon_id']}: kickoff timestamps must be timezone-aware"
            )
        kickoffs.append(kickoff)
        if not isinstance(fixture.get("home"), str) or not fixture["home"].strip():
            raise ValueError(f"{coupon['coupon_id']}: fixture home team is missing")
        if not isinstance(fixture.get("away"), str) or not fixture["away"].strip():
            raise ValueError(f"{coupon['coupon_id']}: fixture away team is missing")
        if normalize_team_name(fixture["home"]) == normalize_team_name(fixture["away"]):
            raise ValueError(
                f"{coupon['coupon_id']}: fixture has identical home and away teams"
            )
        home_goals, away_goals = fixture.get("home_goals"), fixture.get("away_goals")
        if (
            isinstance(home_goals, bool)
            or isinstance(away_goals, bool)
            or not isinstance(home_goals, int)
            or not isinstance(away_goals, int)
            or home_goals < 0
            or away_goals < 0
        ):
            raise ValueError(
                f"{coupon['coupon_id']}: fixture scores must be non-negative integers"
            )
        if fixture.get("result") != _result_from_score(home_goals, away_goals):
            raise ValueError(
                f"{coupon['coupon_id']}: fixture result conflicts with score"
            )
        if fixture["number"] == 15:
            if fixture.get("pleno_home_category") != _pleno_category(home_goals):
                raise ValueError(
                    f"{coupon['coupon_id']}: Pleno home category conflicts with score"
                )
            if fixture.get("pleno_away_category") != _pleno_category(away_goals):
                raise ValueError(
                    f"{coupon['coupon_id']}: Pleno away category conflicts with score"
                )
    first_kickoff = min(kickoffs)
    if datetime.fromisoformat(coupon["first_kickoff_at"]) != first_kickoff:
        raise ValueError(
            f"{coupon['coupon_id']}: first kickoff metadata is inconsistent"
        )
    cutoff = date.fromisoformat(coupon["training_cutoff_date"])
    if cutoff != first_kickoff.date() - timedelta(days=1):
        raise ValueError(
            f"{coupon['coupon_id']}: training cutoff must be the previous local calendar day"
        )
    try:
        source_date_label_at = datetime.fromisoformat(coupon["source_date_label_at"])
        source_date = date.fromisoformat(coupon["source_date"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"{coupon['coupon_id']}: source date label is missing or invalid"
        ) from exc
    if source_date_label_at.tzinfo is None or source_date_label_at.utcoffset() is None:
        raise ValueError(
            f"{coupon['coupon_id']}: source date label must be timezone-aware"
        )
    if source_date != source_date_label_at.date():
        raise ValueError(
            f"{coupon['coupon_id']}: source date conflicts with its displayed date label"
        )
    for field in ("source_sha256", "official_result_sha256"):
        value = coupon.get(field)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError(f"{coupon['coupon_id']}: {field} must be a SHA-256 digest")
    source_url = urlparse(str(coupon.get("source_url", "")))
    official_url = urlparse(str(coupon.get("official_result_url", "")))
    if source_url.scheme != "https" or source_url.netloc != "www.historicoquiniela.com":
        raise ValueError(f"{coupon['coupon_id']}: invalid historical coupon source URL")
    if (
        official_url.scheme != "https"
        or official_url.netloc != "www.loteriasyapuestas.es"
    ):
        raise ValueError(f"{coupon['coupon_id']}: invalid official SELAE source URL")
    if coupon.get("official_main_matches_verified") is not True:
        raise ValueError(
            f"{coupon['coupon_id']}: 14 main results are not verified against SELAE"
        )
    if coupon.get("official_pleno_verified") is not True:
        raise ValueError(
            f"{coupon['coupon_id']}: Pleno al 15 is not verified against SELAE"
        )


def write_coupon_jsonl(
    path: str | Path, coupons: list[dict[str, Any]], manifest: dict[str, Any]
) -> int:
    target = Path(path)
    if target.exists():
        raise FileExistsError(
            f"refusing to overwrite existing coupon archive: {target}"
        )
    if not coupons:
        raise ValueError("at least one coupon is required")
    seen = set()
    for coupon in coupons:
        validate_coupon_record(coupon)
        coupon_id = coupon["coupon_id"]
        if coupon_id in seen:
            raise ValueError(f"duplicate coupon_id: {coupon_id}")
        seen.add(coupon_id)
    header = {
        "record_type": "manifest",
        "schema_version": COUPON_SCHEMA_VERSION,
        **manifest,
    }
    lines = [json.dumps(header, ensure_ascii=False, sort_keys=True)]
    lines.extend(
        json.dumps(
            {"record_type": "coupon", **coupon}, ensure_ascii=False, sort_keys=True
        )
        for coupon in coupons
    )
    content = ("\n".join(lines) + "\n").encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=target.parent, prefix=f".{target.name}.", delete=False
        ) as handle:
            temp_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
        temp_name = None
    finally:
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
    return len(coupons)


def read_coupon_jsonl(path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"cannot read coupon archive {path}") from exc
    if not lines:
        raise ValueError("coupon archive is empty")
    records = [json.loads(line) for line in lines if line.strip()]
    if not records or records[0].get("record_type") != "manifest":
        raise ValueError("coupon archive must start with a manifest")
    manifest = records[0]
    if manifest.get("schema_version") != COUPON_SCHEMA_VERSION:
        raise ValueError("unsupported coupon archive manifest schema_version")
    coupons = []
    seen = set()
    for index, record in enumerate(records[1:], start=2):
        if record.get("record_type") != "coupon":
            raise ValueError(f"coupon archive line {index} is not a coupon")
        coupon = {key: value for key, value in record.items() if key != "record_type"}
        validate_coupon_record(coupon)
        if coupon["coupon_id"] in seen:
            raise ValueError(f"duplicate coupon_id: {coupon['coupon_id']}")
        seen.add(coupon["coupon_id"])
        coupons.append(coupon)
    if not coupons:
        raise ValueError("coupon archive contains no coupons")
    return manifest, coupons


def _match_day(value: datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    raw = str(value).strip()
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y/%m/%d", "%m/%d/%Y"):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
    raise ValueError(f"invalid historical match date: {value!r}")


def _evaluate_ticket(
    probabilities: list[dict[str, float]],
    actual: tuple[str, ...],
    optimizer: Any,
    *,
    budget: int,
    pleno_home_category: str,
    pleno_away_category: str,
    actual_pleno_home: str,
    actual_pleno_away: str,
    pleno_probability: float,
) -> dict[str, Any]:
    ticket = optimizer.optimize(
        probabilities,
        budget=budget,
        pleno15_home_categories=(pleno_home_category,),
        pleno15_away_categories=(pleno_away_category,),
    )
    columns = [tuple(column) for column in ticket["columns"]]
    selected = [{column[index] for column in columns} for index in range(14)]
    covered_14 = all(actual[index] in selected[index] for index in range(14))
    best_column_hits = max(
        sum(sign == actual[index] for index, sign in enumerate(column))
        for column in columns
    )
    single_sign_hits = sum(
        max(SIGNS, key=probabilities[index].__getitem__) == actual[index]
        for index in range(14)
    )
    pleno_hit = (
        actual_pleno_home == pleno_home_category
        and actual_pleno_away == pleno_away_category
    )
    return {
        "status": "success",
        "single_sign_hits": single_sign_hits,
        "best_column_hits": best_column_hits,
        "covered_14": covered_14,
        "pleno_hit": pleno_hit,
        "full_coupon_covered": covered_14 and pleno_hit,
        "columns": [list(column) for column in columns],
        "column_count": ticket["column_count"],
        "total_bets": ticket["total_bets"],
        "double_count": ticket["double_count"],
        "triple_count": ticket["triple_count"],
        "minimum_total_bets": ticket["minimum_total_bets"],
        "maximum_authorized_total_bets": ticket["maximum_authorized_total_bets"],
        "pleno15_multiplier": ticket["pleno15_multiplier"],
        "pleno15_home_categories": ticket["pleno15_home_categories"],
        "pleno15_away_categories": ticket["pleno15_away_categories"],
        "price_per_bet_eur": ticket["price_per_bet_eur"],
        "cost_eur": ticket["cost_eur"],
        "independent_14_coverage_estimate": ticket["independent_coverage_estimate"],
        "pleno_model": "dixon_coles",
        "pleno_selected_home_category": pleno_home_category,
        "pleno_selected_away_category": pleno_away_category,
        "pleno_selected_probability_mass": pleno_probability,
    }


def evaluate_coupon(
    coupon: dict[str, Any],
    historical_matches: list[Match],
    *,
    budget: int = 8,
    min_history_matches: int = 300,
) -> dict[str, Any]:
    """Evaluate a complete 15-match coupon from one pre-first-kickoff snapshot."""
    validate_coupon_record(coupon)
    cutoff = date.fromisoformat(coupon["training_cutoff_date"])
    first_kickoff = datetime.fromisoformat(coupon["first_kickoff_at"])
    history = [
        match
        for match in historical_matches
        if _match_day(match.date) <= cutoff
        and match.home_goals is not None
        and match.away_goals is not None
    ]
    if len(history) < min_history_matches:
        raise ValueError(
            f"{coupon['coupon_id']}: only {len(history)} prior matches; minimum is {min_history_matches}"
        )
    training_dates = [_match_day(match.date) for match in history]
    if any(training_date >= first_kickoff.date() for training_date in training_dates):
        raise RuntimeError(
            f"{coupon['coupon_id']}: training history crosses the coupon kickoff date"
        )
    training_history_min_date = min(training_dates)
    training_history_max_date = max(training_dates)

    engine = KiniEngine(enable_ml=True).fit(history)
    if not engine.dc.fitted:
        raise RuntimeError(
            f"{coupon['coupon_id']}: Dixon-Coles fit failed: {engine.dc.fit_error or engine.dc.fit_status}"
        )
    fixtures = [
        Match(
            date=datetime.fromisoformat(item["kickoff_at"]),
            home=item["home"],
            away=item["away"],
        )
        for item in coupon["fixtures"]
    ]
    if any(fixture.date < first_kickoff for fixture in fixtures):
        raise RuntimeError(
            f"{coupon['coupon_id']}: fixture kickoff precedes recorded first kickoff"
        )

    pleno_distribution = engine.dc.pleno15_probs(
        fixtures[14].home,
        fixtures[14].away,
        allow_unseen_team_fallback=True,
    )
    pleno_best = pleno_distribution[0]
    pleno_home = str(pleno_best["home_goals"])
    pleno_away = str(pleno_best["away_goals"])
    pleno_probability = float(pleno_best["probability"])
    actual_pleno = coupon["fixtures"][14]
    actual_pleno_home = str(actual_pleno["pleno_home_category"])
    actual_pleno_away = str(actual_pleno["pleno_away_category"])
    actual = tuple(item["result"] for item in coupon["fixtures"][:14])
    model_results = {}
    for mode in ("dc", "ml", "ensemble_dc_ml"):
        predictions = []
        error = None
        for fixture in fixtures[:14]:
            try:
                prediction = engine.predict(fixture, mode=mode)
                predictions.append(
                    {sign: float(prediction.probabilities[sign]) for sign in SIGNS}
                )
            except (
                ArithmeticError,
                KeyError,
                RuntimeError,
                TypeError,
                ValueError,
            ) as exc:
                error = f"{type(exc).__name__}: {exc}"
                break
        if error is not None:
            model_results[mode] = {
                "status": "failed",
                "error": error,
                "n_predictions": len(predictions),
            }
            continue
        model_results[mode] = {
            **_evaluate_ticket(
                predictions,
                actual,
                engine.optimizer,
                budget=budget,
                pleno_home_category=pleno_home,
                pleno_away_category=pleno_away,
                actual_pleno_home=actual_pleno_home,
                actual_pleno_away=actual_pleno_away,
                pleno_probability=pleno_probability,
            ),
            "n_predictions": len(predictions),
            "probabilities": predictions,
        }

    return {
        "coupon_id": coupon["coupon_id"],
        "season": coupon["season"],
        "jornada": coupon["jornada"],
        "source_url": coupon["source_url"],
        "official_result_url": coupon["official_result_url"],
        "official_main_matches_verified": coupon["official_main_matches_verified"],
        "official_pleno_verified": coupon["official_pleno_verified"],
        "first_kickoff_at": coupon["first_kickoff_at"],
        "training_cutoff_date": coupon["training_cutoff_date"],
        "actual_main_results": list(actual),
        "actual_pleno_categories": {
            "home": actual_pleno_home,
            "away": actual_pleno_away,
        },
        "training_match_count": len(history),
        "training_history_min_date": training_history_min_date.isoformat(),
        "training_history_max_date": training_history_max_date.isoformat(),
        "model_fit_match_count": engine.dc.n_training_matches,
        "pleno_prediction": {
            "model": "dixon_coles",
            "selection_method": "max_aggregated_category_pair_probability",
            "home_category": pleno_home,
            "away_category": pleno_away,
            "probability_mass": pleno_probability,
            "training_match_count": engine.dc.n_training_matches,
        },
        "budget_columns": budget,
        "models": model_results,
    }


def evaluate_coupon_batch(
    coupons: list[dict[str, Any]],
    historical_matches: list[Match],
    *,
    budget: int = 8,
    min_history_matches: int = 300,
) -> dict[str, Any]:
    results = []
    for coupon in coupons:
        try:
            results.append(
                evaluate_coupon(
                    coupon,
                    historical_matches,
                    budget=budget,
                    min_history_matches=min_history_matches,
                )
            )
        except (ArithmeticError, KeyError, RuntimeError, TypeError, ValueError) as exc:
            results.append(
                {
                    "coupon_id": coupon.get("coupon_id"),
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    summary: dict[str, Any] = {"coupon_count": len(coupons), "models": {}}
    for mode in ("dc", "ml", "ensemble_dc_ml"):
        successful = [
            item["models"][mode]
            for item in results
            if item.get("models", {}).get(mode, {}).get("status") == "success"
        ]
        summary["models"][mode] = {
            "evaluated_coupons": len(successful),
            "failed_coupons": len(coupons) - len(successful),
            "covered_14_coupons": sum(bool(item["covered_14"]) for item in successful),
            "full_coupon_covered": sum(
                bool(item["full_coupon_covered"]) for item in successful
            ),
            "mean_single_sign_hits": (
                sum(item["single_sign_hits"] for item in successful) / len(successful)
                if successful
                else None
            ),
            "mean_best_column_hits": (
                sum(item["best_column_hits"] for item in successful) / len(successful)
                if successful
                else None
            ),
            "total_cost_eur": round(sum(item["cost_eur"] for item in successful), 2),
        }
    return {
        "schema_version": COUPON_BACKTEST_RESULT_SCHEMA_VERSION,
        "method": {
            "cutoff": "all training results dated strictly before the local calendar date of the earliest coupon kickoff",
            "training_history": "one fitted snapshot shared by all 15 coupon fixtures and all model candidates in that coupon",
            "market": "excluded; this coupon archive does not provide timestamp-verified pre-kickoff odds",
            "pleno": "Dixon-Coles score-grid categories; reported separately and not attributed to ML",
            "coverage": "realized exact direct-column coverage; independent marginal estimate is reported separately",
            "payout": "not estimated; official prize distribution and stake-level expected value are outside this pilot",
        },
        "config": {
            "budget_columns": budget,
            "min_history_matches": min_history_matches,
        },
        "summary": summary,
        "coupons": results,
    }


def extract_historical_journeys(html: str, *, season: str) -> list[int]:
    """Return distinct journey numbers linked from a season index page."""
    collector = _HTMLCollector()
    collector.feed(html)
    pattern = re.compile(rf"^/historico/{re.escape(season)}/(\d+)/?$")
    numbers = set()
    for anchor in collector.anchors:
        match = pattern.match(urlparse(anchor.get("href", "")).path)
        if match is not None:
            numbers.add(int(match.group(1)))
    if not numbers:
        raise ValueError(f"season index has no journey links for {season}")
    return sorted(numbers)


def selae_result_url(draw_date: str) -> str:
    """Build the public SELAE result URL from the coupon's displayed draw date.

    The source page's summary "Fecha" label is not a result-publication timestamp.
    """
    months = (
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    )
    parsed = date.fromisoformat(draw_date)
    return (
        "https://www.loteriasyapuestas.es/es/la-quiniela/resultados/"
        f"la-quiniela-resultados-del-{parsed.day}-de-{months[parsed.month - 1]}-de-{parsed.year}"
    )
