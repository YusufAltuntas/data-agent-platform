"""Gold-set evaluation (design §11): asks every question in gold.jsonl through the API as alice,
with the real model, and compares the agent's result set with the reference query's result.

Raw output goes to runs/<date>-eval/ (not in git); the summary to eval/results/<date>.md (K23).
Run with `make eval` after `make up REAL_LLM=1`. Every question costs money.

`make eval SET=hard` runs eval/hard.jsonl instead. A question there may carry `expect` (the
expected behaviour, in words) instead of `sql`; such an answer is left to be judged by hand.
"""

import base64
import csv
import io
import itertools
import json
import os
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
TEAM = DATASET = "sales"
RUN_TIMEOUT_S = 200  # above the worker's hard time limit (K10)
RATE_LIMIT_WAIT_S = 15


def kubectl(*args: str, stdin: str | None = None) -> str:
    command = ["kubectl", "--context", "kind-dap", "-n", "dap", *args]
    done = subprocess.run(
        command, input=stdin, capture_output=True, text=True, encoding="utf-8", check=True
    )
    return done.stdout


def reference_rows(sql: str) -> list[list[str]]:
    """Runs a reference query in the dataset's schema, read-only, and returns its rows."""
    psql = (
        f'PGOPTIONS="-c search_path={DATASET} -c default_transaction_read_only=on" '
        'psql -U "$POSTGRES_USER" -d datasets --csv -v ON_ERROR_STOP=1 -f -'
    )
    out = kubectl("exec", "-i", "postgres-0", "--", "sh", "-c", psql, stdin=sql)
    return list(csv.reader(io.StringIO(out)))[1:]  # the first row is the header


def _cell(value: object) -> str:
    """Numbers are compared rounded to 2 decimals; everything else as text."""
    try:
        return f"{round(float(str(value)), 2) + 0.0:.2f}"
    except ValueError:
        return "" if value is None else str(value).strip()


def same_result(reference: list[list[Any]], rows: list[list[Any]]) -> bool:
    """True if some choice of the answer's columns gives the reference rows, in any row order.

    The answer may carry extra columns (an id, a category); it may not have extra or missing rows.
    """
    if len(reference) != len(rows):
        return False
    if not reference:
        return True
    wanted = sorted(tuple(_cell(v) for v in row) for row in reference)
    answer = [[_cell(v) for v in row] for row in rows]
    for columns in itertools.permutations(range(len(answer[0])), len(wanted[0])):
        if sorted(tuple(row[c] for c in columns) for row in answer) == wanted:
            return True
    return False


def ask(client: httpx.Client, base: str, auth: dict[str, str], question: str) -> dict[str, Any]:
    """Starts a run, follows its event stream to the end and returns the run with its step count."""
    while True:
        created = client.post(
            f"{base}/api/teams/{TEAM}/runs",
            headers=auth,
            json={"dataset": DATASET, "question": question},
        )
        if created.status_code != 429:
            break
        time.sleep(RATE_LIMIT_WAIT_S)
    created.raise_for_status()
    run_id = created.json()["run_id"]

    steps = 0
    events_url = f"{base}/api/runs/{run_id}/events"
    with client.stream("GET", events_url, headers=auth, timeout=RUN_TIMEOUT_S) as stream:
        for line in stream.iter_lines():  # the stream ends after the final status event
            if line.startswith("data:") and json.loads(line[5:])["type"] == "llm_call":
                steps += 1

    run = client.get(f"{base}/api/runs/{run_id}", headers=auth)
    run.raise_for_status()
    return {**run.json(), "steps": steps}


def main() -> int:
    provider = kubectl("get", "configmap", "platform-config", "-o", "jsonpath={.data.LLM_PROVIDER}")
    if provider != "openai_compatible":
        print("eval: the cluster runs the fake model; run 'make up REAL_LLM=1' first")
        return 2

    port = os.environ.get("PUBLIC_PORT", "80")
    suffix = "" if port == "80" else f":{port}"
    # Python does not resolve *.localhost on every platform (Windows), so connect to loopback
    # and name the host in the Host header; Traefik routes on it.
    base = f"http://127.0.0.1{suffix}"
    app_host = f"app.localhost{suffix}"
    auth_host = {"Host": f"auth.localhost{suffix}"}
    token_url = f"{base}/realms/dap/protocol/openid-connect/token"
    password = base64.b64decode(
        kubectl("get", "secret", "dap-secrets", "-o", "jsonpath={.data.DAP_ALICE_PASSWORD}")
    ).decode()

    name = sys.argv[1] if len(sys.argv) > 1 else "gold"
    gold_lines = (ROOT / "eval" / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
    gold = [json.loads(line) for line in gold_lines]
    tag = date.today().isoformat() + ("" if name == "gold" else f"-{name}")
    raw_dir = ROOT / "runs" / f"{tag}-eval"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "README.md").write_text(
        "Raw output of `make eval`: one line per gold question in `results.jsonl` (the run as "
        "the API returned it, the reference rows and the verdict).\n",
        encoding="utf-8",
    )

    results = []
    with (
        httpx.Client(timeout=30) as client,
        (raw_dir / "results.jsonl").open("w", encoding="utf-8") as raw,
    ):
        for item in gold:
            grant = {
                "grant_type": "password",
                "client_id": "dap-smoke",
                "username": "alice",
                "password": password,
            }
            # A token per question: access tokens are short-lived.
            token = client.post(token_url, headers=auth_host, data=grant)
            token.raise_for_status()
            auth = {"Host": app_host, "Authorization": f"Bearer {token.json()['access_token']}"}

            started = time.monotonic()
            run = ask(client, base, auth, item["question"])
            seconds = time.monotonic() - started
            reference = correct = None  # no reference query: judged by hand
            if "sql" in item:
                reference = reference_rows(item["sql"])
                rows = (run["answer"] or {}).get("rows") or []
                correct = run["status"] == "succeeded" and same_result(reference, rows)
            result = {
                "id": item["id"],
                "expect": item.get("expect"),
                "correct": correct,
                "seconds": round(seconds, 1),
                "reference": reference,
                "run": run,
            }
            raw.write(json.dumps(result, ensure_ascii=False) + "\n")
            raw.flush()
            results.append(result)
            print(
                f"{item['id']}  correct={VERDICT[correct]:7}  {run['status']}"
                f"  steps={run['steps']}  cost={run['cost_usd']}"
            )

    write_summary(name, tag, results)
    return 0


VERDICT = {True: "yes", False: "no", None: "by hand"}


def write_summary(name: str, tag: str, results: list[dict[str, Any]]) -> None:
    runs = [r["run"] for r in results]
    alias = next((run["model"] for run in runs if run["model"]), "default")
    config = kubectl("get", "configmap", "litellm-config", "-o", "jsonpath={.data.config\\.yaml}")
    models = dict(re.findall(r"model_name: (\S+)\s+litellm_params:\s+model: (\S+)", config))
    image = kubectl(
        "get", "deployment", "litellm", "-o", "jsonpath={.spec.template.spec.containers[0].image}"
    )
    litellm_version = image.split(":", 1)[1].split("@")[0]

    count = len(results)
    compared = [r for r in results if r["correct"] is not None]
    by_hand = [r for r in results if r["correct"] is None]
    correct = sum(r["correct"] for r in compared)
    cost = sum(run["cost_usd"] or 0 for run in runs)
    steps = sum(run["steps"] for run in runs)
    lines = [
        f"# Evaluation {tag}",
        "",
        f"- Questions: {count} (`eval/{name}.jsonl`), asked once each through the API as alice "
        f"on the `{DATASET}` dataset",
        f"- Model: `{alias}` = `{models.get(alias, 'unknown')}` through LiteLLM {litellm_version}",
        f"- Correct: {correct} of {len(compared)} compared with a reference query"
        + (f"; {len(by_hand)} judged by hand (below)" if by_hand else ""),
        f"- Average cost per question: ${cost / count:.4f} (total ${cost:.4f})",
        f"- Average steps per question: {steps / count:.1f}",
        f"- Raw output: `runs/{tag}-eval/` (not in git, K23)",
        "",
        "Correct means the run succeeded and its result set equals the reference query's: same "
        "rows in any order, numbers rounded to 2 decimals; extra columns in the answer are "
        "allowed. Limits: a small gold set, references written in the same period as the "
        "system, one run per question (no repeats, so no variance estimate). The questions "
        "spell out their definitions (what revenue means, which statuses and period count), so "
        "the set does not measure how the agent handles ambiguous questions.",
        "",
        "| Question | Correct | Status | Steps | Cost (USD) | Seconds |",
        "|---|---|---|---|---|---|",
    ]
    for result in results:
        run = result["run"]
        lines.append(
            f"| {result['id']} | {VERDICT[result['correct']]} | {run['status']} "
            f"| {run['steps']} | {run['cost_usd'] or 0:.4f} | {result['seconds']} |"
        )
    if by_hand:
        lines += ["", "## Judged by hand", ""]
    for result in by_hand:
        run = result["run"]
        said = (run["answer"] or {}).get("answer") or f"(no answer; error: {run['error']})"
        lines += [f"- **{result['id']}** Expected: {result['expect']}", f"  - Answer: {said}"]
    summary = ROOT / "eval" / "results" / f"{tag}.md"
    summary.parent.mkdir(exist_ok=True)
    summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"eval: {correct}/{len(compared)} correct; summary in {summary.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
