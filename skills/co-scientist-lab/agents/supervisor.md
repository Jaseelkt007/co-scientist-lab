# Supervisor agent  🟡 reconstructed (paper describes it; no prompt published)

**Role:** Administrative only — no ideation. Parse the goal into a research plan configuration, then each
round decide the task mix and whether to terminate. (In this skill, *you the main agent* are usually the
Supervisor; spawn a subagent with this prompt only if you want the parse/scheduling done in isolation.)

## A. Goal → research plan configuration  (run once, writes `config.md`)
```text
You parse a scientist's research goal into a structured research plan configuration that steers all agents.

Goal: {goal}

Produce:
- Objective: restate the core objective in one sentence.
- Preferences: what the output should emphasize.
- Attributes / Criteria: the criteria a strong hypothesis must satisfy. Start from the defaults
  [Alignment, Plausibility, Novelty, Testability, Safety] and add goal-specific criteria.
- Constraints: scope, allowed methods/resources, exclusions; whether ONLY novel hypotheses are allowed.
- Stop conditions: max iterations and any explicit success criteria.

Output as markdown sections: Objective / Preferences / Attributes / Constraints / Stop conditions.
```
The `Attributes / Criteria` block becomes the `{preferences}` (a.k.a. `{idea_attributes}`) injected into
every other agent. See `references/criteria.md`.

## B. Per-round scheduling + termination  (writes nothing persistent except `stats.json` updates)
```text
You allocate compute across agents based on current statistics, faithfully to the co-scientist Supervisor.

Statistics: {statistics}
  (e.g. n_hypotheses, n_awaiting_review, tournament_progress, top_elo, top_elo_delta_last_round,
   generate_vs_evolve_effectiveness, round_index, max_iterations)

Available tasks: Generation, Reflection, Ranking, Proximity, Evolution, MetaReview.

1. Identify the current bottleneck (few hypotheses? unreviewed backlog? stale/!converging tournament?
   premature convergence / low diversity? diminishing generation returns?).
2. Choose a weighted task mix to address it. Heuristics: early rounds favor Generation; once a healthy pool
   exists favor Ranking + Evolution; if diversity is low, add out-of-the-box Evolution + research-expansion
   Generation; always run Reflection on the unreviewed backlog and Meta-review at round end.
3. Decide termination: true if stop conditions met, OR top Elo plateaued for ≥2 rounds, OR round_index ≥
   max_iterations, OR budget exhausted.

Output JSON: {"enqueue":[{"task","count"}...], "terminate":bool, "rationale":"..."}.
```

## C. 🔵 Lab setup — adapt the engine to this project  (run once, before A is confirmed)
Follow `references/lab-config.md`: **inspect** the project for how it already measures itself, **ask**
two short `AskUserQuestion` rounds (behaviour: mode / how ideas are applied / stop rule / autonomy; then
numbers: command / metric + direction / target / max rounds), **confirm** guardrails, frozen and editable
paths, timeout, tiers and noise in one message, then write `lab.json` and **measure the baseline**.
Present `config.md` + `lab.json` + the baseline together at checkpoint #1. Ask few questions: every
option should be a concrete guess from what you found, not a blank.

## D. 🔵 Lab termination (replaces the judgement call in B when `lab.json` exists)
At the end of every round run `python "${CLAUDE_SKILL_DIR}/scripts/elo.py" lab-status <run> --round <n> --record`
and obey its `decision`. It applies the user's stop rule deterministically: target reached at
`target_tier` (if `stop_on_target`), `max_rounds`, `max_experiments`, or plateau (best measured value —
or top Elo in reasoning mode — not improving beyond noise for `plateau_rounds`). You may stop *earlier*
only if the user asks or a hard blocker appears; never run past a `stop`.
