import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import accuracy_score, brier_score_loss
import pickle

print("Loading training data...")
df = pd.read_csv("training_data.csv")
print(f"Total games: {len(df)}")

# Features the model trains on
FEATURES = [
    "home_era", "home_whip", "home_k9", "home_bb9",
    "away_era", "away_whip", "away_k9", "away_bb9",
    "home_ops", "home_kpct", "away_ops", "away_kpct",
    "era_diff", "k9_diff", "ops_diff"
]

X = df[FEATURES]
y = df["home_win"]

# Split: 2023-2024 = training, 2025 = test
train = df[df["season"].isin([2023, 2024])]
test  = df[df["season"] == 2025]

X_train = train[FEATURES]
y_train = train["home_win"]
X_test  = test[FEATURES]
y_test  = test["home_win"]

print(f"\nTraining games: {len(X_train)}")
print(f"Test games: {len(X_test)}")

# Scale features
scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled  = scaler.transform(X_test)

# ── Model 1: Logistic Regression ──────────────────────────────
print("\nTraining Logistic Regression...")
lr = LogisticRegression(max_iter=1000)
lr_calibrated = CalibratedClassifierCV(lr, cv=5)
lr_calibrated.fit(X_train_scaled, y_train)

lr_preds = lr_calibrated.predict(X_test_scaled)
lr_probs = lr_calibrated.predict_proba(X_test_scaled)[:, 1]
lr_acc   = accuracy_score(y_test, lr_preds)
lr_brier = brier_score_loss(y_test, lr_probs)

print(f"  Accuracy: {lr_acc:.3f} ({lr_acc*100:.1f}%)")
print(f"  Brier Score: {lr_brier:.4f} (lower is better)")

# ── Model 2: XGBoost ──────────────────────────────────────────
print("\nTraining XGBoost...")
from xgboost import XGBClassifier
xgb = XGBClassifier(
    n_estimators=200,
    max_depth=4,
    learning_rate=0.05,
    subsample=0.8,
    eval_metric="logloss",
    verbosity=0
)
xgb_calibrated = CalibratedClassifierCV(xgb, cv=5)
xgb_calibrated.fit(X_train_scaled, y_train)

xgb_preds = xgb_calibrated.predict(X_test_scaled)
xgb_probs = xgb_calibrated.predict_proba(X_test_scaled)[:, 1]
xgb_acc   = accuracy_score(y_test, xgb_preds)
xgb_brier = brier_score_loss(y_test, xgb_probs)

print(f"  Accuracy: {xgb_acc:.3f} ({xgb_acc*100:.1f}%)")
print(f"  Brier Score: {xgb_brier:.4f} (lower is better)")

# ── Pick best model ───────────────────────────────────────────
if xgb_brier < lr_brier:
    print("\nXGBoost wins -- saving as active model")
    best_model = xgb_calibrated
else:
    print("\nLogistic Regression wins -- saving as active model")
    best_model = lr_calibrated

# Save model and scaler
with open("model.pkl", "wb") as f:
    pickle.dump(best_model, f)
with open("scaler.pkl", "wb") as f:
    pickle.dump(scaler, f)

print("Model saved to model.pkl")
print("Scaler saved to scaler.pkl")

# Feature importance
print("\n--- Feature Importance ---")
try:
    base_lr = LogisticRegression(max_iter=1000)
    base_lr.fit(X_train_scaled, y_train)
    for feat, coef in sorted(zip(FEATURES, base_lr.coef_[0]), key=lambda x: abs(x[1]), reverse=True):
        print(f"  {feat:<20} {coef:+.4f}")
except Exception as e:
    print(f"  Could not display: {e}")