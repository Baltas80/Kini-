from __future__ import annotations

from pathlib import Path
from urllib.request import urlopen

import pandas as pd


FOOTBALL_DATA = "https://www.football-data.co.uk/mmz4281/{season}/{division}.csv"
SEASONS = ("2021", "2122", "2223", "2324", "2425", "2526")
LEAGUES = {"la-liga": "SP1", "segunda": "SP2"}


def fetch(url: str) -> pd.DataFrame:
    with urlopen(url, timeout=30) as response:
        return pd.read_csv(response)


def main() -> None:
    frames: list[pd.DataFrame] = []
    for season in SEASONS:
        for league, code in LEAGUES.items():
            url = FOOTBALL_DATA.format(season=season, division=code)
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
