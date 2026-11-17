from __future__ import annotations

from typing import Any

from .core import KiniEngine, Match
from .sources import KinielaGPTAuthorizationRequired, KinielaGPTSource

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = None  # type: ignore[assignment]


def create_server(engine: KiniEngine | None = None):
    if FastMCP is None:
        raise RuntimeError("Install kini-engine[mcp] to use the MCP server")

    mcp = FastMCP("Kini")
    model = engine or KiniEngine()
    source = KinielaGPTSource()

    @mcp.tool()
    def get_last_quiniela() -> dict[str, Any]:
        jornada, temporada, matches = source.last()
        return {
            "jornada": jornada,
            "temporada": temporada,
            "matches": matches,
            "round_resolution": source.last_round_resolution,
        }

    @mcp.tool()
    def get_quiniela(jornada: int, temporada: int) -> dict[str, Any]:
        probabilities = source.probabilities(jornada, temporada)
        try:
            details = source.details(jornada, temporada)
            details_status = "ok"
            details_error = None
        except KinielaGPTAuthorizationRequired as exc:
            details = []
            details_status = "blocked_missing_authorization"
            details_error = str(exc)
        return {
            "jornada": jornada,
            "temporada": temporada,
            "matches": probabilities,
            "details": details,
            "details_status": details_status,
            "details_error": details_error,
        }

    @mcp.tool()
    def get_probabilities(jornada: int, temporada: int) -> list[dict[str, Any]]:
        return source.probabilities(jornada, temporada)

    @mcp.tool()
    def analyze_match(home: str, away: str) -> dict[str, Any]:
        return model.predict(Match("", home, away)).__dict__

    @mcp.tool()
    def analyze_team(team: str) -> dict[str, Any]:
        history = getattr(model, "history", [])
        matches = [m for m in history if m.home == team or m.away == team][-10:]
        wins = draws = losses = goals_for = goals_against = 0
        for m in matches:
            if m.home_goals is None or m.away_goals is None:
                continue
            if m.home == team:
                gf, ga = m.home_goals, m.away_goals
            else:
                gf, ga = m.away_goals, m.home_goals
            goals_for += gf
            goals_against += ga
            if gf > ga:
                wins += 1
            elif gf == ga:
                draws += 1
            else:
                losses += 1
        n = wins + draws + losses
        return {
            "team": team,
            "matches": n,
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "goals_for": goals_for,
            "goals_against": goals_against,
            "points_per_match": (3 * wins + draws) / n if n else 0.0,
        }

    @mcp.tool()
    def detect_surprises(jornada: int, temporada: int) -> list[dict[str, Any]]:
        rows = source.probabilities(jornada, temporada)
        out = []
        for row in rows:
            home = row.get("local", "")
            away = row.get("visitante", "")
            if not home or not away:
                continue
            lae = row.get("lae")
            detail = {
                "lae_source": row.get("lae_source"),
                "lae_captured_at": row.get("lae_captured_at"),
                "kickoff_at": row.get("kickoff_at"),
                "kickoff_source": row.get("kickoff_source"),
                "kickoff_evidence_url": row.get("kickoff_evidence_url"),
                "kickoff_evidence_checked_at_utc": row.get(
                    "kickoff_evidence_checked_at_utc"
                ),
                "kickoff_timezone": row.get("kickoff_timezone"),
                "fixture_identity_status": row.get("fixture_identity_status"),
            }
            current = Match(
                row.get("kickoff_at") or "",
                home,
                away,
                lae=lae if isinstance(lae, dict) else None,
                detail=detail,
            )
            prediction = model.predict(current)
            if prediction.surprise:
                out.append(
                    {
                        "id": row.get("id"),
                        "home": home,
                        "away": away,
                        "prediction": prediction.__dict__,
                    }
                )
        return out

    @mcp.tool()
    def predict_quiniela(
        fixtures: list[dict[str, str]], budget: int = 8
    ) -> dict[str, Any]:
        ms = [Match("", x["home"], x["away"]) for x in fixtures]
        return model.quiniela(ms, budget)

    return mcp
