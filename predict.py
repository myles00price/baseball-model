import pickle
import numpy as np

def load_model():
    with open("model.pkl", "rb") as f:
        model = pickle.load(f)
    with open("scaler.pkl", "rb") as f:
        scaler = pickle.load(f)
    return model, scaler

def predict_home_win_prob(
    home_era, home_whip, home_k9, home_bb9,
    away_era, away_whip, away_k9, away_bb9,
    home_ops, home_kpct, away_ops, away_kpct
):
    model, scaler = load_model()
    
    era_diff = away_era - home_era
    k9_diff  = home_k9 - away_k9
    ops_diff = home_ops - away_ops
    
    features = np.array([[
        home_era, home_whip, home_k9, home_bb9,
        away_era, away_whip, away_k9, away_bb9,
        home_ops, home_kpct, away_ops, away_kpct,
        era_diff, k9_diff, ops_diff
    ]])
    
    features_scaled = scaler.transform(features)
    prob = model.predict_proba(features_scaled)[0][1]
    return round(prob * 100, 1)