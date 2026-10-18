# Lab setup — adapting the engine to *this* project

The lab is generic; everything project-specific lives in **`<run>/lab.json`**, written **once** at setup
by the orchestrator and read by `scripts/run_experiment.py` and `scripts/elo.py lab-status`. This file
is the playbook for producing it: **inspect first, propose, then ask only what you couldn't infer.**

---

## 1. Inspect the project before asking anything (2–5 minutes, read-only)

Look for how this project already measures itself, so your questions come with good defaults:
- README / CONTRIBUTING / Makefile / `justfile` / `package.json` scripts / `pyproject.toml` / `tox.ini`
- training or eval entry points: `train*.py`, `eval*.py`, `benchmark*`, `score*`, `scripts/`, notebooks
- test suites (`pytest`, `npm test`, `cargo test`, `go test`) and benchmarks (`pytest-benchmark`,
  `hyperfine`, `criterion`, `k6`, `lighthouse`)
- config systems (`configs/*.yaml`, Hydra, argparse flags, `.env`) → candidate **knobs**
- prior results (`results/`, `benchmark.md`, wandb/mlflow logs) → candidate **baseline + target**
- `git status` (clean tree? uncommitted work?) and what is gitignored (data/, checkpoints/ — matters
  for worktrees)

If there is an obvious cheap command, **dry-run it once** (with a short timeout) to see the real output
format — that is how you write a metric pattern that actually matches.

## 2. Ask — two short rounds with `AskUserQuestion`

Put your detected guess first in each question and mark it **(Recommended)**. The user can always pick
"Other" and type their own. If `AskUserQuestion` isn't available (headless run), ask the same questions in
plain text in one message and proceed with the recommended defaults for anything unanswered.

**Round A — how the lab should behave** (one `AskUserQuestion` call, 4 questions):

| Header | Question | Options (adapt) |
|---|---|---|
| Mode | Should ideas be tested by actually running experiments? | **Run experiments** · Reasoning only (classic Co-Scientist) |
| Apply ideas | How may an idea change the project? | **Config/CLI parameters only** (safest) · **Code changes** in isolated git worktrees · **I run them myself** (cluster / manual) |
| Stop when | When should the loop stop? | **Target reached or N rounds** · Exactly N rounds (keep exploring) · On plateau / budget only |
| Autonomy | Should I pause between rounds? | **Pause after each round** for review · Fully autonomous until a stop condition |

If they chose **Reasoning only**, write `{"mode": "reasoning", "stop": {...}}` and skip to step 4 — the
loop runs as the base Co-Scientist, and `lab-status` still enforces rounds / Elo plateau.

**Round B — the numbers** (second `AskUserQuestion` call; options pre-filled from step 1):

| Header | Question | Options (adapt) |
|---|---|---|
| Command | Which command measures one candidate? | detected commands (e.g. `python train.py {args} --out {out_dir}`, `pytest -q benchmarks/`) |
| Metric | Which number decides, and is higher or lower better? | detected metrics (e.g. `val_acc ↑`, `p95_latency_ms ↓`, `loss ↓`) |
| Target | What value counts as success? | e.g. `+5% over baseline` · a value from prior results · no target (just maximize) |
| Rounds | Maximum number of rounds? | 3 · **5** · 10 |

Then confirm (plain text, one message) the details you inferred and the user can correct in one reply:
**guardrails** (metrics that must not regress, with tolerance), **frozen** paths (evaluation code, test
data, metric definitions — never editable, this is the anti-gaming rule), **editable** paths (code mode),
**timeout** per experiment, **smoke vs full** tier (is there a cheap proxy run?), **noise** (is the
metric noisy → repeat baseline 3×), and **max experiments per round / in total**.

## 3. Write `lab.json`, measure the baseline, confirm

1. Write `<run>/lab.json` (schema below) with the Write tool — this is the only time you write it.
2. Measure the baseline for every **automatic** tier:
   `python "${CLAUDE_SKILL_DIR}/scripts/run_experiment.py" <run> --baseline --tier <tier> [--repeats 3]`
   - **Code mode:** measure the baseline in a clean worktree of `HEAD` (`--workdir <worktree>`), the same
     way hypotheses will be measured — otherwise uncommitted local changes skew every delta.
   - If the primary metric isn't found, fix the pattern/command now (look at `experiments/baseline.<tier>.log`).
     **Never start round 1 with a broken baseline.**
3. Show the user, together with `config.md` (checkpoint #1): command, metric + direction, **baseline
   value (and noise)**, target, guardrails, frozen paths, stop rule. Start only after they confirm.

If a **target** was given as a relative change ("+5%"), convert it to an absolute number from the
measured baseline and write it into `lab.json` before round 1.

---

## `lab.json` schema

```json
{
  "mode": "measured",
  "project_dir": "/abs/path/to/project",
  "change_mode": "config",
  "editable": ["configs/", "src/model.py"],
  "frozen": ["eval/", "data/test/", "scripts/score.py"],
  "workspace_setup": "ln -sfn {project_dir}/data data",
  "tiers": {
    "smoke": { "command": "python train.py {args} --max-iters 200 --out {out_dir}", "timeout_s": 900 },
    "full":  { "command": "sbatch jobs/full.sh {config}", "manual": true }
  },
  "metrics": {
    "primary": { "name": "val_acc", "goal": "max", "source": "stdout_regex", "pattern": "val_acc=([0-9.]+)" },
    "guardrails": [
      { "name": "id_acc", "goal": "max", "source": "json_file", "path": "{out_dir}/metrics.json",
        "key": "id.acc", "tolerance": 0.01 }
    ]
  },
  "noise": 0.0,
  "stop": {
    "max_rounds": 5,
    "target": 0.78,
    "target_tier": "smoke",
    "stop_on_target": true,
    "plateau_rounds": 2,
    "max_experiments": 30,
    "max_experiments_per_round": 4
  },
  "autonomy": "pause_each_round"
}
```

| Field | Meaning |
|---|---|
| `mode` | `measured` (run experiments) or `reasoning` (no harness; only `stop` is used) |
| `change_mode` | `config` — an idea is a set of overrides written to `experiments/<id>.config.json`, rendered into the command as `{config}` / `{args}`; no files edited. `code` — the Experiment agent edits code in a throwaway **git worktree**; the diff is saved as `experiments/<id>.<tier>/change.patch`. `manual` — Claude prepares the spec + rendered command, the user runs it and reports numbers. |
| `editable` / `frozen` | Path prefixes (ending `/`) or globs. Changes outside `editable` are flagged; touching `frozen` makes the result **invalid** (`touched-frozen`) and it is not run. Always freeze whatever computes the metric. |
| `workspace_setup` | Code mode only: run once in each new worktree, e.g. to link gitignored data/checkpoints. Files it creates are excluded from the patch. |
| `tiers` | Ordered cheapest → most faithful. `command` placeholders: `{config}` `{args}` `{id}` `{tier}` `{out_dir}` `{project_dir}` `{workdir}` `{run_dir}` (paths are shell-quoted). `manual: true` = never run automatically; queue it for the user. `timeout_s` kills the whole process group. |
| `metrics.*.source` | `stdout_regex` (`pattern`, last match, group 1) · `file_regex` (`path` + `pattern`) · `json_file` (`path` + dotted `key`). `goal`: `max` or `min`. |
| `guardrails[].tolerance` | How much worse than baseline is still acceptable (absolute units). |
| `noise` | Minimum improvement that counts as real. The baseline's measured spread (`--repeats`) is also used; the larger wins. |
| `stop.target_tier` | Which tier's results count toward the target (default: the last tier). Use the cheapest *automatic* tier if the faithful tier is manual and you want the loop to stop by itself. |
| `stop.plateau_rounds` | Stop if the best measured value hasn't improved by more than `noise` over this many rounds (Elo plateau in reasoning mode, threshold `elo_plateau_delta`, default 10). |
| `autonomy` | `pause_each_round` (show the round summary + `lab-status`, wait for "continue") or `autonomous`. |

`{args}` rendering of a JSON config: `{"lr": 0.001, "rope": true, "off": false, "layers": [2, 4]}` →
`--lr 0.001 --rope --layers 2 4` (false/null keys are omitted; keys already starting with `-` are kept).

## Manual tier (cluster / human-run) protocol
1. `run_experiment.py <run> --id h7 --tier full --config <cfg> --render` → the exact command.
2. Add it to `experiment_queue.md` (id, command, why it's a finalist). Tell the user.
3. When results come back: either `--log <their output file>` (parsed with the same metric specs) or
   `--set val_acc=0.81 id_acc=0.90` for numbers they paste. Then `elo.py ingest-experiment`.
