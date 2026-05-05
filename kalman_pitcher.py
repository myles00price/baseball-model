import numpy as np
import requests
from pybaseball import playerid_lookup, statcast_pitcher
from datetime import datetime
import warnings
warnings.filterwarnings("ignore")

class PitcherKalman:
    """
    Kalman filter for pitcher ERA estimation.
    
    Tracks both the estimate AND uncertainty simultaneously.
    A volatile pitcher (alternating 0 ERA and 8 ERA starts) 
    stays uncertain longer than a consistent pitcher.
    
    State: [ERA, WHIP, K9, BB9]
    """

    def __init__(self, career_stats, process_noise=0.3, measurement_noise=4.0):
        """
        career_stats: dict with era, whip, k9, bb9 — used as prior
        process_noise: how much we expect true ability to change start to start
        measurement_noise: how noisy a single start is as a measurement
        """
        # Initial state estimate = career stats
        self.state = np.array([
            career_stats.get("era",  4.50),
            career_stats.get("whip", 1.30),
            career_stats.get("k9",   8.00),
            career_stats.get("bb9",  3.00),
        ])

        # Initial uncertainty — high because we haven't seen 2026 starts
        self.P = np.eye(4) * 5.0

        # Process noise — how much true ability varies start to start
        self.Q = np.eye(4) * process_noise

        # Measurement noise — how noisy one start's stats are
        self.R = np.eye(4) * measurement_noise

        # Track history for display
        self.history = []
        self.n_starts = 0

    def update(self, start_stats):
        """
        Update estimate with a new start's stats.
        start_stats: dict with era, whip, k9, bb9 for this start
        """
        z = np.array([
            start_stats.get("era",  self.state[0]),
            start_stats.get("whip", self.state[1]),
            start_stats.get("k9",   self.state[2]),
            start_stats.get("bb9",  self.state[3]),
        ])

        # Predict step — uncertainty grows slightly each start
        P_pred = self.P + self.Q

        # Kalman gain — how much to trust new measurement vs current estimate
        # High gain = trust new data more
        # Low gain = trust current estimate more
        K = P_pred @ np.linalg.inv(P_pred + self.R)

        # Update state estimate
        self.state = self.state + K @ (z - self.state)

        # Update uncertainty — decreases as we get more data
        self.P = (np.eye(4) - K) @ P_pred

        self.n_starts += 1
        self.history.append({
            "start": self.n_starts,
            "raw_era": round(start_stats.get("era", 0), 2),
            "kalman_era": round(self.state[0], 2),
            "uncertainty": round(self.P[0, 0], 3),
            "gain": round(K[0, 0], 3)
        })

    @property
    def estimate(self):
        return {
            "era":  round(max(1.50, min(6.50, float(self.state[0]))), 2),
            "whip": round(max(0.80, min(1.80, float(self.state[1]))), 2),
            "k9":   round(max(4.00, min(13.00, float(self.state[2]))), 2),
            "bb9":  round(max(1.00, min(6.00, float(self.state[3]))), 2),
            "uncertainty": round(float(self.P[0, 0]), 3),
            "n_starts":    self.n_starts,
            "reliability": round(min(self.n_starts / 10 * 100, 100), 1)
        }

def get_career_stats(player_id):
    """Pull career pitching stats as Kalman prior"""
    try:
        data = requests.get(
            f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats",
            params={"stats": "career", "group": "pitching"},
            timeout=30
        ).json()
        splits = data["stats"][0]["splits"]
        if not splits:
            return None
        s = splits[0]["stat"]
        ip = float(s.get("inningsPitched", 0))
        if ip < 10:
            return None
        return {
            "era":  float(s.get("era",  4.50)),
            "whip": float(s.get("whip", 1.30)),
            "k9":   float(s.get("strikeoutsPer9Inn", 8.00)),
            "bb9":  float(s.get("walksPer9Inn",  3.00)),
        }
    except:
        return None

def get_start_by_start_stats(player_id, season):
    """Pull game log to get per-start stats"""
    try:
        data = requests.get(
            f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats",
            params={"stats": "gameLog", "season": season, "group": "pitching"},
            timeout=30
        ).json()
        splits = data["stats"][0]["splits"]
        starts = []
        for split in splits:
            s = split["stat"]
            ip = float(s.get("inningsPitched", 0))
            if ip < 1:
                continue
            er = float(s.get("earnedRuns", 0))
            h  = float(s.get("hits", 0))
            bb = float(s.get("baseOnBalls", 0))
            so = float(s.get("strikeOuts", 0))
            era  = round((er / ip) * 9, 2) if ip > 0 else 4.50
            whip = round((h + bb) / ip, 2) if ip > 0 else 1.30
            k9   = round((so / ip) * 9, 2) if ip > 0 else 8.00
            bb9  = round((bb / ip) * 9, 2) if ip > 0 else 3.00
            starts.append({
                "date": split.get("date", ""),
                "era":  era,
                "whip": whip,
                "k9":   k9,
                "bb9":  bb9,
                "ip":   ip
            })
        return starts
    except:
        return []

def get_kalman_pitcher_stats(full_name, season, playerid_lookup_fn):
    """
    Main function — replaces get_blended_pitcher_stats
    Returns Kalman-filtered pitcher stats
    """
    if not full_name or full_name in ["TBD", "Unknown"]:
        return None, None

    try:
        parts = full_name.split()
        first, last = parts[0], parts[-1]
        lookup = playerid_lookup_fn(last, first)
        if lookup.empty:
            return None, None
        pid = int(lookup.iloc[0]["key_mlbam"])
    except:
        return None, None

    # Get career stats as prior
    career = get_career_stats(pid)
    if not career:
        career = {"era": 4.50, "whip": 1.30, "k9": 8.00, "bb9": 3.00}

    # Get pitcher handedness
    try:
        bio = requests.get(
            f"https://statsapi.mlb.com/api/v1/people/{pid}",
            timeout=30
        ).json()
        hand = bio["people"][0].get("pitchHand", {}).get("code", "R")
    except:
        hand = "R"

    # Initialize Kalman filter with career stats as prior
    kf = PitcherKalman(career)

    # Get start-by-start data for current season
    starts = get_start_by_start_stats(pid, season)

    # Feed each start through the filter
    for start in starts:
        kf.update(start)

    est = kf.estimate
    est["hand"] = hand

    return est, pid

if __name__ == "__main__":
    print("Testing Kalman filter on select pitchers...\n")

    test_pitchers = [
        "Paul Skenes",
        "Tarik Skubal",
        "Logan Webb",
        "Framber Valdez",
    ]

    from pybaseball import playerid_lookup as lookup_fn

    for name in test_pitchers:
        print(f"\n{'='*50}")
        print(f"  {name}")
        print(f"{'='*50}")
        stats, pid = get_kalman_pitcher_stats(name, 2026, lookup_fn)
        if stats:
            print(f"  Kalman ERA:    {stats['era']}")
            print(f"  Kalman WHIP:   {stats['whip']}")
            print(f"  Kalman K9:     {stats['k9']}")
            print(f"  Kalman BB9:    {stats['bb9']}")
            print(f"  Starts:        {stats['n_starts']}")
            print(f"  Uncertainty:   {stats['uncertainty']}")
            print(f"  Reliability:   {stats['reliability']}%")
            print(f"  Hand:          {stats['hand']}")
        else:
            print(f"  No data found")