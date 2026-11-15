from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import numpy as np
from scipy.stats import poisson

SIGNS = ("1", "X", "2")
LAE_SOURCE_ID = "quinielista.es:porcentajes_lae.asp"
LAE_KICKOFF_EVIDENCE_MAX_AGE = timedelta(hours=24)


def _validated_probability_vector(probabilities: Any) -> np.ndarray | None:
    """Return a valid 1/X/2 vector without silently repairing bad source data."""
    if not isinstance(probabilities, dict):
        return None

    values: list[float] = []
    for sign in SIGNS:
        raw = probabilities.get(sign)
        if isinstance(raw, (bool, np.bool_)):
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        if not np.isfinite(value) or not 0.0 <= value <= 1.0:
            return None
        values.append(value)

    if not np.isclose(sum(values), 1.0, rtol=0.0, atol=1e-6):
        return None
    return np.asarray(values, dtype=float)


@dataclass(frozen=True)
class Match:
    date: datetime | str
    home: str
    away: str
    home_goals: int | None = None
    away_goals: int | None = None
    result: str | None = None
    lae: dict[str, float] | None = None
    market: dict[str, float] | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def outcome(self) -> str:
        if self.result in SIGNS:
            return str(self.result)
        if self.home_goals is None or self.away_goals is None:
            raise ValueError("Match has no observed result")
        return "1" if self.home_goals > self.away_goals else ("2" if self.away_goals > self.home_goals else "X")

    @property
    def has_temporally_eligible_market(self) -> bool:
        """Require the schedule screen and a valid normalized 1/X/2 vector."""
        return (
            self.detail.get("market_temporal_status") == "schedule_compatible"
            and self.detail.get("market_pre_match_eligible") is True
            and _validated_probability_vector(self.market) is not None
        )

    @property
    def has_temporally_eligible_lae(self) -> bool:
        """Require a verified fixture, fresh schedule evidence and a pre-kickoff capture."""
        if not self.lae:
            return False
        if self.detail.get("lae_source") != LAE_SOURCE_ID:
            return False
        if self.detail.get("fixture_identity_status") != "verified":
            return False

        evidence_url = self.detail.get("kickoff_evidence_url")
        if not isinstance(evidence_url, str) or not evidence_url.startswith("https://"):
            return False

        captured_at = _parse_aware_datetime(self.detail.get("lae_captured_at"))
        evidence_checked_at = _parse_aware_datetime(
            self.detail.get("kickoff_evidence_checked_at_utc")
        )
        kickoff_at = _parse_aware_datetime(self.detail.get("kickoff_at"))
        if captured_at is None or evidence_checked_at is None or kickoff_at is None:
            return False

        evidence_age = captured_at - evidence_checked_at
        if not timedelta(0) <= evidence_age <= LAE_KICKOFF_EVIDENCE_MAX_AGE:
            return False
        if captured_at >= kickoff_at:
            return False

        return _validated_probability_vector(self.lae) is not None


@dataclass(frozen=True)
class Prediction:
    home: str
    away: str
    probabilities: dict[str, float]
    sign: str
    scorelines: list[dict[str, Any]]
    surprise: dict[str, Any] | None
    reasons: list[str]


def _date_num(value: datetime | str) -> float:
    """Return a stable timestamp for ISO and Football-Data date formats."""
    if isinstance(value, datetime):
        return value.timestamp()

    raw = str(value).strip()
    normalized = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        pass

    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).timestamp()
        except ValueError:
            continue

    raise ValueError(f"Unsupported date format: {raw!r}")


def _parse_aware_datetime(value: Any) -> datetime | None:
    """Parse an ISO timestamp only when its timezone is explicit."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _calendar_date_key(value: datetime | str) -> str:
    """Return the source calendar date without admitting same-day results."""
    if isinstance(value, datetime):
        return value.date().isoformat()

    raw = str(value).strip()
    normalized = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date().isoformat()
    except ValueError:
        pass

    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue

    return datetime.fromtimestamp(_date_num(value)).date().isoformat()


def _prior_completed_matches(history: list[Match], current: Match) -> list[Match]:
    """Return completed matches strictly before the fixture's source calendar day."""
    target_day = _calendar_date_key(current.date)
    prior = [
        match
        for match in history
        if _calendar_date_key(match.date) < target_day
        and match.home_goals is not None
        and match.away_goals is not None
    ]
    prior.sort(
        key=lambda match: (_calendar_date_key(match.date), _date_num(match.date))
    )
    return prior


def _team_form_features(
    team: str,
    matches: list[Match],
) -> tuple[float, float, float]:
    """Summarize the latest eight completed matches already scoped to a team."""
    recent = matches[-8:]
    if not recent:
        return 0.0, 1.35, 1.05

    points = goals_for = goals_against = 0.0
    for match in recent:
        if match.home == team:
            scored, conceded = match.home_goals, match.away_goals
        else:
            scored, conceded = match.away_goals, match.home_goals
        goals_for += scored
        goals_against += conceded
        points += 3 if scored > conceded else 1 if scored == conceded else 0
    return (
        points / len(recent),
        goals_for / len(recent),
        goals_against / len(recent),
    )


def _norm(p: Iterable[float]) -> np.ndarray:
    x = np.asarray(list(p), dtype=float)
    x = np.clip(x, 1e-12, None)
    return x / x.sum()


def _dc_tau(i: int, j: int, lh: float, la: float, rho: float) -> float:
    if i == 0 and j == 0:
        return 1 - lh * la * rho
    if i == 0 and j == 1:
        return 1 + lh * rho
    if i == 1 and j == 0:
        return 1 + la * rho
    if i == 1 and j == 1:
        return 1 - rho
    return 1.0


def score_grid(lh: float, la: float, rho: float = -0.05, max_goals: int = 10) -> np.ndarray:
    grid = np.zeros((max_goals + 1, max_goals + 1), dtype=float)
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            t = max(_dc_tau(h, a, lh, la, rho), 1e-8)
            grid[h, a] = poisson.pmf(h, lh) * poisson.pmf(a, la) * t
    return grid / grid.sum()


def grid_to_1x2(grid: np.ndarray) -> dict[str, float]:
    h, a = np.indices(grid.shape)
    return dict(zip(SIGNS, _norm([grid[h > a].sum(), grid[h == a].sum(), grid[h < a].sum()])))


class DixonColes:
    """Kini adapter around the maintained penaltyblog Dixon-Coles model."""

    def __init__(self, decay: float = 0.995, rho: float = -0.05) -> None:
        self.decay = decay
        self.rho = rho
        self.teams: list[str] = []
        self.home_adv = 0.25
        self.fitted = False
        self.model: Any = None

    def fit(self, matches: list[Match]) -> DixonColes:
        usable = [
            m for m in matches
            if m.home_goals is not None and m.away_goals is not None
        ]
        if len(usable) < 12:
            self.fitted = False
            return self

        from penaltyblog.models import DixonColesGoalModel, dixon_coles_weights

        self.teams = sorted({m.home for m in usable} | {m.away for m in usable})
        # penaltyblog expects datetime-like values because it computes timedelta.days.
        # Parse through the shared date parser so ISO and Football-Data DD/MM/YYYY
        # inputs follow exactly the same chronological interpretation.
        dates = [datetime.fromtimestamp(_date_num(m.date)) for m in usable]

        xi = max(-np.log(float(self.decay)), 0.0)
        weights = dixon_coles_weights(dates, xi=xi)

        self.model = DixonColesGoalModel(
            goals_home=np.asarray([m.home_goals for m in usable], dtype=float),
            goals_away=np.asarray([m.away_goals for m in usable], dtype=float),
            teams_home=np.asarray([m.home for m in usable], dtype=str),
            teams_away=np.asarray([m.away for m in usable], dtype=str),
            weights=weights,
        )
        self.model.fit(
            use_gradient=True,
            minimizer_options={"maxiter": 1000, "ftol": 1e-7},
        )

        self.teams = list(self.model.teams)
        self.fitted = bool(self.model.fitted)
        return self

    def expected_goals(self, home: str, away: str) -> tuple[float, float]:
        if not self.fitted or home not in self.teams or away not in self.teams:
            return 1.35, 1.05
        pred = self.model.predict(home, away, max_goals=15, normalize=True)
        return (
            float(np.clip(pred.home_goal_expectation, 0.15, 5.0)),
            float(np.clip(pred.away_goal_expectation, 0.15, 5.0)),
        )

    def _score_grid(self, home: str, away: str) -> np.ndarray:
        if not self.fitted or home not in self.teams or away not in self.teams:
            lh, la = self.expected_goals(home, away)
            return score_grid(lh, la, self.rho)

        prediction = self.model.predict(home, away, max_goals=15, normalize=True)
        grid = np.asarray(prediction.grid, dtype=float)
        total = float(grid.sum())
        if not np.isfinite(grid).all() or total <= 0.0:
            raise ValueError("Dixon-Coles returned an invalid score grid")
        return grid / total

    def predict(self, home: str, away: str) -> tuple[dict[str, float], list[dict[str, Any]]]:
        if not self.fitted or home not in self.teams or away not in self.teams:
            lh, la = self.expected_goals(home, away)
            grid = score_grid(lh, la, self.rho)
            probs = grid_to_1x2(grid)
        else:
            pred = self.model.predict(home, away, max_goals=15, normalize=True)
            grid = np.asarray(pred.grid, dtype=float)
            probs = dict(zip(SIGNS, map(float, pred.home_draw_away)))

        flat = [
            {"score": f"{h}-{a}", "probability": float(grid[h, a])}
            for h, a in np.ndindex(grid.shape)
        ]
        flat.sort(key=lambda x: x["probability"], reverse=True)
        return probs, flat[:10]


    def pleno15_probs(self, home: str, away: str) -> list[dict[str, Any]]:
        """Aggregate the score grid into SELAE Pleno al 15 goal categories."""
        grid = self._score_grid(home, away)
        categories = {
            (home_goals, away_goals): 0.0
            for home_goals in ("0", "1", "2", "M")
            for away_goals in ("0", "1", "2", "M")
        }
        for home_goals, away_goals in np.ndindex(grid.shape):
            home_category = str(home_goals) if home_goals < 3 else "M"
            away_category = str(away_goals) if away_goals < 3 else "M"
            categories[(home_category, away_category)] += float(
                grid[home_goals, away_goals]
            )

        result = [
            {
                "home_goals": home_category,
                "away_goals": away_category,
                "probability": probability,
            }
            for (home_category, away_category), probability in categories.items()
        ]
        result.sort(key=lambda item: item["probability"], reverse=True)
        return result



class FeatureModel:
    """Compact supervised model using only pre-match information."""

    def __init__(self) -> None:
        self.model: Any = None
        self.teams: dict[str, int] = {}
        self._history_ref: list[Match] | None = None

    def invalidate(self) -> None:
        """Invalidate the fitted estimator when the engine receives new history."""
        self.model = None
        self._history_ref = None

    def _features(self, history: list[Match], m: Match) -> np.ndarray:
        """Build 12 rolling form features from completed matches on prior dates.

        The source has no reliable publication timestamp for standings or
        arbitrary context fields. Those fields are deliberately excluded.
        Date-only inputs use a strict calendar-day cutoff: same-day results
        cannot become features for another fixture on that date.
        """
        prior_history = _prior_completed_matches(history, m)

        def stats(team: str, venue: str | None = None) -> tuple[float, float, float]:
            xs = [
                match
                for match in prior_history
                if match.home == team or match.away == team
            ]
            if venue == "home":
                xs = [match for match in xs if match.home == team]
            elif venue == "away":
                xs = [match for match in xs if match.away == team]
            return _team_form_features(team, xs)

        home_points, home_gf, home_ga = stats(m.home)
        away_points, away_gf, away_ga = stats(m.away)
        home_home_points, home_home_gf, home_home_ga = stats(m.home, "home")
        away_away_points, away_away_gf, away_away_ga = stats(m.away, "away")

        return np.asarray(
            [
                home_points,
                home_gf,
                home_ga,
                away_points,
                away_gf,
                away_ga,
                home_home_points,
                home_home_gf,
                home_home_ga,
                away_away_points,
                away_away_gf,
                away_away_ga,
            ],
            dtype=float,
        )

    def _training_rows(
        self,
        training_history: list[Match],
    ) -> tuple[list[np.ndarray], list[str]]:
        """Build historical training rows in one chronological pass.

        All fixtures on a calendar day are scored from the state accumulated
        before that day; completed results are added only after the whole day.
        This is equivalent to calling _features for every row, without the
        quadratic repeated-history scans.
        """
        ordered = sorted(
            training_history,
            key=lambda match: (_calendar_date_key(match.date), _date_num(match.date)),
        )
        overall: dict[str, list[Match]] = {}
        home_only: dict[str, list[Match]] = {}
        away_only: dict[str, list[Match]] = {}
        rows: list[np.ndarray] = []
        outcomes: list[str] = []

        start = 0
        while start < len(ordered):
            day = _calendar_date_key(ordered[start].date)
            end = start + 1
            while end < len(ordered) and _calendar_date_key(ordered[end].date) == day:
                end += 1
            group = ordered[start:end]

            for match in group:
                if match.home_goals is None or match.away_goals is None:
                    continue
                values = (
                    *_team_form_features(match.home, overall.get(match.home, [])),
                    *_team_form_features(match.away, overall.get(match.away, [])),
                    *_team_form_features(match.home, home_only.get(match.home, [])),
                    *_team_form_features(match.away, away_only.get(match.away, [])),
                )
                rows.append(np.asarray(values, dtype=float))
                outcomes.append(match.outcome())

            for match in group:
                if match.home_goals is None or match.away_goals is None:
                    continue
                for team in {match.home, match.away}:
                    recent = overall.setdefault(team, [])
                    recent.append(match)
                    if len(recent) > 8:
                        del recent[:-8]

                home_recent = home_only.setdefault(match.home, [])
                home_recent.append(match)
                if len(home_recent) > 8:
                    del home_recent[:-8]

                away_recent = away_only.setdefault(match.away, [])
                away_recent.append(match)
                if len(away_recent) > 8:
                    del away_recent[:-8]

            start = end

        return rows, outcomes

    def fit_predict_proba(
        self,
        training_history: list[Match],
        current: Match,
        feature_history: list[Match] | None = None,
    ) -> np.ndarray | None:
        # Fit once per model-training snapshot. Inference features may advance
        # between refits as new results become available.
        if self._history_ref is not training_history:
            self.model = None
            rows, y = self._training_rows(training_history)

            if len(rows) < 40 or len(set(y)) < 3:
                self._history_ref = training_history
                return None

            try:
                from xgboost import XGBClassifier
                self.model = XGBClassifier(
                    n_estimators=180, max_depth=4, learning_rate=0.04,
                    subsample=0.85, colsample_bytree=0.85, objective="multi:softprob",
                    num_class=3, eval_metric="mlogloss", random_state=42, n_jobs=1
                )
            except (ImportError, OSError):
                from sklearn.ensemble import HistGradientBoostingClassifier
                self.model = HistGradientBoostingClassifier(
                    max_iter=180, learning_rate=0.05, max_leaf_nodes=15, random_state=42
                )

            enc = {"1": 0, "X": 1, "2": 2}
            self.model.fit(np.vstack(rows), np.asarray([enc[v] for v in y]))
            self._history_ref = training_history

        if self.model is None:
            return None

        current_history = feature_history if feature_history is not None else training_history
        # Estimators require a 2D matrix even for a single forecast row.
        features = np.asarray(self._features(current_history, current), dtype=float).reshape(1, -1)
        raw = np.asarray(self.model.predict_proba(features)[0], dtype=float)
        probabilities = np.zeros(len(SIGNS), dtype=float)
        probabilities[np.asarray(self.model.classes_, dtype=int)] = raw
        return _norm(probabilities)


def context_adjust(
    probs: dict[str, float],
    current: Match,
    history: list[Match],
) -> tuple[dict[str, float], list[str]]:
    prior_history = _prior_completed_matches(history, current)
    p = np.array([probs[s] for s in SIGNS], dtype=float)
    reasons: list[str] = []

    hf = _recent_form(prior_history, current.home)
    af = _recent_form(prior_history, current.away)
    delta = float(np.clip((hf - af) * 0.025, -0.08, 0.08))
    if abs(delta) >= 0.025:
        p += np.array([delta, -abs(delta) * 0.25, -delta])
        reasons.append(f"forma reciente: {current.home} {hf:.2f} vs {current.away} {af:.2f}")

    h2h = [
        match
        for match in prior_history
        if {match.home, match.away} == {current.home, current.away}
    ]
    if len(h2h) >= 5:
        current_home_wins = 0
        draws = 0
        current_away_wins = 0
        for m in h2h[-10:]:
            if m.home_goals == m.away_goals:
                draws += 1
            elif (m.home == current.home and m.home_goals > m.away_goals) or (
                m.away == current.home and m.away_goals > m.home_goals
            ):
                current_home_wins += 1
            else:
                current_away_wins += 1
        hp = _norm([current_home_wins, draws, current_away_wins])
        p = 0.94 * p + 0.06 * hp
        reasons.append("histórico H2H incorporado con peso limitado")

    out = _norm(p)
    return dict(zip(SIGNS, map(float, out))), reasons


def _blend(*items: tuple[dict[str, float], float]) -> dict[str, float]:
    acc = np.zeros(3)
    weight = 0.0
    for probs, w in items:
        if not probs or w <= 0:
            continue
        q = _norm([probs.get(s, 0.0) for s in SIGNS])
        acc += w * q
        weight += w
    return dict(zip(SIGNS, map(float, _norm(acc / max(weight, 1e-12)))))


def surprise_signal(
    model: dict[str, float],
    lae: dict[str, float] | None,
    market: dict[str, float] | None,
    current: Match,
    history: list[Match],
) -> dict[str, Any] | None:
    """Compare against Match-attached sources only after their own eligibility checks.

    The legacy lae and market arguments remain as source-selection flags;
    their values are never trusted. The authoritative vectors come from current.
    """
    refs = []
    if lae is not None and current.has_temporally_eligible_lae:
        vector = _validated_probability_vector(current.lae)
        if vector is not None:
            refs.append(("LAE", vector))
    if market is not None and current.has_temporally_eligible_market:
        vector = _validated_probability_vector(current.market)
        if vector is not None:
            refs.append(("mercado", vector))
    if not refs:
        return None
    m = np.array([model[s] for s in SIGNS])
    divergences = [float(np.abs(m - q).sum() / 2) for _, q in refs]
    score = max(divergences)
    if score < 0.18:
        return None
    best_model = SIGNS[int(np.argmax(m))]
    ref_name = refs[int(np.argmax(divergences))][0]
    reasons = [f"divergencia modelo vs {ref_name}: {score:.1%}"]
    prior_history = _prior_completed_matches(history, current)
    hf = _recent_form(prior_history, current.home)
    af = _recent_form(prior_history, current.away)
    if abs(hf - af) >= 1.5:
        reasons.append("diferencia relevante de forma reciente")
    return {"score": min(score / 0.5, 1.0), "fav_model": best_model, "reference": ref_name, "reasons": reasons}


def _recent_form(history: list[Match], team: str) -> float:
    xs = [
        match
        for match in history
        if (match.home == team or match.away == team)
        and match.home_goals is not None
        and match.away_goals is not None
    ][-5:]
    val = 0
    for m in xs:
        val += 3 if ((m.home == team and m.home_goals > m.away_goals) or (m.away == team and m.away_goals > m.home_goals)) else (1 if m.home_goals == m.away_goals else 0)
    return val / max(1, len(xs))


class TicketOptimizer:
    """SELAE direct-multiple optimizer under an independent-match approximation.

    Only double/triple counts authorized by the direct-method table are
    considered. Coverage is the probability that every match outcome belongs
    to its selected sign set; it is not expected payout or profitability.
    """

    MAX_AUTHORIZED_COLUMNS = 31_104
    MAX_TRIPLES_BY_DOUBLES: ClassVar[dict[int, int]] = {
        0: 9,
        1: 8,
        2: 8,
        3: 7,
        4: 6,
        5: 6,
        6: 5,
        7: 5,
        8: 4,
        9: 3,
        10: 3,
        11: 2,
        12: 1,
        13: 1,
        14: 0,
    }

    def __init__(
        self,
        price_per_column_eur: float = 0.75,
        minimum_columns: int = 2,
    ) -> None:
        try:
            price = float(price_per_column_eur)
        except (TypeError, ValueError) as exc:
            raise ValueError("price_per_column_eur must be finite and positive") from exc
        if isinstance(price_per_column_eur, bool) or not np.isfinite(price) or price <= 0.0:
            raise ValueError("price_per_column_eur must be finite and positive")
        if (
            isinstance(minimum_columns, bool)
            or not isinstance(minimum_columns, int)
            or minimum_columns < 2
        ):
            raise ValueError("minimum_columns must be an integer of at least 2")
        if minimum_columns > self.MAX_AUTHORIZED_COLUMNS:
            raise ValueError("minimum_columns exceeds the authorized direct-system maximum")
        self.price_per_column_eur = price
        self.minimum_columns = minimum_columns

    def optimize(self, predictions: list[dict[str, float]], budget: int = 8) -> dict[str, Any]:
        """Maximize full-ticket coverage within SELAE's direct-system table.

        Budget is the maximum number of 14-match columns. The current engine
        selects exactly one Pleno al 15 category pair, so its multiplier is 1.
        """
        if len(predictions) != 14:
            raise ValueError("standard ticket optimisation needs exactly 14 matches")
        if isinstance(budget, bool) or not isinstance(budget, int):
            raise TypeError("budget must be a positive integer number of columns")
        if budget < self.minimum_columns:
            raise ValueError(
                f"budget must be at least {self.minimum_columns} columns"
            )
        if budget > self.MAX_AUTHORIZED_COLUMNS:
            raise ValueError(
                f"budget must not exceed {self.MAX_AUTHORIZED_COLUMNS} authorized direct columns"
            )

        normalized: list[dict[str, float]] = []
        for index, prediction in enumerate(predictions, start=1):
            if not isinstance(prediction, dict):
                raise TypeError(f"match {index}: probabilities must be a mapping")
            missing_signs = [sign for sign in SIGNS if sign not in prediction]
            if missing_signs:
                raise ValueError(
                    f"match {index}: missing probability for sign(s): {', '.join(missing_signs)}"
                )

            values: dict[str, float] = {}
            for sign in SIGNS:
                raw = prediction[sign]
                if isinstance(raw, (bool, np.bool_)):
                    raise TypeError(f"match {index}: invalid probability for sign {sign}")
                try:
                    value = float(raw)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"match {index}: invalid probability for sign {sign}"
                    ) from exc
                if not np.isfinite(value) or value < 0.0 or value > 1.0:
                    raise ValueError(
                        f"match {index}: probability for sign {sign} must be finite and in [0, 1]"
                    )
                values[sign] = value

            total = sum(values.values())
            if total <= 0.0 or not np.isclose(total, 1.0, rtol=0.0, atol=1e-6):
                raise ValueError(
                    f"match {index}: 1/X/2 probabilities must sum to 1 (got {total:.8g})"
                )
            normalized.append({sign: values[sign] / total for sign in SIGNS})

        # State is (number of doubles, number of triples). The SELAE direct
        # table constrains the authorized triple count for each double count.
        # For a fixed state, the best sign subset at each match is its top-k.
        dp: dict[tuple[int, int], tuple[float, list[tuple[str, ...]]]] = {
            (0, 0): (0.0, [])
        }

        for probabilities in normalized:
            nxt: dict[tuple[int, int], tuple[float, list[tuple[str, ...]]]] = {}
            ordered = sorted(
                SIGNS,
                key=lambda sign: probabilities[sign],
                reverse=True,
            )

            for (double_count, triple_count), (log_mass, picks) in dp.items():
                for count in (1, 2, 3):
                    new_doubles = double_count + int(count == 2)
                    new_triples = triple_count + int(count == 3)
                    if new_triples > self.MAX_TRIPLES_BY_DOUBLES[new_doubles]:
                        continue

                    new_used = (2 ** new_doubles) * (3 ** new_triples)
                    if new_used > budget:
                        continue

                    signs = tuple(ordered[:count])
                    mass = sum(probabilities[sign] for sign in signs)
                    candidate = log_mass + float(np.log(max(mass, 1e-15)))
                    state = (new_doubles, new_triples)
                    previous = nxt.get(state)
                    if previous is None or candidate > previous[0]:
                        nxt[state] = (candidate, picks + [signs])

            dp = nxt

        eligible = {
            state: value
            for state, value in dp.items()
            if (2 ** state[0]) * (3 ** state[1]) >= self.minimum_columns
        }
        if not eligible:
            raise ValueError(
                f"budget {budget} cannot satisfy the {self.minimum_columns}-column minimum"
            )

        (double_count, triple_count), (log_mass, picks) = max(
            eligible.items(),
            key=lambda item: item[1][0],
        )
        used = (2 ** double_count) * (3 ** triple_count)
        columns = [
            [picks[j][mask[j]] for j in range(14)]
            for mask in np.ndindex(tuple(len(x) for x in picks))
        ]
        if len(columns) != used:
            raise RuntimeError("ticket column count does not match the optimizer state")

        independent_coverage = float(np.exp(log_mass))
        return {
            "budget": budget,
            "budget_unit": "columns",
            "columns": columns,
            "column_count": len(columns),
            "double_count": double_count,
            "triple_count": triple_count,
            "shape": tuple(len(x) for x in picks),
            # Legacy field retained for API compatibility; this is an independence product.
            "joint_coverage": independent_coverage,
            "independent_coverage_estimate": independent_coverage,
            "coverage_assumption": "independent_matches",
            "coverage_method": "product_of_marginal_selected_sign_masses",
            "system_method": "multiple_direct",
            "maximum_authorized_columns": self.MAX_AUTHORIZED_COLUMNS,
            "minimum_columns": self.minimum_columns,
            "price_per_column_eur": self.price_per_column_eur,
            "pleno15_multiplier": 1,
            "cost_eur": round(len(columns) * self.price_per_column_eur, 2),
        }


    @staticmethod
    def evaluate_joint_scenario_coverage(
        columns: Iterable[Iterable[str]],
        scenarios: Iterable[Iterable[str]],
        weights: Iterable[float] | None = None,
    ) -> dict[str, Any]:
        """Measure exact 14-match coverage against caller-supplied joint scenarios.

        Each scenario is one complete 14-match outcome vector. A scenario is
        covered only when that exact vector is present as a ticket column.
        Unlike optimize(), this evaluator makes no independence assumption.
        It excludes Pleno al 15 and never assembles scenarios from per-match
        marginal observations.
        """
        try:
            raw_columns = list(columns)
        except TypeError as exc:
            raise TypeError("columns must be an iterable of 14-sign columns") from exc
        if not raw_columns:
            raise ValueError("at least one ticket column is required")

        validated_columns: set[tuple[str, ...]] = set()
        for index, raw_column in enumerate(raw_columns, start=1):
            if isinstance(raw_column, (str, bytes)):
                raise TypeError(f"column {index} must be an iterable of 14 signs")
            try:
                column = tuple(raw_column)
            except TypeError as exc:
                raise TypeError(
                    f"column {index} must be an iterable of 14 signs"
                ) from exc
            if len(column) != 14:
                raise ValueError(f"column {index} must contain exactly 14 signs")
            if any(not isinstance(sign, str) or sign not in SIGNS for sign in column):
                raise ValueError(f"column {index} contains an invalid 1/X/2 sign")
            validated_columns.add(column)

        try:
            raw_scenarios = list(scenarios)
        except TypeError as exc:
            raise TypeError("scenarios must be an iterable of 14-outcome vectors") from exc
        if not raw_scenarios:
            raise ValueError("at least one joint scenario is required")

        validated_scenarios: list[tuple[str, ...]] = []
        for index, raw_scenario in enumerate(raw_scenarios, start=1):
            if isinstance(raw_scenario, (str, bytes)):
                raise TypeError(f"scenario {index} must be an iterable of 14 signs")
            try:
                scenario = tuple(raw_scenario)
            except TypeError as exc:
                raise TypeError(
                    f"scenario {index} must be an iterable of 14 signs"
                ) from exc
            if len(scenario) != 14:
                raise ValueError(f"scenario {index} must contain exactly 14 signs")
            if any(not isinstance(sign, str) or sign not in SIGNS for sign in scenario):
                raise ValueError(f"scenario {index} contains an invalid 1/X/2 sign")
            validated_scenarios.append(scenario)

        if weights is None:
            scenario_weights = np.ones(len(validated_scenarios), dtype=float)
            weighting = "uniform"
        else:
            try:
                raw_weights = list(weights)
            except TypeError as exc:
                raise TypeError(
                    "weights must be an iterable of finite non-negative numbers"
                ) from exc
            if len(raw_weights) != len(validated_scenarios):
                raise ValueError("weights length must match the number of scenarios")

            parsed_weights: list[float] = []
            for index, raw_weight in enumerate(raw_weights, start=1):
                if isinstance(raw_weight, (bool, np.bool_)):
                    raise TypeError(
                        f"weight {index} must be a finite non-negative number"
                    )
                try:
                    weight = float(raw_weight)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"weight {index} must be a finite non-negative number"
                    ) from exc
                if not np.isfinite(weight) or weight < 0.0:
                    raise ValueError(
                        f"weight {index} must be finite and non-negative"
                    )
                parsed_weights.append(weight)
            scenario_weights = np.asarray(parsed_weights, dtype=float)
            weighting = "explicit"

        # Scale before summing/squaring so very small/large finite weights
        # do not underflow or overflow aggregate calculations.
        weight_scale = float(scenario_weights.max())
        if weight_scale <= 0.0:
            raise ValueError("scenario weights must have a finite positive total")
        scaled_weights = scenario_weights / weight_scale
        scaled_total = float(scaled_weights.sum())
        squared_scaled_weight_sum = float(np.dot(scaled_weights, scaled_weights))
        if (
            not np.isfinite(scaled_total)
            or scaled_total <= 0.0
            or squared_scaled_weight_sum <= 0.0
            or weight_scale > np.finfo(float).max / scaled_total
        ):
            raise ValueError("scenario weights must have a finite positive total")
        total_weight = weight_scale * scaled_total

        covered = np.asarray(
            [scenario in validated_columns for scenario in validated_scenarios],
            dtype=bool,
        )
        covered_count = int(covered.sum())
        covered_scaled_weight = float(scaled_weights[covered].sum())
        covered_weight = covered_scaled_weight * weight_scale
        effective_sample_size = scaled_total**2 / squared_scaled_weight_sum

        return {
            "scenario_count": len(validated_scenarios),
            "unique_scenario_count": len(set(validated_scenarios)),
            "ticket_column_count": len(raw_columns),
            "unique_ticket_column_count": len(validated_columns),
            "duplicate_ticket_columns": len(raw_columns) - len(validated_columns),
            "covered_scenarios": covered_count,
            "uncovered_scenarios": len(validated_scenarios) - covered_count,
            "scenario_weight_sum": total_weight,
            "covered_scenario_weight": covered_weight,
            "effective_sample_size": float(effective_sample_size),
            "scenario_joint_coverage": covered_scaled_weight / scaled_total,
            "coverage_basis": "caller_supplied_joint_scenarios",
            "scenario_weighting": weighting,
            "scope": "14_main_matches_only",
        }


class KiniEngine:
    """Main pipeline: KinielaGPT data/context + Dixon-Coles + supervised ML + LAE/market ensemble."""

    def __init__(self, enable_ml: bool = False, enable_context: bool = False) -> None:
        self.dc = DixonColes()
        self.ml = FeatureModel() if enable_ml else None
        self.enable_ml = enable_ml
        self.enable_context = enable_context
        self.optimizer = TicketOptimizer()
        self.history: list[Match] = []
        self.fitted = False
        self.temperature = 1.0

    def fit(self, history: list[Match]) -> KiniEngine:
        self.history = sorted(history, key=lambda m: _date_num(m.date))
        self.dc.fit(self.history)
        if self.ml is not None and hasattr(self.ml, "invalidate"):
            self.ml.invalidate()
        self.fitted = True
        return self

    def _predict_one(
        self,
        m: Match,
        history: list[Match],
        mode: str = "ensemble",
        model_history: list[Match] | None = None,
    ) -> Prediction:
        dc_probs, scores = self.dc.predict(m.home, m.away)
        # The fitted estimator uses model_history; current features and context
        # use all results available before this fixture.
        needs_ml = mode in {"ml", "ensemble", "ensemble_dc_ml"}
        training_history = model_history if model_history is not None else history
        ml = (
            self.ml.fit_predict_proba(training_history, m, feature_history=history)
            if self.ml is not None and needs_ml else None
        )
        ml_probs = None if ml is None else dict(zip(SIGNS, map(float, ml)))
        # Raw odds remain on Match for audit diagnostics, but only explicitly
        # schedule-screened odds may influence a forecast.
        market_probs = m.market if m.has_temporally_eligible_market else None
        lae_probs = m.lae if m.has_temporally_eligible_lae else None
        if mode not in {"ensemble", "ensemble_dc_ml", "dc", "ml", "lae", "market"}:
            raise ValueError("mode must be one of: ensemble, ensemble_dc_ml, dc, ml, lae, market")

        if mode == "dc":
            base = dc_probs
        elif mode == "ml":
            if ml_probs is None:
                raise ValueError("ML mode requires enable_ml=True and sufficient history")
            base = ml_probs
        elif mode == "lae":
            if not lae_probs:
                raise ValueError(
                    "LAE probabilities are unavailable or not temporally verified"
                )
            base = _blend((lae_probs, 1.0))
        elif mode == "market":
            if not market_probs:
                raise ValueError("market probabilities are unavailable or not temporally eligible")
            base = _blend((market_probs, 1.0))
        elif mode == "ensemble_dc_ml":
            if ml_probs is None:
                raise ValueError("model-only ensemble requires valid ML probabilities")
            # Preserve the relative DC/ML weights of the existing ensemble,
            # normalized to 100%; market and LAE are deliberately excluded.
            base = _blend((dc_probs, 0.58), (ml_probs, 0.17))
        else:
            blend_items = [(dc_probs, 0.58)]
            if ml_probs:
                blend_items.append((ml_probs, 0.17))
            if lae_probs:
                blend_items.append((lae_probs, 0.18))
            if market_probs:
                blend_items.append((market_probs, 0.07))
            base = _blend(*blend_items)

        if self.enable_context and mode == "ensemble":
            adjusted, reasons = context_adjust(base, m, history)
        else:
            adjusted, reasons = base, []
        surprise = surprise_signal(adjusted, lae_probs, market_probs, m, history)
        sign = max(SIGNS, key=lambda s: adjusted[s])
        return Prediction(m.home, m.away, adjusted, sign, scores, surprise, reasons)

    def predict(
        self,
        match: Match,
        mode: str = "ensemble",
        history: list[Match] | None = None,
    ) -> Prediction:
        model_history = getattr(self, "history", None)
        feature_history = history if history is not None else model_history
        if feature_history is None:
            feature_history = []
        if model_history is None:
            model_history = feature_history
        return self._predict_one(
            match,
            feature_history,
            mode=mode,
            model_history=model_history,
        )

    def quiniela(self, fixtures: list[Match], budget: int = 8) -> dict[str, Any]:
        if len(fixtures) != 15:
            raise ValueError("Quiniela needs 15 fixtures")
        preds = [self._predict_one(m, self.history) for m in fixtures]
        ticket = self.optimizer.optimize([p.probabilities for p in preds[:14]], budget=budget)
        pleno_distribution = self.dc.pleno15_probs(
            fixtures[14].home,
            fixtures[14].away,
        )
        pleno_best = pleno_distribution[0]
        coverage_14 = float(ticket["joint_coverage"])
        pleno15_probability = float(pleno_best["probability"])

        return {
            "predictions": [p.__dict__ for p in preds],
            "ticket": ticket,
            "pleno_al_15": pleno_distribution,
            "pleno_al_15_best": pleno_best,
            "estimated_full_coupon_coverage_independent": (
                coverage_14 * pleno15_probability
            ),
            "full_coupon_coverage_assumption": (
                "independent_all_14_matches_and_pleno15"
            ),
        }
