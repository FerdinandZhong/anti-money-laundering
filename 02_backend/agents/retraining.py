"""Retraining agent workflow — the backbone for auto-retraining + canary deploy.

Same supervisor/SSE shape as agents/supervisor.py (a generator yielding event
dicts), but a DETERMINISTIC pipeline the LLM narrates rather than drives:

  PREPARE  -> count the human tx-labels + annotations feeding the training set
  TRAIN    -> Cloudera AI Workbench: create training job -> run it -> poll;
              falls back to a local train_model() when no Workbench is configured
  CANARY   -> Workbench: build + deploy the retrained model ("canary"); reflected
              as a CANARY row in the ops `deployments` table
  PROMOTE  -> flip the canary to CHAMPION (what ml/scorer.py + Dashboard B read)
  NARRATE  -> one streamed LLM summary of what happened

Event shapes (mirrors supervisor.py):
  {"type": "phase",  "phase": str}
  {"type": "step",   "step": str, "status": "start"|"ok"|"skip"|"error", "detail": str}
  {"type": "token",  "text": str}
  {"type": "done",   "model_version": str, "deployment_id": str, "mode": str}
"""
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "02_backend"))

import json
import time
import datetime
from typing import Generator

from agents.llm_client import chat
from common import workbench
from common.db import get_connection
from common.config import get_config
from ml.train import train_model


def _e(type_: str, **kw) -> dict:
    return {"type": type_, **kw}


def _new_version() -> str:
    return "v" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


_NARRATE_SYSTEM = (
    "You are an MLOps engineer. In 3-4 short sentences, summarize this AML model "
    "retraining + canary deployment for a compliance audience: what data retrained "
    "it, how it was trained (Cloudera AI Workbench job or local), and that the new "
    "version was canary-deployed then promoted to CHAMPION. Be concrete and factual."
)


def run_retraining(triggered_by: str = "manual") -> Generator[dict, None, None]:
    """Drive the retrain -> canary -> promote pipeline, yielding SSE event dicts.

    Opens its own DB connection (safe to run in a daemon thread or SSE stream).
    """
    cfg = get_config()
    wb_cfg = cfg.get("workbench") or {}
    conn = get_connection()
    mode = workbench.mode() if workbench.configured() else "local"
    deployment_id = ""
    model_version = ""

    try:
        # ── PREPARE ───────────────────────────────────────────────────────────
        yield _e("phase", phase="PREPARE")
        n_labels = conn.execute("SELECT COUNT(*) FROM transaction_labels").fetchone()[0]
        n_annot = conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]
        yield _e("step", step="dataset", status="ok",
                 detail=f"triggered_by={triggered_by} · mode={mode} · "
                        f"{n_labels} human tx-labels, {n_annot} case annotations "
                        f"(training label = COALESCE(human, synthetic))")

        # ── TRAIN ─────────────────────────────────────────────────────────────
        yield _e("phase", phase="TRAIN")
        trained_remotely = False
        if mode != "local":
            try:
                script = wb_cfg.get("train_script", "02_backend/ml/train.py")
                runtime_id = wb_cfg.get("runtime_id") or None
                yield _e("step", step="create_job", status="start",
                         detail=f"create training job → {script}")
                job_id = workbench.create_training_job(
                    name=wb_cfg.get("job_name", "aml-retrain"),
                    script=script, runtime_id=runtime_id)
                yield _e("step", step="create_job", status="ok", detail=f"job_id={job_id}")

                run_id = workbench.run_job(job_id)
                yield _e("step", step="run_job", status="start", detail=f"run_id={run_id}")

                interval = float(wb_cfg.get("poll_interval_s", 10))
                max_polls = int(wb_cfg.get("max_polls", 30))
                status = "ENGINE_SCHEDULING"
                for i in range(max_polls):
                    time.sleep(interval)
                    run = workbench.get_job_run(job_id, run_id)
                    status = str(run.get("status", ""))
                    yield _e("step", step="run_job", status="start",
                             detail=f"poll {i+1}/{max_polls}: {status}")
                    if workbench.run_terminal(status):
                        break
                if not workbench.run_succeeded(status):
                    raise workbench.WorkbenchError(f"job run did not succeed: {status}")

                model_version = _new_version()
                conn.execute(
                    "INSERT OR IGNORE INTO model_runs (run_id, model_version, status, metrics) "
                    "VALUES (?, ?, ?, ?)",
                    (f"RUN-{model_version}", model_version, "COMPLETE",
                     json.dumps({"source": "workbench", "job_id": job_id, "run_id": run_id})),
                )
                conn.commit()
                trained_remotely = True
                yield _e("step", step="run_job", status="ok",
                         detail=f"{status} → model {model_version}")
            except workbench.WorkbenchError as ex:
                yield _e("step", step="train_workbench", status="error",
                         detail=f"{ex} — falling back to local training")
                mode = "local"

        if not trained_remotely:
            yield _e("step", step="train_local", status="start",
                     detail="training locally (train_model)")
            model_version = train_model(conn)  # writes artifact + model_runs row
            yield _e("step", step="train_local", status="ok",
                     detail=f"trained → model {model_version}")

        # ── CANARY ────────────────────────────────────────────────────────────
        yield _e("phase", phase="CANARY")
        deployment_id = f"DEPLOY-{model_version}"
        if trained_remotely:
            try:
                yield _e("step", step="canary_deploy", status="start",
                         detail="Workbench: build + deploy model")
                info = workbench.canary_deploy(
                    model_version=model_version,
                    model_name=wb_cfg.get("model_name", "aml-risk-model"),
                    script=wb_cfg.get("serving_script", wb_cfg.get("train_script", "02_backend/ml/train.py")),
                    function_name=wb_cfg.get("serving_function", "predict"),
                    runtime_id=wb_cfg.get("runtime_id") or None)
                deployment_id = info["deployment_id"]
                yield _e("step", step="canary_deploy", status="ok",
                         detail=f"CML deployment {deployment_id} (build {info['build_id']})")
            except workbench.WorkbenchError as ex:
                yield _e("step", step="canary_deploy", status="skip",
                         detail=f"{ex} — recording canary in ops DB only")

        conn.execute(
            "INSERT OR REPLACE INTO deployments "
            "(deployment_id, model_version, environment, traffic_pct, status, deployed_at) "
            "VALUES (?, ?, 'production', ?, 'CANARY', ?)",
            (deployment_id, model_version, float(wb_cfg.get("canary_traffic_pct", 10.0)),
             datetime.datetime.now(datetime.timezone.utc).isoformat()),
        )
        conn.commit()
        yield _e("step", step="canary_record", status="ok",
                 detail=f"deployments row {deployment_id} → CANARY")

        # ── PROMOTE ───────────────────────────────────────────────────────────
        yield _e("phase", phase="PROMOTE")
        conn.execute("UPDATE deployments SET status='RETIRED', rolled_back_at=? "
                     "WHERE status='CHAMPION' AND deployment_id != ?",
                     (datetime.datetime.now(datetime.timezone.utc).isoformat(), deployment_id))
        conn.execute("UPDATE deployments SET status='CHAMPION', traffic_pct=100.0 "
                     "WHERE deployment_id=?", (deployment_id,))
        conn.commit()
        yield _e("step", step="promote", status="ok",
                 detail=f"{deployment_id} ({model_version}) → CHAMPION; scorer + Dashboard now use it")

        # ── SCORE ─────────────────────────────────────────────────────────────
        # Refresh the alert queue with the freshly promoted champion. Without
        # this the retrain flow leaves a model but no alerts (empty dashboard) —
        # the scorer is the only thing that writes the ALERT-ML queue.
        yield _e("phase", phase="SCORE")
        try:
            from ml.scorer import score_transactions
            created = score_transactions(conn)
            yield _e("step", step="score", status="ok",
                     detail=f"scored champion → {created} new alert(s) in the queue")
        except Exception as ex:
            yield _e("step", step="score", status="error", detail=f"scoring failed: {ex}")

        # ── NARRATE ───────────────────────────────────────────────────────────
        yield _e("phase", phase="NARRATE")
        row = conn.execute("SELECT metrics FROM model_runs WHERE model_version=?",
                           (model_version,)).fetchone()
        metrics = row["metrics"] if row else "{}"
        ctx = (f"trigger={triggered_by}; mode={mode}; labels={n_labels}; "
               f"annotations={n_annot}; new_version={model_version}; "
               f"deployment={deployment_id}; metrics={metrics}")
        try:
            for tok in chat([{"role": "system", "content": _NARRATE_SYSTEM},
                             {"role": "user", "content": ctx}], stream=True):
                yield _e("token", text=tok)
        except Exception as ex:  # LLM unreachable locally — canned summary
            yield _e("token", text=(
                f"Retrained on {n_labels} analyst tx-labels + synthetic fill ({mode}); "
                f"model {model_version} canary-deployed as {deployment_id} and promoted "
                f"to CHAMPION. [narration LLM unavailable: {ex}]"))

        yield _e("done", model_version=model_version, deployment_id=deployment_id, mode=mode)
    finally:
        conn.close()


if __name__ == "__main__":
    # Self-check: local-fallback pipeline must produce a model_runs row and flip
    # the CHAMPION deployment to the freshly trained version.
    conn = get_connection()
    before = conn.execute(
        "SELECT model_version FROM deployments WHERE status='CHAMPION'").fetchone()
    conn.close()

    saw_canary = saw_promote = False
    final = {}
    for evt in run_retraining("self-check"):
        if evt.get("type") == "step" and evt.get("step") == "canary_record":
            saw_canary = True
        if evt.get("type") == "step" and evt.get("step") == "promote":
            saw_promote = True
        if evt.get("type") == "done":
            final = evt
        print(evt if evt.get("type") != "token" else evt["text"], end="" if evt.get("type") == "token" else "\n")
    print()

    conn = get_connection()
    champ = conn.execute(
        "SELECT model_version, deployment_id FROM deployments WHERE status='CHAMPION'").fetchone()
    run = conn.execute(
        "SELECT 1 FROM model_runs WHERE model_version=?", (final.get("model_version"),)).fetchone()
    conn.close()

    assert final.get("model_version"), "no model_version in done event"
    assert saw_canary and saw_promote, "missing canary/promote steps"
    assert run is not None, "no model_runs row for the new version"
    assert champ["model_version"] == final["model_version"], "CHAMPION not flipped to new version"
    print(f"[retraining] OK — CHAMPION {before['model_version'] if before else '∅'} "
          f"→ {champ['model_version']} (deployment {champ['deployment_id']})")
