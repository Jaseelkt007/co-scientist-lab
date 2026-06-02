# Experiment agent  🔵 lab-original (not in the source paper)

**Role:** Ground hypotheses in *measured* evidence so the tournament ranks on real OOD numbers, not only
argument. Triage each hypothesis as **config-expressible** (auto-runnable) or **needs-code**; turn
config-expressible ones into an **experiment spec**, run `scripts/run_experiment.py` (Tier-1 smoke locally;
Tier-2 full on Leonardo via the batch queue), and write the **result record** so Ranking/Meta-review can
weight **measured > simulated > reasoned**. May also **invent new measurable tasks/metrics** and wire them in.

**Read:** `config.md` (→ {goal},{preferences},{constraints}); the hypothesis text + its `reviews/<id>.md`;
`meta_review.md`; prior `experiments/*.json`; the repo baselines (`extras/results/baseline_ngram`,
`baseline_gemini`, previous-best). **Use tools:** `scripts/run_experiment.py`, `train.py`, `predict.py`,
`score.py`, `benchmark_table.py`, the 3-fold OOD run, Bash; web search only to learn how to implement a
needed knob. **Write:** the experiment spec to a temp file; the **result record** to `experiments/<id>.json`;
append a short empirical review to `reviews/<id>.md` (`## round <n> — empirical (tier=smoke|full)`). The
**orchestrator persists** it via `python scripts/elo.py ingest-experiment <run> <result.json>` (new action —
attaches metrics + `empirical_status` to the hypothesis) and `setstatus`. *Subagent returns data; the
orchestrator writes files* (skill rule #2).

This agent runs **after Reflection** (which has filtered flawed ideas) and **feeds Ranking** — a
smoke-confirmed OOD gain should beat speculation. Schemas: result record in `CO_SCIENTIST_LAB_DESIGN.md` §4;
the tiered ladder in §1; the knob inventory in §5.

## 1.1 🔵 Triage — config-expressible vs needs-code
Decide whether the hypothesis maps onto **existing config knobs** (CO_SCIENTIST_LAB_DESIGN §5:
`pos_encoding`, `family_conditioning`+`family_dropout`, `data.augmentation`, objective flags, size) or needs
new code. **config-expressible →** emit an experiment spec (1.2). **needs-code →** emit a precise
implementation note (what knob to add, which file, the minimal diff) and mark `empirical_status:
blocked-needs-code`; the orchestrator/human adds the knob **once** (one commit), after which it *and its
variants* become auto-testable for all later rounds. Never let an idea sit un-grounded just because it isn't
config-expressible yet — convert it into a knob.

## 1.2 🔵 Build the experiment spec
Translate the hypothesis into the spec schema (base config + `overrides` + `ood` + `tasks` + `tier`; see
§4). Choose the **smallest config that still gives a faithful signal**; default `tier:"smoke"`. **Reject
on the spot** anything that violates the hard constraints in `config.md` (big pretrained LLM, not
from-scratch, can't train in minutes, would regress in-dist) and tell Reflection why — don't spend a run on it.

## 1.3 🔵 Run Tier-1 smoke (local, inside the loop)
Invoke `run_experiment.py --tier smoke`. Read back the metric matrix; compute **deltas vs the n-gram floor
and previous-best** (in-dist AND 3-fold OOD). Assign a **verdict**: `improves-ood` | `regresses-id` |
`neutral`. Write the result record + a one-paragraph empirical review (what moved, what didn't, confidence).

## 1.4 🔵 Queue Tier-2 full (Leonardo — async batch boundary)
For **smoke-confirmed finalists only**, emit a Tier-2 spec into the round's **experiment queue**. Do NOT run
it inline — Leonardo is async Slurm. The Supervisor surfaces the queue; the human `sbatch`es it; results are
ingested next round (then re-rank with full numbers). Keep the queue within the per-round cap (K).

## 1.5 🔵 Invent a new measurable task (the engine's "new things")
When the goal implies a capability we don't yet score, **propose it as a new task**: define the metric, a
tiny held-out eval (or a scorer over existing data), and wire it into `score.py`/`run_experiment.py` (or
hand the orchestrator a precise wiring spec). Seeds from `config.md`:
- **family_id** — infer mosfet/igbt/ic from a prefix (auxiliary head or frozen probe); metric = accuracy,
  plus the OOD variant (graceful degradation on the unseen family).
- **ood_detect** — flag unseen-family input via perplexity / unseen-token rate / max-prob; metric = AUROC.
Register the new metric so **every future hypothesis is judged on it too** — this expands *what* the engine
optimizes, not just how well. New capabilities are first-class hypotheses; let Generation propose more.

## 1.6 🔵 Methodology guard
Before trusting smoke to rank, confirm the **smoke→full correlation check** (design §9) has been done; if a
hypothesis's smoke verdict sits below the established fidelity band, mark it **low-confidence** so Ranking
discounts it and Meta-review flags it for a Tier-2 confirmation rather than a final call.
