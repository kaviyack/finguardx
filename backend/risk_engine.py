"""
FinGuardX — Risk Engine
Standalone module for model training, evaluation, and batch scoring.
Uses synthetic data modelled on Kaggle Credit Card Fraud dataset structure.

Usage:
  python risk_engine.py train      # Train and save model
  python risk_engine.py evaluate   # Evaluate model accuracy
  python risk_engine.py score      # Score a sample transaction
"""

import sys, os, json
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score,
    f1_score, roc_auc_score, confusion_matrix, classification_report
)
from sklearn.pipeline import Pipeline
import joblib

MODEL_DIR    = os.path.join(os.path.dirname(__file__), "model")
MODEL_PATH   = os.path.join(MODEL_DIR, "risk_model.joblib")
ENCODER_PATH = os.path.join(MODEL_DIR, "encoders.joblib")
SCALER_PATH  = os.path.join(MODEL_DIR, "scaler.joblib")

# ─── SYNTHETIC DATASET GENERATION ────────────────────────────────────────────
# Simulates the Kaggle Credit Card Fraud Detection dataset structure
# with domain-specific features matching FinGuardX's transaction schema.

def generate_dataset(n_samples: int = 10000, seed: int = 42) -> pd.DataFrame:
    """
    Generate synthetic transaction dataset.
    Features mirror those used in the Kaggle CC Fraud Detection dataset:
    - Transaction amount (V-features are abstracted into domain features)
    - Time/hour features
    - Categorical features (encoded)
    - Binary fraud label
    """
    rng = np.random.default_rng(seed)

    TX_TYPES  = ["Wire Transfer", "Card Payment", "ACH Transfer",
                 "Crypto Conversion", "Cash Deposit"]
    CATEGORIES = ["Retail", "Travel", "Gambling", "Crypto Exchange",
                  "Utilities", "Healthcare"]
    LOCATIONS  = ["Same country", "Cross-border", "High-risk jurisdiction"]

    # Sample features
    amounts   = np.where(
        rng.random(n_samples) > 0.9,
        rng.exponential(scale=15000, size=n_samples),   # 10% large
        rng.exponential(scale=2000,  size=n_samples),   # 90% normal
    )
    hours     = rng.integers(0, 24, size=n_samples)
    tx_types  = rng.choice(TX_TYPES,  p=[0.15, 0.45, 0.25, 0.08, 0.07], size=n_samples)
    categories= rng.choice(CATEGORIES,p=[0.40, 0.20, 0.08, 0.07, 0.15, 0.10], size=n_samples)
    locations = rng.choice(LOCATIONS, p=[0.65, 0.28, 0.07], size=n_samples)

    # Fraud probability based on domain risk factors
    risk_score = np.zeros(n_samples)
    risk_score += (amounts > 20000) * 3.5
    risk_score += (amounts > 10000) * 1.5
    risk_score += np.isin(categories, ["Gambling", "Crypto Exchange"]) * 2.5
    risk_score += (locations == "High-risk jurisdiction") * 3.0
    risk_score += (locations == "Cross-border") * 1.2
    risk_score += ((hours < 5) | (hours > 23)) * 2.0
    risk_score += np.isin(tx_types, ["Crypto Conversion"]) * 2.0
    risk_score += np.isin(tx_types, ["Wire Transfer"]) * 0.8
    risk_score += rng.normal(0, 0.8, size=n_samples)   # noise

    fraud_prob = 1 / (1 + np.exp(-(risk_score - 5)))
    fraud      = (rng.random(n_samples) < fraud_prob).astype(int)

    df = pd.DataFrame({
        "amount":            amounts.round(2),
        "hour_of_day":       hours,
        "tx_type":           tx_types,
        "merchant_category": categories,
        "location_flag":     locations,
        "is_fraud":          fraud,
    })
    return df


# ─── FEATURE ENGINEERING ─────────────────────────────────────────────────────
def engineer_features(df: pd.DataFrame,
                       encoders: dict = None,
                       fit: bool = False) -> tuple[np.ndarray, dict]:
    """Transform raw features into model-ready array."""
    df = df.copy()

    # Log-transform amount (reduces skew, matches V-feature behaviour in Kaggle set)
    df["log_amount"]  = np.log1p(df["amount"])
    df["is_offhours"] = ((df["hour_of_day"] < 6) | (df["hour_of_day"] > 22)).astype(int)
    df["is_large_tx"] = (df["amount"] > 10000).astype(int)
    df["is_xlarge_tx"]= (df["amount"] > 25000).astype(int)

    cat_cols = ["tx_type", "merchant_category", "location_flag"]
    if fit or encoders is None:
        encoders = {c: LabelEncoder().fit(df[c]) for c in cat_cols}
    for c in cat_cols:
        enc = encoders[c]
        vals = df[c].copy()
        # Handle unseen labels gracefully
        mask = ~vals.isin(enc.classes_)
        if mask.any():
            vals[mask] = enc.classes_[0]
        df[c + "_enc"] = enc.transform(vals)

    feature_cols = [
        "log_amount", "amount", "hour_of_day", "is_offhours",
        "is_large_tx", "is_xlarge_tx",
        "tx_type_enc", "merchant_category_enc", "location_flag_enc",
    ]
    X = df[feature_cols].values
    return X, encoders


# ─── TRAINING ────────────────────────────────────────────────────────────────
def train(n_samples: int = 10000):
    """Train RandomForest model and save to disk."""
    os.makedirs(MODEL_DIR, exist_ok=True)

    print(f"[FinGuardX Risk Engine] Generating synthetic dataset ({n_samples} samples)...")
    df = generate_dataset(n_samples)
    print(f"  Fraud rate: {df['is_fraud'].mean()*100:.2f}%  "
          f"({df['is_fraud'].sum()} fraudulent / {len(df)} total)")

    X, encoders = engineer_features(df, fit=True)
    y = df["is_fraud"].values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    print("[FinGuardX Risk Engine] Training RandomForestClassifier...")
    model = RandomForestClassifier(
        n_estimators   = 150,
        max_depth      = 10,
        min_samples_leaf = 4,
        class_weight   = "balanced",
        random_state   = 42,
        n_jobs         = -1,
    )
    model.fit(X_train, y_train)

    # Evaluate
    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]

    acc  = accuracy_score(y_test, y_pred)
    prec = precision_score(y_test, y_pred)
    rec  = recall_score(y_test, y_pred)
    f1   = f1_score(y_test, y_pred)
    auc  = roc_auc_score(y_test, y_prob)

    print(f"\n{'─'*50}")
    print(f"  Accuracy:  {acc*100:.2f}%  (target ≥ 85%)")
    print(f"  Precision: {prec*100:.2f}%")
    print(f"  Recall:    {rec*100:.2f}%")
    print(f"  F1 Score:  {f1*100:.2f}%")
    print(f"  ROC-AUC:   {auc:.4f}")
    print(f"{'─'*50}")
    print("\nConfusion Matrix:")
    cm = confusion_matrix(y_test, y_pred)
    print(f"  TN={cm[0,0]:4d}  FP={cm[0,1]:4d}")
    print(f"  FN={cm[1,0]:4d}  TP={cm[1,1]:4d}")
    print(f"\n{classification_report(y_test, y_pred, target_names=['Legit','Fraud'])}")

    # Feature importance
    feature_names = [
        "log_amount", "amount", "hour_of_day", "is_offhours",
        "is_large_tx", "is_xlarge_tx", "tx_type", "category", "location",
    ]
    importances = sorted(zip(feature_names, model.feature_importances_),
                         key=lambda x: -x[1])
    print("Feature importances:")
    for name, imp in importances:
        bar = "█" * int(imp * 40)
        print(f"  {name:<20} {bar} {imp:.4f}")

    # Save
    joblib.dump(model, MODEL_PATH)
    joblib.dump(encoders, ENCODER_PATH)
    print(f"\n[FinGuardX Risk Engine] Model saved to {MODEL_PATH}")

    # Save evaluation results
    results = {
        "accuracy": round(acc, 4), "precision": round(prec, 4),
        "recall": round(rec, 4),   "f1": round(f1, 4), "roc_auc": round(auc, 4),
        "n_train": len(X_train),   "n_test": len(X_test),
        "fraud_rate": round(float(df["is_fraud"].mean()), 4),
        "model": "RandomForestClassifier", "version": "v1.0",
    }
    with open(os.path.join(MODEL_DIR, "eval_results.json"), "w") as f:
        json.dump(results, f, indent=2)

    return model, encoders, results


# ─── SCORING ─────────────────────────────────────────────────────────────────
def score_transaction(amount: float, hour: int, tx_type: str,
                       category: str, location: str,
                       model=None, encoders=None) -> dict:
    """
    Score a single transaction. Returns a dict with:
      - score (0-100)
      - risk_level (Low / Medium / High)
      - fraud_probability (0.0-1.0)
      - factor contributions
    """
    if model is None or encoders is None:
        if not os.path.exists(MODEL_PATH):
            model, encoders, _ = train()
        else:
            model    = joblib.load(MODEL_PATH)
            encoders = joblib.load(ENCODER_PATH)

    row = pd.DataFrame([{
        "amount": amount, "hour_of_day": hour,
        "tx_type": tx_type, "merchant_category": category,
        "location_flag": location,
    }])
    X, _ = engineer_features(row, encoders=encoders, fit=False)
    prob = float(model.predict_proba(X)[0][1])

    # Heuristic factor contributions
    factors = {
        "amount":   _factor_amount(amount),
        "category": _factor_category(category),
        "location": _factor_location(location),
        "time":     _factor_time(hour),
        "type":     _factor_type(tx_type),
    }
    h_total = sum(factors.values())
    h_norm  = min(100, int((h_total / 90) * 100))
    ml_part = int(prob * 100)
    blended = int(ml_part * 0.5 + h_norm * 0.5)
    score   = max(0, min(100, blended))

    risk_level = "High" if score >= 70 else "Medium" if score >= 40 else "Low"

    return {
        "score":             score,
        "risk_level":        risk_level,
        "fraud_probability": round(prob, 4),
        "factors":           factors,
        "model_version":     "v1.0",
    }


def _factor_amount(a):
    if a > 20000: return 35
    if a > 5000:  return 20
    if a > 1000:  return 10
    return 3

def _factor_category(c):
    return {"Gambling":28,"Crypto Exchange":22,"Travel":12,"Retail":5,"Healthcare":2,"Utilities":3}.get(c,5)

def _factor_location(l):
    return {"High-risk jurisdiction":28,"Cross-border":14,"Same country":4}.get(l,4)

def _factor_time(h):
    return 18 if (h < 6 or h > 22) else 5

def _factor_type(t):
    return {"Crypto Conversion":18,"Wire Transfer":10,"ACH Transfer":7,"Card Payment":4,"Cash Deposit":12}.get(t,5)


# ─── BATCH SCORING ───────────────────────────────────────────────────────────
def batch_score(df: pd.DataFrame) -> pd.DataFrame:
    """Score a DataFrame of transactions. Adds 'score' and 'risk_level' columns."""
    if not os.path.exists(MODEL_PATH):
        model, encoders, _ = train()
    else:
        model    = joblib.load(MODEL_PATH)
        encoders = joblib.load(ENCODER_PATH)

    X, _ = engineer_features(df, encoders=encoders, fit=False)
    probs = model.predict_proba(X)[:, 1]

    df = df.copy()
    df["fraud_prob"] = probs
    df["score"] = df.apply(
        lambda r: max(0, min(100, int(
            float(r["fraud_prob"]) * 50 +
            (_factor_amount(r["amount"]) +
             _factor_category(r["merchant_category"]) +
             _factor_location(r["location_flag"]) +
             _factor_time(r["hour_of_day"]) +
             _factor_type(r["tx_type"])) / 90 * 50
        ))), axis=1
    )
    df["risk_level"] = pd.cut(
        df["score"], bins=[-1, 39, 69, 100],
        labels=["Low", "Medium", "High"]
    )
    return df


# ─── CLI ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "train"

    if cmd == "train":
        train(n_samples=10000)

    elif cmd == "evaluate":
        if not os.path.exists(MODEL_PATH):
            print("Model not found — training first...")
            train()
        results_path = os.path.join(MODEL_DIR, "eval_results.json")
        if os.path.exists(results_path):
            with open(results_path) as f:
                print(json.dumps(json.load(f), indent=2))

    elif cmd == "score":
        result = score_transaction(
            amount   = float(sys.argv[2]) if len(sys.argv) > 2 else 12000,
            hour     = int(sys.argv[3])   if len(sys.argv) > 3 else 3,
            tx_type  = sys.argv[4]        if len(sys.argv) > 4 else "Wire Transfer",
            category = sys.argv[5]        if len(sys.argv) > 5 else "Gambling",
            location = sys.argv[6]        if len(sys.argv) > 6 else "High-risk jurisdiction",
        )
        print(json.dumps(result, indent=2))

    elif cmd == "batch":
        # Score a sample batch
        df = generate_dataset(100)
        df = df.drop(columns=["is_fraud"])
        results = batch_score(df)
        print(results[["amount","tx_type","merchant_category","location_flag","score","risk_level"]].head(20).to_string())

    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python risk_engine.py [train|evaluate|score|batch]")
