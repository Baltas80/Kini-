from __future__ import annotations

from pathlib import Path
from urllib.request import urlopen

import pandas as pd


DATAHUB = "https://datahub.io/football/spanish-{league}/_r/-/season-{season}.csv"
SEASONS = ("2021", "2122", "2223", "2324", "2425", "2526")
LEAGUES = {
    "la-liga": "sp1",
    "segunda": "sp2",
}


def fetch(url: str) -> pd.DataFrame:
    with urlopen(url, timeout=30) as response:
        return pd.read_csv(response)


def main() -> None:
    frames: list[pd.DataFrame] = []
    for season in SEASONS:
        for league, code in LEAGUES.items():
            url = DATAHUB.format(league=league, season=season)
            # DataHub uses season names matching the source dataset; keep the
            # source URL in metadata rather than copying the external files.
            df = fetch(url)
            df["League"] = league
            df["Season"] = season
            df["SourceURL"] = url
            frames.append(df)

    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["HomeTeam", "AwayTeam", "FTHG", "FTAG"])
    out = out.sort_values("Date")
    target = Path("data/historical_spain.csv")
    target.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(target, index=False)
    print(f"Wrote {len(out)} matches to {target}")


if __name__ == "__main__":
    main()
