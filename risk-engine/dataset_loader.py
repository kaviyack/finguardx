"""
FinGuardX — Kaggle Dataset Integration
=======================================
Handles loading, preprocessing, and adapting the two Kaggle datasets
specified in SRS §3 for use in risk model training and evaluation.

Datasets:
  1. Credit Card Fraud Detection  (primary)
     kaggle.com/datasets/mlg-ulb/creditcardfraud
     → Used for: fraud label classification, risk scoring

  2. Loan Prediction / Credit Risk  (secondary)
     kaggle.com/datasets/laotse/credit-risk-dataset
     → Used for: credit behavior analysis, repayment patterns

Usage:
  python dataset_loader.py prepare   # Prepare datasets (download or generate)
  python dataset_loader.py stats     # Show dataset statistics
  python dataset_loader.py train     # Train model on prepared data

Since real Kaggle data requires authentication and cannot be downloaded
in all environments, this module implements a three-tier strategy:
  1. Use real Kaggle CSV if present in ./data/
  2. Generate high-fidelity synthetic data matching exact Kaggle schema
  3. Fall back to risk_engine.py internal generator
"""

import os, sys, json, csv
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_score
from sklearn.preprocessing import LabelEncoder, StandardScaler, RobustScaler
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score,
    f1_score, roc_auc_score, confusion_matrix, classification_report,
    average_precision_score,
)
from sklearn.pipeline import Pipeline
from sklearn.utils import resample
import joblib

DATA_DIR    = os.path.join(os.path.dirname(__file__), "data")
MODEL_DIR   = os.path.join(os.path.dirname(__file__), "model")
KAGGLE_CC   = os.path.join(DATA_DIR, "creditcard.csv")       # Kaggle CC Fraud
KAGGLE_LOAN = os.path.join(DATA_DIR, "credit_risk_dataset.csv")  # Kaggle Loan
SYNTH_CC    = os.path.join(DATA_DIR, "synthetic_cc_fraud.csv")
SYNTH_LOAN  = os.path.join(DATA_DIR, "synthetic_loan.csv")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(MODEL_DIR, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — CREDIT CARD FRAUD DATASET (Primary)
# Mirrors the Kaggle Credit Card Fraud Detection dataset schema exactly:
#   - 28 PCA-transformed features (V1-V28) + Time + Amount + Class
#   - Class: 0 = legitimate, 1 = fraudulent
# ═══════════════════════════════════════════════════════════════════════════════

def generate_cc_fraud_dataset(n: int = 50000, seed: int = 42) -> pd.DataFrame:
    """
    Generate synthetic data matching the Kaggle CC Fraud Detection schema.
    284,807 transactions, 492 frauds (0.172%) in the real dataset.
    We generate a balanced representative sample.
    """
    print(f"  Generating synthetic CC fraud dataset ({n:,} rows)...")
    rng = np.random.default_rng(seed)

    # Fraud rate matches real Kaggle dataset (~0.17%)
    n_fraud = max(500, int(n * 0.0017 * 30))  # oversample for training viability
    n_legit = n - n_fraud

    # V1-V28: PCA components (real dataset has these anonymised)
    # We model them as correlated Gaussians with fraud-specific shifts
    legit_V  = rng.multivariate_normal(np.zeros(28), np.eye(28), size=n_legit)
    # Fraud transactions have distinct PCA signatures (shifted distributions)
    fraud_shifts = np.array([
        -2.3, 2.8, -3.1, 2.5, -1.8, 2.1, -4.5, 3.2,
        -2.7, 2.9, -1.5, 1.8, -2.2, 2.4, -1.9, 2.6,
        -3.3, 2.1, -1.7, 2.3, -2.8, 1.9, -2.1, 2.7,
        -1.6, 2.2, -2.4, 1.8
    ])
    fraud_V  = rng.multivariate_normal(fraud_shifts, np.eye(28) * 1.5, size=n_fraud)

    # Time: seconds elapsed (0 to 172792 in real dataset, 2 days)
    legit_time = rng.uniform(0, 172792, n_legit)
    fraud_time = np.concatenate([
        rng.uniform(0, 43200, n_fraud // 2),      # off-hours cluster
        rng.uniform(129600, 172792, n_fraud - n_fraud // 2),
    ])

    # Amount: real dataset has mean=$88, high skew
    legit_amt = np.abs(rng.exponential(scale=80, size=n_legit)).round(2)
    fraud_amt = np.abs(rng.exponential(scale=120, size=n_fraud)).round(2)
    fraud_amt = np.clip(fraud_amt, 1, 5000)

    V_cols = [f"V{i}" for i in range(1, 29)]

    legit_df = pd.DataFrame(legit_V, columns=V_cols)
    legit_df["Time"]   = legit_time
    legit_df["Amount"] = legit_amt
    legit_df["Class"]  = 0

    fraud_df = pd.DataFrame(fraud_V, columns=V_cols)
    fraud_df["Time"]   = fraud_time
    fraud_df["Amount"] = fraud_amt
    fraud_df["Class"]  = 1

    df = pd.concat([legit_df, fraud_df], ignore_index=True)
    df = df.sample(frac=1, random_state=seed).reset_index(drop=True)
    return df


def load_cc_fraud_dataset() -> pd.DataFrame:
    """Load CC fraud dataset: real Kaggle CSV → synthetic fallback."""
    if os.path.exists(KAGGLE_CC):
        print(f"  Loading real Kaggle dataset: {KAGGLE_CC}")
        df = pd.read_csv(KAGGLE_CC)
        print(f"  Loaded {len(df):,} rows, fraud rate: {df['Class'].mean()*100:.3f}%")
        return df
    elif os.path.exists(SYNTH_CC):
        print(f"  Loading cached synthetic CC dataset: {SYNTH_CC}")
        return pd.read_csv(SYNTH_CC)
    else:
        df = generate_cc_fraud_dataset()
        df.to_csv(SYNTH_CC, index=False)
        print(f"  Saved to {SYNTH_CC}")
        return df


def engineer_cc_features(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """
    Feature engineering for CC Fraud dataset.
    Adds time-of-day, amount bins, and interaction features.
    """
    df = df.copy()

    # Time features
    df["hour"]       = (df["Time"] // 3600) % 24
    df["is_offhours"]= ((df["hour"] < 6) | (df["hour"] > 22)).astype(int)
    df["day"]        = (df["Time"] // 86400).astype(int)

    # Amount features
    df["log_amount"]   = np.log1p(df["Amount"])
    df["is_large"]     = (df["Amount"] > 200).astype(int)
    df["is_very_large"]= (df["Amount"] > 1000).astype(int)
    df["is_tiny"]      = (df["Amount"] < 5).astype(int)

    # V-feature interactions (top fraud-discriminating components)
    df["V1_V2"]   = df["V1"] * df["V2"]
    df["V3_V4"]   = df["V3"] * df["V4"]
    df["V14_neg"] = -df["V14"]   # V14 is strong fraud indicator (negatively correlated)
    df["V17_neg"] = -df["V17"]

    feature_cols = (
        [f"V{i}" for i in range(1, 29)] +
        ["log_amount", "Amount", "hour", "is_offhours", "day",
         "is_large", "is_very_large", "is_tiny",
         "V1_V2", "V3_V4", "V14_neg", "V17_neg"]
    )
    X = df[feature_cols].values
    y = df["Class"].values
    return X, y


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — LOAN / CREDIT RISK DATASET (Secondary)
# Mirrors the Kaggle Credit Risk Dataset schema:
#   person_age, person_income, person_home_ownership, person_emp_length,
#   loan_intent, loan_grade, loan_amnt, loan_int_rate, loan_status,
#   loan_percent_income, cb_person_default_on_file, cb_person_cred_hist_length
# loan_status: 0 = non-default, 1 = default
# ═══════════════════════════════════════════════════════════════════════════════

def generate_loan_dataset(n: int = 30000, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic data matching Kaggle Credit Risk dataset schema."""
    print(f"  Generating synthetic loan/credit dataset ({n:,} rows)...")
    rng = np.random.default_rng(seed)

    home_ownership = ["RENT", "OWN", "MORTGAGE", "OTHER"]
    loan_intent    = ["PERSONAL", "EDUCATION", "MEDICAL", "VENTURE",
                      "HOMEIMPROVEMENT", "DEBTCONSOLIDATION"]
    loan_grade     = ["A", "B", "C", "D", "E", "F", "G"]
    cb_default     = ["Y", "N"]

    ages     = rng.integers(20, 72, size=n)
    incomes  = np.clip(rng.exponential(scale=45000, size=n), 4000, 500000).astype(int)
    emp_len  = np.clip(rng.exponential(scale=4, size=n), 0, 41).round(0)
    home_own = rng.choice(home_ownership, p=[0.50, 0.10, 0.38, 0.02], size=n)
    intent   = rng.choice(loan_intent,    p=[0.20, 0.17, 0.14, 0.10, 0.15, 0.24], size=n)
    grade    = rng.choice(loan_grade,     p=[0.22, 0.26, 0.20, 0.14, 0.10, 0.05, 0.03], size=n)
    loan_amt = np.clip(rng.exponential(scale=8000, size=n), 500, 35000).astype(int)
    int_rate = np.where(
        np.isin(grade, ["A","B"]),
        rng.uniform(5, 12, n),
        rng.uniform(12, 24, n),
    ).round(2)
    pct_inc  = (loan_amt / incomes).round(2)
    cb_def   = rng.choice(cb_default, p=[0.18, 0.82], size=n)
    cred_hist= rng.integers(2, 30, size=n)

    # Default probability (loan_status=1)
    risk = (
        np.isin(grade, ["E","F","G"]).astype(float) * 2.5 +
        (pct_inc > 0.3).astype(float) * 2.0 +
        (cb_def == "Y").astype(float) * 2.0 +
        (int_rate > 18).astype(float) * 1.5 +
        (emp_len < 1).astype(float) * 1.2 +
        (incomes < 20000).astype(float) * 1.0 +
        rng.normal(0, 0.5, n)
    )
    default_prob = 1 / (1 + np.exp(-(risk - 3)))
    loan_status  = (rng.random(n) < default_prob).astype(int)

    df = pd.DataFrame({
        "person_age":                ages,
        "person_income":             incomes,
        "person_home_ownership":     home_own,
        "person_emp_length":         emp_len,
        "loan_intent":               intent,
        "loan_grade":                grade,
        "loan_amnt":                 loan_amt,
        "loan_int_rate":             int_rate,
        "loan_status":               loan_status,
        "loan_percent_income":       pct_inc,
        "cb_person_default_on_file": cb_def,
        "cb_person_cred_hist_length":cred_hist,
    })
    return df


def load_loan_dataset() -> pd.DataFrame:
    """Load loan dataset: real Kaggle CSV → synthetic fallback."""
    if os.path.exists(KAGGLE_LOAN):
        print(f"  Loading real Kaggle dataset: {KAGGLE_LOAN}")
        df = pd.read_csv(KAGGLE_LOAN)
        print(f"  Loaded {len(df):,} rows, default rate: {df['loan_status'].mean()*100:.2f}%")
        return df
    elif os.path.exists(SYNTH_LOAN):
        print(f"  Loading cached synthetic loan dataset: {SYNTH_LOAN}")
        return pd.read_csv(SYNTH_LOAN)
    else:
        df = generate_loan_dataset()
        df.to_csv(SYNTH_LOAN, index=False)
        print(f"  Saved to {SYNTH_LOAN}")
        return df


def engineer_loan_features(df: pd.DataFrame,
                             encoders: dict = None,
                             fit: bool = True) -> tuple[np.ndarray, np.ndarray, dict]:
    """Feature engineering for loan dataset."""
    df = df.copy()
    df = df.dropna()

    cat_cols = ["person_home_ownership","loan_intent","loan_grade","cb_person_default_on_file"]
    if fit or encoders is None:
        encoders = {c: LabelEncoder().fit(df[c].astype(str)) for c in cat_cols}
    for c in cat_cols:
        enc  = encoders[c]
        vals = df[c].astype(str)
        mask = ~vals.isin(enc.classes_)
        if mask.any():
            vals[mask] = enc.classes_[0]
        df[c+"_enc"] = enc.transform(vals)

    df["log_income"]       = np.log1p(df["person_income"])
    df["log_loan_amnt"]    = np.log1p(df["loan_amnt"])
    df["income_per_year"]  = df["person_income"] / (df["person_emp_length"] + 1)
    df["loan_to_income"]   = df["loan_amnt"] / (df["person_income"] + 1)

    feature_cols = [
        "person_age", "log_income", "person_emp_length",
        "log_loan_amnt", "loan_int_rate", "loan_percent_income",
        "cb_person_cred_hist_length", "income_per_year", "loan_to_income",
    ] + [c+"_enc" for c in cat_cols]

    X = df[feature_cols].values
    y = df["loan_status"].values
    return X, y, encoders


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — FINGUARDX DOMAIN DATASET
# Bridges Kaggle features to FinGuardX transaction schema
# ═══════════════════════════════════════════════════════════════════════════════

TX_TYPES   = ["Wire Transfer","Card Payment","ACH Transfer","Crypto Conversion","Cash Deposit"]
CATEGORIES = ["Retail","Travel","Gambling","Crypto Exchange","Utilities","Healthcare"]
LOCATIONS  = ["Same country","Cross-border","High-risk jurisdiction"]

def generate_finguardx_dataset(n: int = 20000, seed: int = 42) -> pd.DataFrame:
    """
    Generate FinGuardX-native transaction dataset by adapting Kaggle
    CC Fraud dataset features into the domain-specific schema.
    """
    print(f"  Generating FinGuardX domain dataset ({n:,} rows)...")
    rng = np.random.default_rng(seed)

    # Load base CC fraud data for fraud labels
    cc_df   = load_cc_fraud_dataset()
    sample  = cc_df.sample(n=min(n, len(cc_df)), random_state=seed, replace=len(cc_df)<n)
    labels  = sample["Class"].values
    amounts = np.abs(sample["Amount"].values)

    # Map Kaggle V-features to domain features using learned correlations
    hours    = rng.integers(0, 24, n)
    tx_types = np.where(
        labels == 1,
        rng.choice(TX_TYPES, p=[0.35, 0.10, 0.15, 0.30, 0.10], size=n),
        rng.choice(TX_TYPES, p=[0.12, 0.48, 0.25, 0.06, 0.09], size=n),
    )
    categories = np.where(
        labels == 1,
        rng.choice(CATEGORIES, p=[0.10, 0.15, 0.25, 0.30, 0.10, 0.10], size=n),
        rng.choice(CATEGORIES, p=[0.42, 0.20, 0.05, 0.05, 0.17, 0.11], size=n),
    )
    locations = np.where(
        labels == 1,
        rng.choice(LOCATIONS, p=[0.20, 0.30, 0.50], size=n),
        rng.choice(LOCATIONS, p=[0.72, 0.25, 0.03], size=n),
    )

    df = pd.DataFrame({
        "amount":            amounts.round(2),
        "hour_of_day":       hours,
        "tx_type":           tx_types,
        "merchant_category": categories,
        "location_flag":     locations,
        "is_fraud":          labels,
    })
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — MODEL TRAINING ON PREPARED DATA
# ═══════════════════════════════════════════════════════════════════════════════

def train_on_kaggle_data():
    """
    Full training pipeline using Kaggle-structured datasets.
    Trains and evaluates both the CC fraud model and the credit risk model.
    """
    print("\n" + "═"*60)
    print("  FinGuardX — Kaggle Dataset Training Pipeline")
    print("═"*60)

    # ── 1. CC Fraud Model ────────────────────────────────────────────────────
    print("\n[1/2] Credit Card Fraud Detection Model")
    print("─"*40)
    cc_df = load_cc_fraud_dataset()
    X_cc, y_cc = engineer_cc_features(cc_df)

    X_tr, X_te, y_tr, y_te = train_test_split(
        X_cc, y_cc, test_size=0.2, random_state=42, stratify=y_cc
    )

    # Handle class imbalance with SMOTE-style upsampling
    X_maj = X_tr[y_tr == 0]; X_min = X_tr[y_tr == 1]
    target = min(len(X_maj), len(X_min) * 10)
    X_min_up = resample(X_min, replace=True, n_samples=target, random_state=42)
    X_bal = np.vstack([X_maj[:target], X_min_up])
    y_bal = np.array([0]*target + [1]*target)

    scaler_cc = RobustScaler()
    X_bal_s   = scaler_cc.fit_transform(X_bal)
    X_te_s    = scaler_cc.transform(X_te)

    rf_cc = RandomForestClassifier(
        n_estimators=200, max_depth=12,
        min_samples_leaf=2, class_weight="balanced",
        random_state=42, n_jobs=-1,
    )
    rf_cc.fit(X_bal_s, y_bal)

    y_pred_cc = rf_cc.predict(X_te_s)
    y_prob_cc = rf_cc.predict_proba(X_te_s)[:, 1]

    acc_cc  = accuracy_score(y_te, y_pred_cc)
    prec_cc = precision_score(y_te, y_pred_cc, zero_division=0)
    rec_cc  = recall_score(y_te, y_pred_cc, zero_division=0)
    f1_cc   = f1_score(y_te, y_pred_cc, zero_division=0)
    auc_cc  = roc_auc_score(y_te, y_prob_cc)
    ap_cc   = average_precision_score(y_te, y_prob_cc)

    print(f"  Accuracy:          {acc_cc*100:.2f}%  (target ≥ 85%)")
    print(f"  Precision:         {prec_cc*100:.2f}%")
    print(f"  Recall:            {rec_cc*100:.2f}%")
    print(f"  F1:                {f1_cc*100:.2f}%")
    print(f"  ROC-AUC:           {auc_cc:.4f}")
    print(f"  Avg Precision:     {ap_cc:.4f}")
    cm = confusion_matrix(y_te, y_pred_cc)
    print(f"  Confusion matrix:  TN={cm[0,0]} FP={cm[0,1]} FN={cm[1,0]} TP={cm[1,1]}")

    # ── 2. Credit Risk Model ─────────────────────────────────────────────────
    print("\n[2/2] Credit Risk / Loan Default Model")
    print("─"*40)
    loan_df = load_loan_dataset()
    X_loan, y_loan, loan_enc = engineer_loan_features(loan_df, fit=True)

    X_ltr, X_lte, y_ltr, y_lte = train_test_split(
        X_loan, y_loan, test_size=0.2, random_state=42, stratify=y_loan
    )
    scaler_loan = StandardScaler()
    X_ltr_s     = scaler_loan.fit_transform(X_ltr)
    X_lte_s     = scaler_loan.transform(X_lte)

    rf_loan = RandomForestClassifier(
        n_estimators=150, max_depth=10,
        class_weight="balanced", random_state=42, n_jobs=-1,
    )
    rf_loan.fit(X_ltr_s, y_ltr)

    y_pred_l = rf_loan.predict(X_lte_s)
    y_prob_l = rf_loan.predict_proba(X_lte_s)[:, 1]

    acc_l  = accuracy_score(y_lte, y_pred_l)
    prec_l = precision_score(y_lte, y_pred_l, zero_division=0)
    rec_l  = recall_score(y_lte, y_pred_l, zero_division=0)
    f1_l   = f1_score(y_lte, y_pred_l, zero_division=0)
    auc_l  = roc_auc_score(y_lte, y_prob_l)

    print(f"  Accuracy:   {acc_l*100:.2f}%")
    print(f"  Precision:  {prec_l*100:.2f}%")
    print(f"  Recall:     {rec_l*100:.2f}%")
    print(f"  F1:         {f1_l*100:.2f}%")
    print(f"  ROC-AUC:    {auc_l:.4f}")

    # ── 3. Save models ───────────────────────────────────────────────────────
    os.makedirs(MODEL_DIR, exist_ok=True)
    joblib.dump(rf_cc,       os.path.join(MODEL_DIR, "cc_fraud_model.joblib"))
    joblib.dump(scaler_cc,   os.path.join(MODEL_DIR, "cc_scaler.joblib"))
    joblib.dump(rf_loan,     os.path.join(MODEL_DIR, "credit_risk_model.joblib"))
    joblib.dump(scaler_loan, os.path.join(MODEL_DIR, "credit_risk_scaler.joblib"))
    joblib.dump(loan_enc,    os.path.join(MODEL_DIR, "loan_encoders.joblib"))

    results = {
        "cc_fraud": {
            "accuracy": round(acc_cc,4), "precision": round(prec_cc,4),
            "recall": round(rec_cc,4), "f1": round(f1_cc,4),
            "roc_auc": round(auc_cc,4), "avg_precision": round(ap_cc,4),
            "n_train": len(X_bal), "n_test": len(X_te),
        },
        "credit_risk": {
            "accuracy": round(acc_l,4), "precision": round(prec_l,4),
            "recall": round(rec_l,4), "f1": round(f1_l,4),
            "roc_auc": round(auc_l,4),
            "n_train": len(X_ltr), "n_test": len(X_lte),
        }
    }
    with open(os.path.join(MODEL_DIR, "kaggle_eval_results.json"), "w") as f:
        json.dump(results, f, indent=2)

    print("\n" + "═"*60)
    print("  Training complete. Models saved to ./model/")
    print("  CC Fraud model  →  cc_fraud_model.joblib")
    print("  Credit Risk model → credit_risk_model.joblib")
    print("═"*60)
    return results


def print_dataset_stats():
    """Print statistics for both datasets."""
    print("\n── CC Fraud Dataset ──")
    cc = load_cc_fraud_dataset()
    print(f"  Rows:        {len(cc):,}")
    print(f"  Fraud rate:  {cc['Class'].mean()*100:.3f}%")
    print(f"  Amount mean: ${cc['Amount'].mean():.2f}")
    print(f"  Amount max:  ${cc['Amount'].max():,.2f}")
    print(f"  Columns:     {list(cc.columns)[:6]} ...")

    print("\n── Loan/Credit Risk Dataset ──")
    loan = load_loan_dataset()
    print(f"  Rows:         {len(loan):,}")
    print(f"  Default rate: {loan['loan_status'].mean()*100:.2f}%")
    print(f"  Loan mean:    ${loan['loan_amnt'].mean():,.0f}")
    print(f"  Columns:      {list(loan.columns)}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "prepare"

    if cmd == "prepare":
        print("Preparing datasets...")
        load_cc_fraud_dataset()
        load_loan_dataset()
        print("Datasets ready in ./data/")

    elif cmd == "stats":
        print_dataset_stats()

    elif cmd == "train":
        train_on_kaggle_data()

    elif cmd == "generate":
        print("Generating FinGuardX domain dataset...")
        df = generate_finguardx_dataset(n=20000)
        out = os.path.join(DATA_DIR, "finguardx_transactions.csv")
        df.to_csv(out, index=False)
        print(f"Saved {len(df):,} rows to {out}")
        print(df.groupby("is_fraud").size())

    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python dataset_loader.py [prepare|stats|train|generate]")
