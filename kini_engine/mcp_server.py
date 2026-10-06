from __future__ import annotations

from typing import Any

from .core import KiniEngine, Match
from .sources import KinielaGPTSource

try:
    from mcp.server.fastmcp import FastMCP
except Exception:
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
        return {"jornada": jornada, "temporada": temporada, "matches": matches}

    @mcp.tool()
    def get_probabilities(jornada: int, temporada: int) -> list[dict[str, Any]]:
        return source.probabilities(jornada, temporada)

    @mcp.tool()
    def analyze_match(home: str, away: str) -> dict[str, Any]:
        return model.predict(Match("", home, away)).__dict__

    @mcp.tool()
    def predict_quiniela(fixtures: list[dict[str, str]], budget: int = 8) -> dict[str, Any]:
        ms = [Match("", x["home"], x["away"]) for x in fixtures]
        return model.quiniela(ms, budget)

    return mcp
