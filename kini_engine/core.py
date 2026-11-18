from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import numpy as np
from scipy.stats import poisson

from .team_identity import normalize_team_name
from .ticket_ledger import TicketLedger
from .ticket_outcomes import (
    TicketOutcomeError,
    build_ticket_probability_vectors,
    validate_coupon_plan,
)

SIGNS = ("1", "X", "2")
LAE_SOURCE_ID = "quinielista.es:porcentajes_lae.asp"


class DixonColesFitError(RuntimeError):
    """Raised when Dixon-Coles cannot produce a validated fitted model."""
LAE_KICKOFF_EVIDENCE_MAX_AGE = timedelta(hours=24)


def _validated_probability_vector(probabilities: Any) -> np.ndarray | None:
    """Return an exact numeric 1/X/2 vector without silently repairing source data."""
    if not isinstance(probabilities, dict) or set(probabilities) != set(SIGNS):
        return None

    raw_values = [probabilities[sign] for sign in SIGNS]
    if any(
        isinstance(value, (bool, np.bool_))
        or not isinstance(value, (int, float, np.integer, np.floating))
        for value in raw_values
    ):
        return None

    try:
        values = np.asarray(raw_values, dtype=float)
    except (TypeError, ValueError, OverflowError):
        return None
    if (
        not np.isfinite(values).all()
        or np.any(values < 0.0)
        or np.any(values > 1.0)
        or not np.isclose(float(values.sum()), 1.0, rtol=0.0, atol=1e-6)
    ):
        return None
    return values


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


def _match_kickoff_utc(value: datetime | str, field: str) -> datetime:
    """Parse a fixture kickoff only when its timezone is explicit."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        raw = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise TicketOutcomeError(f"{field} must be an ISO-8601 kickoff") from exc
    else:
        raise TicketOutcomeError(f"{field} must be a timezone-aware kickoff")

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TicketOutcomeError(f"{field} must include a timezone offset")
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


def _assert_training_history_precedes_fixture(
    history: list[Match],
    current: Match,
    model_name: str,
) -> None:
    """Fail closed when a dated forecast's training snapshot contains future labels.

    Same-calendar-day results are excluded even when a kickoff time is present:
    the historical source does not consistently provide verified publication
    timestamps, so date-only grouping is the conservative point-in-time boundary.
    Undated live-analysis calls remain supported, but cannot be certified as
    historical point-in-time forecasts.
    """
    if isinstance(current.date, str) and not current.date.strip():
        return

    forecast_day = _calendar_date_key(current.date)
    leaking_days = [
        _calendar_date_key(match.date)
        for match in history
        if match.home_goals is not None
        and match.away_goals is not None
        and _calendar_date_key(match.date) >= forecast_day
    ]
    if leaking_days:
        first_leaking_day = min(leaking_days)
        raise ValueError(
            f"{model_name} training history must contain only completed results "
            f"strictly before forecast date {forecast_day}; found "
            f"{len(leaking_days)} result(s) on or after it "
            f"(earliest {first_leaking_day})"
        )


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
        self.fit_status = "not_fitted"
        self.fit_error: str | None = None
        self.n_training_matches = 0
        self.n_training_teams = 0
        self.log_likelihood: float | None = None
        self.aic: float | None = None

    def fit(self, matches: list[Match]) -> DixonColes:
        """Fit the model and validate optimizer state plus a real forecast."""
        self.fitted = False
        self.model = None
        self.teams = []
        self.fit_status = "fitting"
        self.fit_error = None
        self.log_likelihood = None
        self.aic = None

        usable = sorted(
            (m for m in matches if m.home_goals is not None and m.away_goals is not None),
            key=lambda m: _date_num(m.date),
        )
        self.n_training_matches = len(usable)
        self.n_training_teams = len({m.home for m in usable} | {m.away for m in usable})
        if len(usable) < 12:
            self.fit_status = "insufficient_history"
            self.fit_error = f"need at least 12 completed matches; received {len(usable)}"
            return self

        if (
            isinstance(self.decay, bool)
            or not np.isfinite(self.decay)
            or not 0.0 < float(self.decay) <= 1.0
        ):
            self.fit_status = "invalid_configuration"
            self.fit_error = "decay must be finite and in (0, 1]"
            raise ValueError(self.fit_error)

        try:
            from penaltyblog.models import DixonColesGoalModel, dixon_coles_weights

            self.teams = sorted({m.home for m in usable} | {m.away for m in usable})
            # penaltyblog expects datetime-like values because it computes timedelta.days.
            # Use the source calendar day, not the host-local timezone. Football-Data
            # dates are date-only; aware datetime inputs must remain reproducible
            # when the same history is fitted on runners in different timezones.
            dates = [
                datetime.fromisoformat(_calendar_date_key(m.date)) for m in usable
            ]
            weights = dixon_coles_weights(dates, xi=-np.log(float(self.decay)))

            model = DixonColesGoalModel(
                goals_home=np.asarray([m.home_goals for m in usable], dtype=float),
                goals_away=np.asarray([m.away_goals for m in usable], dtype=float),
                teams_home=np.asarray([m.home for m in usable], dtype=str),
                teams_away=np.asarray([m.away for m in usable], dtype=str),
                weights=weights,
            )
            model.fit(
                use_gradient=True,
                minimizer_options={"maxiter": 1000, "ftol": 1e-7},
            )
            if getattr(model, "fitted", False) is not True:
                raise RuntimeError("penaltyblog.fit() returned without model.fitted=True")

            log_likelihood = float(model.loglikelihood)
            aic = float(model.aic)
            if not np.isfinite(log_likelihood) or not np.isfinite(aic):
                raise RuntimeError("Dixon-Coles fit returned non-finite likelihood/AIC")

            probe = model.predict(
                usable[-1].home,
                usable[-1].away,
                max_goals=15,
                normalize=True,
            )
            grid = np.asarray(probe.grid, dtype=float)
            vector = np.asarray(probe.home_draw_away, dtype=float)
            if (
                grid.ndim != 2
                or grid.size == 0
                or not np.isfinite(grid).all()
                or np.any(grid < 0.0)
                or not np.isclose(float(grid.sum()), 1.0, rtol=0.0, atol=1e-6)
            ):
                raise RuntimeError("Dixon-Coles fit produced an invalid score grid")
            if (
                vector.shape != (3,)
                or not np.isfinite(vector).all()
                or np.any(vector < 0.0)
                or not np.isclose(float(vector.sum()), 1.0, rtol=0.0, atol=1e-6)
            ):
                raise RuntimeError("Dixon-Coles fit produced invalid 1/X/2 probabilities")
        except Exception as exc:
            self.model = None
            self.teams = []
            self.fitted = False
            self.fit_status = "fit_failed"
            self.fit_error = f"{type(exc).__name__}: {exc}"
            raise DixonColesFitError(
                f"Dixon-Coles fit failed with {len(usable)} completed matches: {self.fit_error}"
            ) from exc

        self.model = model
        self.teams = list(model.teams)
        self.fitted = True
        self.fit_status = "fitted"
        self.fit_error = None
        self.n_training_teams = len(self.teams)
        self.log_likelihood = log_likelihood
        self.aic = aic
        return self

    def prediction_source(self, home: str, away: str) -> str:
        """Identify trained forecasts and cold-start fallback cases."""
        if not self.fitted:
            return "untrained_fallback"
        if home not in self.teams or away not in self.teams:
            return "unseen_team_fallback"
        return "dixon_coles"

    def expected_goals(
        self,
        home: str,
        away: str,
        *,
        allow_untrained_fallback: bool = False,
        allow_unseen_team_fallback: bool = False,
    ) -> tuple[float, float]:
        source = self.prediction_source(home, away)
        if source == "untrained_fallback":
            if not allow_untrained_fallback:
                raise ValueError(
                    f"Dixon-Coles model is not fitted (fit_status={self.fit_status})"
                )
            return 1.35, 1.05
        if source == "unseen_team_fallback":
            if not allow_unseen_team_fallback:
                raise ValueError(
                    "Dixon-Coles cannot predict an unseen team without an explicit cold-start fallback"
                )
            return 1.35, 1.05

        pred = self.model.predict(home, away, max_goals=15, normalize=True)
        expected = np.asarray(
            [pred.home_goal_expectation, pred.away_goal_expectation], dtype=float
        )
        if not np.isfinite(expected).all() or np.any(expected <= 0.0):
            raise ValueError("Dixon-Coles returned invalid expected goals")
        return (
            float(np.clip(expected[0], 0.15, 5.0)),
            float(np.clip(expected[1], 0.15, 5.0)),
        )

    def _score_grid(
        self,
        home: str,
        away: str,
        *,
        allow_untrained_fallback: bool = False,
        allow_unseen_team_fallback: bool = False,
    ) -> np.ndarray:
        source = self.prediction_source(home, away)
        if source != "dixon_coles":
            lh, la = self.expected_goals(
                home,
                away,
                allow_untrained_fallback=allow_untrained_fallback,
                allow_unseen_team_fallback=allow_unseen_team_fallback,
            )
            return score_grid(lh, la, self.rho)

        prediction = self.model.predict(home, away, max_goals=15, normalize=True)
        grid = np.asarray(prediction.grid, dtype=float)
        total = float(grid.sum())
        if (
            not np.isfinite(grid).all()
            or np.any(grid < 0.0)
            or total <= 0.0
        ):
            raise ValueError("Dixon-Coles returned an invalid score grid")
        return grid / total

    def predict(
        self,
        home: str,
        away: str,
        *,
        allow_untrained_fallback: bool = False,
        allow_unseen_team_fallback: bool = False,
    ) -> tuple[dict[str, float], list[dict[str, Any]]]:
        source = self.prediction_source(home, away)
        if source != "dixon_coles":
            lh, la = self.expected_goals(
                home,
                away,
                allow_untrained_fallback=allow_untrained_fallback,
                allow_unseen_team_fallback=allow_unseen_team_fallback,
            )
            grid = score_grid(lh, la, self.rho)
            probabilities = grid_to_1x2(grid)
        else:
            prediction = self.model.predict(home, away, max_goals=15, normalize=True)
            grid = np.asarray(prediction.grid, dtype=float)
            vector = np.asarray(prediction.home_draw_away, dtype=float)
            if (
                grid.ndim != 2
                or not np.isfinite(grid).all()
                or np.any(grid < 0.0)
                or not np.isclose(float(grid.sum()), 1.0, rtol=0.0, atol=1e-6)
            ):
                raise ValueError("Dixon-Coles returned an invalid score grid")
            if (
                vector.shape != (3,)
                or not np.isfinite(vector).all()
                or np.any(vector < 0.0)
                or not np.isclose(float(vector.sum()), 1.0, rtol=0.0, atol=1e-6)
            ):
                raise ValueError("Dixon-Coles returned invalid 1/X/2 probabilities")
            probabilities = dict(zip(SIGNS, map(float, vector)))

        flat = [
            {"score": f"{h}-{a}", "probability": float(grid[h, a])}
            for h, a in np.ndindex(grid.shape)
        ]
        flat.sort(key=lambda item: item["probability"], reverse=True)
        return probabilities, flat[:10]

    def pleno15_probs(
        self,
        home: str,
        away: str,
        *,
        allow_untrained_fallback: bool = False,
        allow_unseen_team_fallback: bool = False,
    ) -> list[dict[str, Any]]:
        """Aggregate the score grid into SELAE Pleno al 15 goal categories."""
        grid = self._score_grid(
            home,
            away,
            allow_untrained_fallback=allow_untrained_fallback,
            allow_unseen_team_fallback=allow_unseen_team_fallback,
        )
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
        _assert_training_history_precedes_fixture(training_history, current, "ML")
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

    Input vectors must contain exactly numeric 1/X/2 probabilities. The
    optimizer does not coerce or silently renormalize source forecasts.
    The budget counts 14-match columns. Each selected Pleno category pair
    multiplies payable bets; the official cap applies after that multiplier.
    Coverage is not expected payout or profitability.
    """

    MAX_AUTHORIZED_TOTAL_BETS = 31_104
    # Backwards-compatible name; the statutory cap includes Pleno al 15.
    MAX_AUTHORIZED_COLUMNS = MAX_AUTHORIZED_TOTAL_BETS
    PLENO15_CATEGORIES: ClassVar[tuple[str, ...]] = ("0", "1", "2", "M")
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

    @classmethod
    def _normalize_pleno_categories(
        cls,
        categories: Iterable[str] | None,
        name: str,
    ) -> tuple[str, ...] | None:
        if categories is None:
            return None
        if isinstance(categories, (str, bytes)):
            raise TypeError(f"{name} must be an iterable of Pleno categories")
        try:
            values = list(categories)
        except TypeError as exc:
            raise TypeError(
                f"{name} must be an iterable of Pleno categories"
            ) from exc
        if not values:
            raise ValueError(f"{name} must contain at least one category")
        if any(
            not isinstance(category, str) or category not in cls.PLENO15_CATEGORIES
            for category in values
        ):
            raise ValueError(
                f"{name} contains an invalid Pleno category; use 0, 1, 2 or M"
            )
        if len(set(values)) != len(values):
            raise ValueError(f"{name} must not contain duplicate categories")
        return tuple(
            category for category in cls.PLENO15_CATEGORIES if category in values
        )

    def optimize(
        self,
        predictions: list[dict[str, float]],
        budget: int = 8,
        *,
        pleno15_home_categories: Iterable[str] | None = None,
        pleno15_away_categories: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        """Maximize 14-match coverage under the direct-system total-bet cap.

        The budget is the maximum number of 14-match columns. Payable bets
        equal column_count times the Pleno multiplier. The legacy
        minimum_columns setting is retained but applies to total bets.
        """
        if len(predictions) != 14:
            raise ValueError("standard ticket optimisation needs exactly 14 matches")
        if isinstance(budget, bool) or not isinstance(budget, int):
            raise TypeError(
                "budget must be a positive integer number of 14-match columns"
            )
        if budget < 1:
            raise ValueError("budget must be at least one 14-match column")
        if budget > self.MAX_AUTHORIZED_TOTAL_BETS:
            raise ValueError(
                f"budget must not exceed {self.MAX_AUTHORIZED_TOTAL_BETS} "
                "authorized direct columns"
            )

        home_categories = self._normalize_pleno_categories(
            pleno15_home_categories, "pleno15_home_categories"
        )
        away_categories = self._normalize_pleno_categories(
            pleno15_away_categories, "pleno15_away_categories"
        )
        if (home_categories is None) != (away_categories is None):
            raise ValueError(
                "home and away Pleno category sets must be supplied together"
            )
        pleno15_multiplier = (
            len(home_categories) * len(away_categories)
            if home_categories is not None and away_categories is not None
            else 1
        )
        if budget * pleno15_multiplier < self.minimum_columns:
            if pleno15_multiplier == 1:
                raise ValueError(
                    f"budget must be at least {self.minimum_columns} columns"
                )
            raise ValueError(
                "budget and Pleno multiplier cannot satisfy the minimum "
                f"of {self.minimum_columns} total bets"
            )

        validated_probabilities: list[dict[str, float]] = []
        for index, prediction in enumerate(predictions, start=1):
            if not isinstance(prediction, dict):
                raise TypeError(f"match {index}: probabilities must be a mapping")
            missing_signs = [sign for sign in SIGNS if sign not in prediction]
            if missing_signs:
                raise ValueError(
                    f"match {index}: missing probability for sign(s): {', '.join(missing_signs)}"
                )
            extra_signs = [sign for sign in prediction if sign not in SIGNS]
            if extra_signs:
                raise ValueError(
                    f"match {index}: unexpected probability key(s): {extra_signs!r}"
                )

            values: dict[str, float] = {}
            for sign in SIGNS:
                raw = prediction[sign]
                if isinstance(raw, (bool, np.bool_)) or not isinstance(
                    raw, (int, float, np.integer, np.floating)
                ):
                    raise TypeError(f"match {index}: invalid probability for sign {sign}")
                value = float(raw)
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
            # The 1e-6 sum tolerance is validation only. Preserve source values:
            # do not coerce strings or silently renormalize a forecast vector.
            validated_probabilities.append({sign: values[sign] for sign in SIGNS})

        # State is (number of doubles, number of triples). The SELAE direct
        # table constrains triples; the 31,104 cap also applies after Pleno.
        dp: dict[tuple[int, int], tuple[float, list[tuple[str, ...]]]] = {
            (0, 0): (0.0, [])
        }

        for probabilities in validated_probabilities:
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

                    new_columns = (2**new_doubles) * (3**new_triples)
                    new_total_bets = new_columns * pleno15_multiplier
                    if (
                        new_columns > budget
                        or new_total_bets > self.MAX_AUTHORIZED_TOTAL_BETS
                    ):
                        continue

                    signs = tuple(ordered[:count])
                    mass = sum(probabilities[sign] for sign in signs)
                    if mass <= 0.0:
                        raise RuntimeError(
                            "validated probability vector produced zero selected mass"
                        )
                    candidate = log_mass + float(np.log(mass))
                    state = (new_doubles, new_triples)
                    previous = nxt.get(state)
                    if previous is None or candidate > previous[0]:
                        nxt[state] = (candidate, picks + [signs])

            dp = nxt

        eligible = {
            state: value
            for state, value in dp.items()
            if (
                (2**state[0])
                * (3**state[1])
                * pleno15_multiplier
                >= self.minimum_columns
            )
        }
        if not eligible:
            raise ValueError(
                f"budget {budget} cannot satisfy the {self.minimum_columns}-bet "
                "minimum and SELAE total-bet cap"
            )

        (double_count, triple_count), (log_mass, picks) = max(
            eligible.items(),
            key=lambda item: item[1][0],
        )
        used = (2**double_count) * (3**triple_count)
        total_bets = used * pleno15_multiplier
        columns = [
            [picks[j][mask[j]] for j in range(14)]
            for mask in np.ndindex(tuple(len(x) for x in picks))
        ]
        if len(columns) != used:
            raise RuntimeError("ticket column count does not match the optimizer state")
        if total_bets > self.MAX_AUTHORIZED_TOTAL_BETS:
            raise RuntimeError("ticket exceeds SELAE's authorized total-bet cap")

        independent_coverage = float(np.exp(log_mass))
        pleno15_combinations = (
            [
                {"home_goals": home, "away_goals": away}
                for home in home_categories
                for away in away_categories
            ]
            if home_categories is not None and away_categories is not None
            else None
        )
        return {
            "budget": budget,
            "budget_unit": "columns",
            "budget_scope": "14_match_columns",
            "columns": columns,
            "column_count": len(columns),
            "total_bets": total_bets,
            "double_count": double_count,
            "triple_count": triple_count,
            "shape": tuple(len(x) for x in picks),
            # Legacy field retained for API compatibility; this is an independence product.
            "joint_coverage": independent_coverage,
            "independent_coverage_estimate": independent_coverage,
            "coverage_assumption": "independent_matches",
            "coverage_method": "product_of_marginal_selected_sign_masses",
            "system_method": "multiple_direct",
            "maximum_authorized_columns": (
                self.MAX_AUTHORIZED_TOTAL_BETS // pleno15_multiplier
            ),
            "maximum_authorized_14_match_columns": (
                self.MAX_AUTHORIZED_TOTAL_BETS // pleno15_multiplier
            ),
            "maximum_authorized_total_bets": self.MAX_AUTHORIZED_TOTAL_BETS,
            "minimum_columns": self.minimum_columns,
            "minimum_total_bets": self.minimum_columns,
            "price_per_column_eur": self.price_per_column_eur,
            "price_per_bet_eur": self.price_per_column_eur,
            "pleno15_multiplier": pleno15_multiplier,
            "pleno15_home_categories": (
                list(home_categories) if home_categories is not None else None
            ),
            "pleno15_away_categories": (
                list(away_categories) if away_categories is not None else None
            ),
            "pleno15_combinations": pleno15_combinations,
            "cost_eur": round(total_bets * self.price_per_column_eur, 2),
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

    def __init__(
        self,
        enable_ml: bool = False,
        enable_context: bool = False,
        ticket_ledger: TicketLedger | None = None,
    ) -> None:
        self.dc = DixonColes()
        self.ml = FeatureModel() if enable_ml else None
        self.enable_ml = enable_ml
        self.enable_context = enable_context
        self.optimizer = TicketOptimizer()
        self.history: list[Match] = []
        self.fitted = False
        self.dc_fit_error: str | None = None
        self.temperature = 1.0
        self.ticket_ledger = ticket_ledger

    def fit(self, history: list[Match]) -> KiniEngine:
        self.history = sorted(history, key=lambda m: _date_num(m.date))
        self.dc_fit_error: str | None = None
        try:
            self.dc.fit(self.history)
        except DixonColesFitError as exc:
            # Keep the failure visible while allowing independent ML/market/LAE modes.
            self.dc_fit_error = str(exc)
        if self.ml is not None and hasattr(self.ml, "invalidate"):
            self.ml.invalidate()
        self.fitted = bool(self.dc.fitted)
        return self

    def model_diagnostics(self) -> dict[str, Any]:
        """Return explicit per-model fit state rather than inferring readiness."""
        return {
            "history_loaded": bool(self.history),
            "dixon_coles": {
                "fitted": self.dc.fitted,
                "status": self.dc.fit_status,
                "training_matches": self.dc.n_training_matches,
                "training_teams": self.dc.n_training_teams,
                "log_likelihood": self.dc.log_likelihood,
                "aic": self.dc.aic,
                "error": self.dc.fit_error or self.dc_fit_error,
            },
            "ml_enabled": self.ml is not None,
        }

    def _predict_one(
        self,
        m: Match,
        history: list[Match],
        mode: str = "ensemble",
        model_history: list[Match] | None = None,
    ) -> Prediction:
        allowed_modes = {
            "ensemble", "ensemble_dc_ml", "dc", "ml", "lae", "market"
        }
        if mode not in allowed_modes:
            raise ValueError(
                "mode must be one of: ensemble, ensemble_dc_ml, dc, ml, lae, market"
            )

        needs_dc = mode in {"ensemble", "ensemble_dc_ml", "dc"}
        dc_reasons: list[str] = []
        if needs_dc:
            _assert_training_history_precedes_fixture(
                self.history, m, "Dixon-Coles"
            )
            if not self.dc.fitted:
                reason = self.dc.fit_error or self.dc_fit_error or self.dc.fit_status
                raise ValueError(
                    "Dixon-Coles model is not available for this forecast "
                    f"(fit_status={self.dc.fit_status}; reason={reason})"
                )
            dc_source = self.dc.prediction_source(m.home, m.away)
            dc_probs, scores = self.dc.predict(
                m.home,
                m.away,
                allow_unseen_team_fallback=True,
            )
            if dc_source == "unseen_team_fallback":
                dc_reasons.append(
                    "Dixon-Coles cold-start fallback used for an unseen team"
                )
        else:
            dc_probs, scores = None, []

        # ML has its own fit lifecycle and can run when Dixon-Coles is unavailable.
        needs_ml = mode in {"ml", "ensemble", "ensemble_dc_ml"}
        training_history = model_history if model_history is not None else history
        ml = (
            self.ml.fit_predict_proba(
                training_history, m, feature_history=history
            )
            if self.ml is not None and needs_ml else None
        )
        ml_probs = None if ml is None else dict(zip(SIGNS, map(float, ml)))
        # Raw odds remain on Match for audit diagnostics, but only explicitly
        # schedule-screened odds may influence a forecast.
        market_probs = m.market if m.has_temporally_eligible_market else None
        lae_probs = m.lae if m.has_temporally_eligible_lae else None

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
                raise ValueError(
                    "market probabilities are unavailable or not temporally eligible"
                )
            base = _blend((market_probs, 1.0))
        elif mode == "ensemble_dc_ml":
            if dc_probs is None or ml_probs is None:
                raise ValueError(
                    "model-only ensemble requires fitted DC and valid ML probabilities"
                )
            base = _blend((dc_probs, 0.58), (ml_probs, 0.17))
        else:
            if dc_probs is None:
                raise ValueError("ensemble mode requires a fitted Dixon-Coles model")
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
        reasons.extend(dc_reasons)
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

    def quiniela(
        self,
        fixtures: list[Match],
        budget: int = 8,
        *,
        pleno15_home_categories: Iterable[str] | None = None,
        pleno15_away_categories: Iterable[str] | None = None,
        coupon_plan: dict[str, Any] | None = None,
        public_draw_snapshots: Mapping[int, dict[str, Any]] | None = None,
        ticket_id: str | None = None,
    ) -> dict[str, Any]:
        """Generate a coupon with optional strict pre-ticket evidence validation.

        With a coupon plan, the first 14 fixtures are matched by exact normalized
        team labels and timezone-aware kickoffs. Football forecasts are generated
        only for scheduled positions. Public-draw positions require their own
        pre-ticket SELAE participant snapshot and never enter the football model.
        The Pleno al 15 kickoff is independently checked.
        """
        if len(fixtures) != 15:
            raise ValueError("Quiniela needs 15 fixtures")

        probability_vectors: dict[str, Any] | None = None
        normalized_plan: dict[str, Any] | None = None
        preds: list[Prediction | None] = []

        if coupon_plan is None:
            if public_draw_snapshots is not None or ticket_id is not None:
                raise TicketOutcomeError(
                    "public-draw snapshots and ticket_id require a pre-ticket coupon plan"
                )
            preds = [self._predict_one(match, self.history) for match in fixtures]
            optimizer_probabilities = [
                prediction.probabilities
                for prediction in preds[:14]
                if prediction is not None
            ]
        else:
            if not isinstance(coupon_plan, dict) or not isinstance(
                coupon_plan.get("draw_date"), str
            ):
                raise TicketOutcomeError(
                    "pre-ticket coupon plan must contain an ISO draw_date"
                )
            draw_date = coupon_plan["draw_date"]
            normalized_plan = validate_coupon_plan(coupon_plan, draw_date)

            for position, match in enumerate(fixtures[:14], start=1):
                planned = normalized_plan["positions"][position]
                if (
                    normalize_team_name(match.home)
                    != normalize_team_name(planned["home"])
                    or normalize_team_name(match.away)
                    != normalize_team_name(planned["away"])
                ):
                    raise TicketOutcomeError(
                        f"fixture {position} home/away identity or coupon order "
                        "does not match the pre-ticket plan"
                    )
                actual_kickoff = _match_kickoff_utc(
                    match.date, f"fixture {position}.kickoff"
                )
                if actual_kickoff != planned["kickoff_at"].astimezone(UTC):
                    raise TicketOutcomeError(
                        f"fixture {position} kickoff does not match the pre-ticket plan"
                    )

            pleno_fixture = fixtures[14]
            if (
                normalize_team_name(pleno_fixture.home)
                != normalize_team_name(normalized_plan["pleno15_home"])
                or normalize_team_name(pleno_fixture.away)
                != normalize_team_name(normalized_plan["pleno15_away"])
            ):
                raise TicketOutcomeError(
                    "Pleno al 15 home/away identity does not match the pre-ticket plan"
                )
            if _match_kickoff_utc(
                pleno_fixture.date, "Pleno al 15 kickoff"
            ) != normalized_plan["pleno15_kickoff_at"].astimezone(UTC):
                raise TicketOutcomeError(
                    "Pleno al 15 kickoff does not match the pre-ticket plan"
                )

            model_probabilities_by_position: dict[int, dict[str, float]] = {}
            for position, match in enumerate(fixtures[:14], start=1):
                if position in normalized_plan["public_draw_positions"]:
                    preds.append(None)
                    continue
                prediction = self._predict_one(match, self.history)
                preds.append(prediction)
                model_probabilities_by_position[position] = prediction.probabilities

            # Fixture 15 is the separate Pleno al 15 football match.
            preds.append(self._predict_one(pleno_fixture, self.history))
            probability_vectors = build_ticket_probability_vectors(
                draw_date=draw_date,
                coupon_plan=coupon_plan,
                model_probabilities_by_position=model_probabilities_by_position,
                public_draw_snapshots=(
                    public_draw_snapshots
                    if public_draw_snapshots is not None
                    else {}
                ),
            )
            for source in probability_vectors["probability_sources"]:
                if source["source"] == "football_model":
                    source["model_mode"] = "ensemble"
            optimizer_probabilities = probability_vectors["probabilities"]

        pleno_source = self.dc.prediction_source(
            fixtures[14].home,
            fixtures[14].away,
        )
        pleno_distribution = self.dc.pleno15_probs(
            fixtures[14].home,
            fixtures[14].away,
            allow_unseen_team_fallback=True,
        )
        pleno_best = pleno_distribution[0]
        if pleno15_home_categories is None and pleno15_away_categories is None:
            # Preserve the existing default: one best joint Pleno category pair.
            pleno15_home_categories = (str(pleno_best["home_goals"]),)
            pleno15_away_categories = (str(pleno_best["away_goals"]),)

        ticket = self.optimizer.optimize(
            optimizer_probabilities,
            budget=budget,
            pleno15_home_categories=pleno15_home_categories,
            pleno15_away_categories=pleno15_away_categories,
        )
        selected_pairs = {
            (item["home_goals"], item["away_goals"])
            for item in ticket["pleno15_combinations"]
        }
        selected_distribution = [
            item
            for item in pleno_distribution
            if (item["home_goals"], item["away_goals"]) in selected_pairs
        ]
        selected_pleno_probability = float(
            sum(item["probability"] for item in selected_distribution)
        )
        if not selected_distribution or not 0.0 < selected_pleno_probability <= 1.0:
            raise RuntimeError("selected Pleno categories have invalid probability mass")

        coverage_14 = float(ticket["joint_coverage"])
        result: dict[str, Any] = {
            "predictions": [
                None if prediction is None else prediction.__dict__
                for prediction in preds
            ],
            "ticket": ticket,
            "pleno_al_15": pleno_distribution,
            "pleno_al_15_best": pleno_best,
            "pleno_al_15_selected": selected_distribution,
            "pleno_al_15_selected_probability": selected_pleno_probability,
            "pleno_al_15_selected_categories": {
                "home": ticket["pleno15_home_categories"],
                "away": ticket["pleno15_away_categories"],
            },
            "pleno_al_15_model_source": pleno_source,
            "estimated_full_coupon_coverage_independent": (
                coverage_14 * selected_pleno_probability
            ),
            "full_coupon_coverage_assumption": (
                "independent_all_14_matches_and_selected_pleno15_categories"
            ),
        }

        if probability_vectors is not None and normalized_plan is not None:
            ticket_payload: dict[str, Any] = {
                "schema_version": 1,
                "draw_date": probability_vectors["draw_date"],
                "ticket_created_at_utc": probability_vectors["ticket_created_at_utc"],
                "ticket_cutoff_at_utc": probability_vectors["ticket_cutoff_at_utc"],
                "first_kickoff_at": probability_vectors["first_kickoff_at"],
                "cutoff_evidence_url": normalized_plan["cutoff_evidence_url"],
                "cutoff_evidence_sha256": normalized_plan["cutoff_evidence_sha256"],
                "cutoff_evidence_captured_at_utc": (
                    normalized_plan["cutoff_evidence_captured_at_utc"]
                    .isoformat()
                    .replace("+00:00", "Z")
                ),
                "schedule_evidence_url": normalized_plan["schedule_evidence_url"],
                "schedule_evidence_sha256": normalized_plan["schedule_evidence_sha256"],
                "schedule_evidence_captured_at_utc": (
                    normalized_plan["schedule_captured_at_utc"]
                    .isoformat()
                    .replace("+00:00", "Z")
                ),
                "pleno15_home": normalized_plan["pleno15_home"],
                "pleno15_away": normalized_plan["pleno15_away"],
                "pleno15_kickoff_at": probability_vectors["pleno15_kickoff_at"],
                "coupon_plan": coupon_plan,
                "probability_vectors": probability_vectors["probabilities"],
                "probability_sources": probability_vectors["probability_sources"],
                "public_draw_positions": probability_vectors["public_draw_positions"],
                "columns": ticket["columns"],
                "pleno15_combinations": ticket["pleno15_combinations"],
                "budget": ticket["budget"],
                "cost_eur": ticket["cost_eur"],
            }
            identity_payload = json.dumps(
                ticket_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            identity_hash = hashlib.sha256(identity_payload.encode("utf-8")).hexdigest()
            if ticket_id is None:
                ticket_id = f"{probability_vectors['draw_date']}:{identity_hash[:16]}"
            elif not isinstance(ticket_id, str) or not ticket_id.strip():
                raise TicketOutcomeError("ticket_id must be a non-empty string")
            ticket_payload["ticket_id"] = ticket_id.strip()
            ticket_record_json = json.dumps(
                ticket_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            ticket_record_sha256 = hashlib.sha256(
                ticket_record_json.encode("utf-8")
            ).hexdigest()
            ticket_ledger_receipt = None
            if self.ticket_ledger is not None:
                ticket_ledger_receipt = self.ticket_ledger.append_ticket(
                    ticket_payload,
                    expected_sha256=ticket_record_sha256,
                )
            result.update(
                {
                    "ticket_id": ticket_payload["ticket_id"],
                    "ticket_record": ticket_payload,
                    "ticket_record_sha256": ticket_record_sha256,
                    "ticket_probability_vectors": probability_vectors["probabilities"],
                    "ticket_probability_sources": probability_vectors["probability_sources"],
                    "public_draw_positions": probability_vectors["public_draw_positions"],
                    "coupon_plan": coupon_plan,
                }
            )
            if ticket_ledger_receipt is not None:
                result["ticket_ledger"] = ticket_ledger_receipt

        return result
