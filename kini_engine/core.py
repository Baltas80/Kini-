from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from math import exp
from typing import Any, Iterable

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson


SIGNS = ("1", "X", "2")


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

    def fit(self, matches: list[Match]) -> "DixonColes":
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


class FeatureModel:
    """Compact supervised model using only pre-match information."""

    def __init__(self) -> None:
        self.model: Any = None
        self.teams: dict[str, int] = {}

    def _features(self, history: list[Match], m: Match) -> np.ndarray:
        def stats(team: str, venue: str | None = None) -> tuple[float, float, float]:
            xs = [x for x in history if (x.home == team or x.away == team) and x.home_goals is not None and x.away_goals is not None]
            if venue == "home":
                xs = [x for x in xs if x.home == team]
            elif venue == "away":
                xs = [x for x in xs if x.away == team]
            xs = xs[-8:]
            if not xs:
                return 0.0, 1.35, 1.05
            pts = gf = ga = 0.0
            for x in xs:
                gf += x.home_goals if x.home == team else x.away_goals
                ga += x.away_goals if x.home == team else x.home_goals
                pts += 3 if ((x.home == team and x.home_goals > x.away_goals) or (x.away == team and x.away_goals > x.home_goals)) else (1 if x.home_goals == x.away_goals else 0)
            return pts / len(xs), gf / len(xs), ga / len(xs)

        hp, hgf, hga = stats(m.home)
        ap, agf, aga = stats(m.away)
        hhp, hhgf, hhga = stats(m.home, "home")
        aap, aagf, aaga = stats(m.away, "away")
        pos_h = float(m.detail.get("clasificacion_local_pos", 0) or 0)
        pos_a = float(m.detail.get("clasificacion_visitante_pos", 0) or 0)
        return np.array([hp, hgf, hga, ap, agf, aga, hhp, hhgf, hhga, aap, aagf, aaga, pos_h, pos_a, pos_h - pos_a], dtype=float)

    def fit_predict_proba(self, history: list[Match], current: Match) -> np.ndarray | None:
        rows, y = [], []
        for i, m in enumerate(history):
            if m.home_goals is None or m.away_goals is None:
                continue
            rows.append(self._features(history[:i], m))
            y.append(m.outcome())
        if len(rows) < 40 or len(set(y)) < 3:
            return None
        try:
            from xgboost import XGBClassifier
            self.model = XGBClassifier(
                n_estimators=180, max_depth=4, learning_rate=0.04,
                subsample=0.85, colsample_bytree=0.85, objective="multi:softprob",
                num_class=3, eval_metric="mlogloss", random_state=42
            )
        except Exception:
            from sklearn.ensemble import HistGradientBoostingClassifier
            self.model = HistGradientBoostingClassifier(max_iter=180, learning_rate=0.05, max_leaf_nodes=15, random_state=42)
        enc = {"1": 0, "X": 1, "2": 2}
        self.model.fit(np.vstack(rows), np.asarray([enc[v] for v in y]))
        return _norm(self.model.predict_proba(self._features(history, current))[0])


def context_adjust(
    probs: dict[str, float],
    current: Match,
    history: list[Match],
) -> tuple[dict[str, float], list[str]]:
    p = np.array([probs[s] for s in SIGNS], dtype=float)
    reasons: list[str] = []

    def form(team: str) -> float:
        xs = [m for m in history if (m.home == team or m.away == team) and m.home_goals is not None and m.away_goals is not None][-5:]
        val = 0.0
        for m in xs:
            if m.home == team:
                val += 3 if m.home_goals > m.away_goals else (1 if m.home_goals == m.away_goals else 0)
            else:
                val += 3 if m.away_goals > m.home_goals else (1 if m.home_goals == m.away_goals else 0)
        return val / max(1, len(xs))

    hf, af = form(current.home), form(current.away)
    delta = float(np.clip((hf - af) * 0.025, -0.08, 0.08))
    if abs(delta) >= 0.025:
        p += np.array([delta, -abs(delta) * 0.25, -delta])
        reasons.append(f"forma reciente: {current.home} {hf:.2f} vs {current.away} {af:.2f}")

    h2h = [m for m in history if {m.home, m.away} == {current.home, current.away} and m.home_goals is not None and m.away_goals is not None]
    if len(h2h) >= 5:
        local_wins = sum(1 for m in h2h[-10:] if m.home == current.home and m.home_goals > m.away_goals)
        draw = sum(1 for m in h2h[-10:] if m.home_goals == m.away_goals)
        away_wins = sum(1 for m in h2h[-10:] if m.away == current.home and m.away_goals > m.home_goals)
        hp = _norm([local_wins, draw, away_wins])
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
    refs = []
    for name, probs in (("LAE", lae), ("mercado", market)):
        if probs:
            refs.append((name, np.array([probs.get(s, 0.0) for s in SIGNS])))
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
    hf = _recent_form(history, current.home)
    af = _recent_form(history, current.away)
    if abs(hf - af) >= 1.5:
        reasons.append("diferencia relevante de forma reciente")
    return {"score": min(score / 0.5, 1.0), "fav_model": best_model, "reference": ref_name, "reasons": reasons}


def _recent_form(history: list[Match], team: str) -> float:
    xs = [m for m in history if m.home == team or m.away == team][-5:]
    val = 0
    for m in xs:
        val += 3 if ((m.home == team and m.home_goals > m.away_goals) or (m.away == team and m.away_goals > m.home_goals)) else (1 if m.home_goals == m.away_goals else 0)
    return val / max(1, len(xs))


class TicketOptimizer:
    """Exact budget-constrained optimizer for the 14 standard matches."""

    def optimize(self, predictions: list[dict[str, float]], budget: int = 8) -> dict[str, Any]:
        if len(predictions) != 14:
            raise ValueError("standard ticket optimisation needs exactly 14 matches")
        if not isinstance(budget, int) or budget < 1:
            raise ValueError("budget must be a positive integer")

        # A single, double or triple contributes respectively 1, 2 or 3
        # columns. For a fixed selection of signs, the covered probability is
        # the product of the selected marginal masses. Maximising its log turns
        # the problem into a small exact dynamic programme over column budget.
        dp: dict[int, tuple[float, list[tuple[str, ...]]]] = {1: (0.0, [])}

        for p in predictions:
            nxt: dict[int, tuple[float, list[tuple[str, ...]]]] = {}
            ordered = sorted(SIGNS, key=lambda sign: float(p.get(sign, 0.0)), reverse=True)

            for used, (log_mass, picks) in dp.items():
                for k in (1, 2, 3):
                    new_used = used * k
                    if new_used > budget:
                        continue
                    signs = tuple(ordered[:k])
                    mass = max(sum(float(p.get(sign, 0.0)) for sign in signs), 1e-15)
                    candidate = log_mass + float(np.log(mass))
                    previous = nxt.get(new_used)
                    if previous is None or candidate > previous[0]:
                        nxt[new_used] = (candidate, picks + [signs])

            dp = nxt

        if not dp:
            raise ValueError(f"budget {budget} cannot represent a 14-match ticket")

        used, (log_mass, picks) = max(dp.items(), key=lambda item: item[1][0])
        columns = [
            [picks[j][mask[j]] for j in range(14)]
            for mask in np.ndindex(tuple(len(x) for x in picks))
        ]

        return {
            "budget": budget,
            "columns": columns,
            "column_count": len(columns),
            "shape": tuple(len(x) for x in picks),
            "joint_coverage": float(np.exp(log_mass)),
        }


class KiniEngine:
    """Main pipeline: KinielaGPT data/context + Dixon-Coles + supervised ML + LAE/market ensemble."""

    def __init__(self, enable_ml: bool = False, enable_context: bool = False) -> None:
        self.dc = DixonColes()
        self.ml = FeatureModel() if enable_ml else None
        self.enable_ml = enable_ml
        self.enable_context = enable_context
        self.optimizer = TicketOptimizer()
        self.fitted = False
        self.temperature = 1.0

    def fit(self, history: list[Match]) -> "KiniEngine":
        self.history = sorted(list(history), key=lambda m: _date_num(m.date))
        self.dc.fit(self.history)
        self.fitted = True
        return self

    def _predict_one(self, m: Match, history: list[Match], mode: str = "ensemble") -> Prediction:
        dc_probs, scores = self.dc.predict(m.home, m.away)
        ml = self.ml.fit_predict_proba(history, m) if self.ml is not None else None
        ml_probs = None if ml is None else dict(zip(SIGNS, map(float, ml)))
        if mode not in {"ensemble", "dc", "ml", "lae", "market"}:
            raise ValueError("mode must be one of: ensemble, dc, ml, lae, market")

        if mode == "dc":
            base = dc_probs
        elif mode == "ml":
            if ml_probs is None:
                raise ValueError("ML mode requires enable_ml=True and sufficient history")
            base = ml_probs
        elif mode == "lae":
            if not m.lae:
                raise ValueError("LAE probabilities are unavailable")
            base = _blend((m.lae, 1.0))
        elif mode == "market":
            if not m.market:
                raise ValueError("market probabilities are unavailable")
            base = _blend((m.market, 1.0))
        else:
            blend_items = [(dc_probs, 0.58)]
            if ml_probs:
                blend_items.append((ml_probs, 0.17))
            if m.lae:
                blend_items.append((m.lae, 0.18))
            if m.market:
                blend_items.append((m.market, 0.07))
            base = _blend(*blend_items)

        if self.enable_context and mode == "ensemble":
            adjusted, reasons = context_adjust(base, m, history)
        else:
            adjusted, reasons = base, []
        surprise = surprise_signal(adjusted, m.lae, m.market, m, history)
        sign = max(SIGNS, key=lambda s: adjusted[s])
        return Prediction(m.home, m.away, adjusted, sign, scores, surprise, reasons)

    def predict(self, match: Match, mode: str = "ensemble") -> Prediction:
        return self._predict_one(match, getattr(self, "history", []), mode=mode)

    def quiniela(self, fixtures: list[Match], budget: int = 8) -> dict[str, Any]:
        if len(fixtures) != 15:
            raise ValueError("Quiniela needs 15 fixtures")
        preds = [self._predict_one(m, self.history) for m in fixtures]
        ticket = self.optimizer.optimize([p.probabilities for p in preds[:14]], budget=budget)
        return {
            "predictions": [p.__dict__ for p in preds],
            "ticket": ticket,
            "pleno_al_15": preds[14].scorelines[:8],
        }
