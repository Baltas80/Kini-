from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

import pandas as pd

from kini_engine.dataio import build_dataset_profile, load_matches_csv, validate_matches


FOOTBALL_DATA = "https://www.football-data.co.uk/mmz4281/{season}/{division}.csv"
SEASONS = ("2021", "2122", "2223", "2324", "2425", "2526")
LEAGUES = {"la-liga": "SP1", "segunda": "SP2"}


def fetch(url: str) -> pd.DataFrame:
    with urlopen(url, timeout=30) as response:
        return pd.read_csv(response)


def main() -> None:
    frames: list[pd.DataFrame] = []
    source_urls: list[str] = []
    for season in SEASONS:
        for league, code in LEAGUES.items():
            url = FOOTBALL_DATA.format(season=season, division=code)
            df = fetch(url).assign(League=league, Season=season, SourceURL=url)
            source_urls.append(url)
            frames.append(df)

    raw = pd.concat(frames, ignore_index=True)
    required = ["HomeTeam", "AwayTeam", "FTHG", "FTAG"]
    final = raw.dropna(subset=required).copy()
    final = final.sort_values(["Date", "League", "HomeTeam", "AwayTeam"]).reset_index(drop=True)

    target = Path("data/historical_spain.csv")
    profile_target = Path("data/historical_spain.profile.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    final.to_csv(target, index=False)

    # The same validator used by the CLI must accept the generated backtest input.
    matches = load_matches_csv(target)
    validate_matches(matches)

    profile = build_dataset_profile(
        raw,
        final,
        source_urls,
        retrieved_at=datetime.now(timezone.utc),
    )
    profile_target.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(final)} matches to {target}")
    print(f"Wrote dataset profile to {profile_target}")
    print(json.dumps(profile, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
