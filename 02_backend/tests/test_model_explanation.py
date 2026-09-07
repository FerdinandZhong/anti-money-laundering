import pytest


def test_no_champion_deployment_returns_explicit_no_explanation(db_conn):
    from agents.tools import get_model_explanation

    result = get_model_explanation(db_conn, "TX-ANY")
    assert result == [{"error": "no explanation available: no CHAMPION deployment found"}]


def test_champion_with_missing_artifact_returns_explicit_no_explanation(db_conn):
    from agents.tools import get_model_explanation

    db_conn.execute(
        "INSERT INTO deployments (deployment_id, model_version, status) VALUES (?, ?, 'CHAMPION')",
        ("DEPLOY-GHOST", "vGHOST-NO-ARTIFACT"),
    )
    db_conn.commit()

    result = get_model_explanation(db_conn, "TX-ANY")
    assert len(result) == 1
    assert "no explanation available" in result[0]["error"]
    assert "vGHOST-NO-ARTIFACT" in result[0]["error"]


def test_champion_with_real_artifact_returns_ranked_features(db_conn, monkeypatch, tmp_path):
    import numpy as np
    import xgboost as xgb
    from ml.feature_engineering import FEATURE_COLS
    from agents import tools

    monkeypatch.setattr(tools, "PROJECT_ROOT", str(tmp_path))
    import common.config as config_mod
    cfg = config_mod.get_config()
    monkeypatch.setitem(cfg, "model", {**cfg["model"], "model_dir": "."})

    X = np.random.default_rng(0).random((50, len(FEATURE_COLS)))
    y = (X[:, 0] > 0.5).astype(int)
    model = xgb.XGBClassifier(n_estimators=5, max_depth=2)
    model.fit(X, y)
    model.save_model(str(tmp_path / "aml_model_vREAL.json"))

    db_conn.execute(
        "INSERT INTO deployments (deployment_id, model_version, status) VALUES (?, ?, 'CHAMPION')",
        ("DEPLOY-REAL", "vREAL"),
    )
    db_conn.commit()

    result = tools.get_model_explanation(db_conn, "TX-ANY")
    assert len(result) == 5
    for row in result:
        assert set(row.keys()) == {"feature", "importance"}
        assert row["feature"] in FEATURE_COLS
    importances = [r["importance"] for r in result]
    assert importances == sorted(importances, reverse=True)
