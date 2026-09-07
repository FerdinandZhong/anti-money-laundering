import pytest


def test_promote_flips_champion_and_retires_old_one(db_conn, tmp_path):
    from ml.train import promote

    model_dir = str(tmp_path)
    (tmp_path / "aml_model_v1.json").write_text("{}")
    (tmp_path / "aml_model_v2.json").write_text("{}")

    db_conn.execute(
        "INSERT INTO deployments (deployment_id, model_version, status) VALUES (?, ?, 'CHAMPION')",
        ("DEPLOY-v1", "v1"),
    )
    db_conn.commit()

    promote(db_conn, "v2", model_dir)

    rows = {r["model_version"]: r["status"] for r in
            db_conn.execute("SELECT model_version, status FROM deployments").fetchall()}
    assert rows["v2"] == "CHAMPION"
    assert rows["v1"] == "RETIRED"


def test_promote_refuses_when_artifact_missing(db_conn, tmp_path):
    from ml.train import promote

    with pytest.raises(AssertionError, match="artifact missing"):
        promote(db_conn, "vGHOST", str(tmp_path))

    row = db_conn.execute("SELECT 1 FROM deployments WHERE model_version='vGHOST'").fetchone()
    assert row is None, "must not record a deployment for a version with no artifact"
