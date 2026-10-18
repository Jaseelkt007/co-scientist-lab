---
name: co-scientist-lab
description: >-
  A measurement-grounded multi-agent discovery engine: Google's AI Co-Scientist (generate → debate →
  Elo-rank → evolve → synthesize) plus an Experiment agent that runs each promising idea through the
  user's own project (training run, benchmark, test suite) so the tournament ranks on measured results.
  Adapts to any project: it inspects the repo, asks a few setup questions (command, metric, target,
  rounds, what may change), then loops for N rounds or until the target is hit. Use for "run a
  discovery loop on …", "improve <metric> in this repo", "find a better architecture/config for …",
  "tournament-rank hypotheses for …". Also runs reasoning-only for non-code goals. Quality scales with rounds.
---

# Co-Scientist Lab (measurement-grounded multi-agent discovery engine)

A faithful replica of Google's AI Co-Scientist (Gottweis et al., Nature 2026 / arXiv:2502.18864),
**extended with an Experiment agent** so hypotheses are *measured*, not just argued. Instead of
answering once, a **team of specialized subagents** continuously **generate → review → experiment →
rank (Elo tournament) → evolve**, while a **meta-review** feeds lessons back into every agent each
round. More rounds = better results.

**The roster** (each is a subagent persona in `agents/`):
Supervisor (orchestrates), Generation (ideates), Reflection (peer-reviews), Proximity (clusters/dedupes),
**Experiment ★** (trains + benchmarks each hypothesis — the lab extension), Ranking (Elo tournament),
Evolution (refines), Meta-review (synthesizes feedback + final overview).

> **★ The Experiment agent** (`agents/experiment.md`) is the lab's addition to the base Co-Scientist.
> It runs *after* Reflection and *feeds* Ranking: it applies a hypothesis to the user's project (config
> overrides, or a code change in a throwaway git worktree), runs the project's own command through the
> generic harness `scripts/run_experiment.py`, and returns a measured result vs the baseline — so the
> tournament weights **measured > simulated > reasoned**. Everything project-specific is captured once in
> `lab.json` by the **lab setup** (`references/lab-config.md`). Choosing "reasoning only" at setup runs the
> standard Co-Scientist loop.

> Verbatim agent prompts and provenance: `references/`. Architecture rationale: `references/architecture.md`.
> Lab setup + `lab.json` schema: `references/lab-config.md`.

---

## When you (Claude) run this skill

You are the **Supervisor + orchestrator**. You drive the loop in the main thread and spawn the other
agents as **subagents** (the `Agent` tool). All shared state lives in **files** (the "context memory"),
so a run survives interruptions and you can always resume by re-reading the run directory.

### Operational discipline (read this first — it prevents real corruption)
These rules exist because skipping them has actually corrupted run state in practice:

1. **One writer at a time per file.** NEVER run two things that write the same memory file at once —
   e.g. don't fire several `elo.py match` calls (or a Write to `hypotheses.json`) in the *same* parallel
   tool batch. Concurrent writers race and truncate the JSON. Mutate state **sequentially**: one command,
   await it, then the next. (`elo.py` now writes atomically via a temp-file + `os.replace`, which is a
   safety net — but you must still serialize, because the *logic* of two writers still clobbers each other.)
2. **Subagents return data; the orchestrator writes files.** Have Generation/Reflection/Ranking/etc.
   *return* their JSON/verdict to you. YOU then persist it. Don't have subagents and yourself both writing
   the same file — that's how you get two writers.
3. **Mutate JSON only through `scripts/elo.py`, not by hand.** Use `add` / `match` / `setstatus` /
   `ingest` / `proximity` / `rank` / `ingest-experiment` / `lab-status`. Script paths: always
   `python "${CLAUDE_SKILL_DIR}/scripts/<script>"` — the scripts live with this skill, not in the user's
   project. (Below, `elo.py …` / `run_experiment.py …` are shorthand for that.) Hand-writing `hypotheses.json` with the Write tool while `elo.py` also
   touches it is the exact pattern that corrupted a run. (If a subcommand you need is missing, add it to
   `elo.py` rather than hand-editing the JSON.)
4. **Verify with a fresh programmatic read, never trust a stale viewer.** Right after a write, the file
   viewer can show a stale/empty version. To confirm state, run a quick `python -c "import json; ..."`
   read — that reflects what's actually on disk.
5. **Shell variables don't survive a Python heredoc.** Set `RUN=...` in bash itself (not inside a
   `python <<'PY'` block) or later commands get an empty path.
6. **Always use the absolute run path.** Resolve it once (`<project>/.coscientist_runs/<slug>`, absolute)
   and pass that exact path to every script and subagent. Never `cd` into the run dir — a relative path
   used after a `cd` silently creates a nested duplicate run.
7. **Wait for every subagent you spawned** before persisting a round's results and before the final
   handoff. A round is not finished while one of its agents is still running.

### Step 0 — Set up the run (context memory)
1. Get the **research goal** from the user (a sentence to many paragraphs; may include constraints,
   preferences, background, or files). If absent, ask for it.
2. Create a run directory: `.coscientist_runs/<slug>/` where `<slug>` is a short kebab-case name of the goal.
3. Initialize the memory files (schemas in `references/memory-schema.md`):
   - `config.md` — the parsed research plan configuration (see Step 1)
   - `hypotheses.json` — array of hypothesis objects (id, text, summary, category, elo, parents, status)
   - `reviews/<hyp-id>.md` — one file per hypothesis accumulating its reviews
   - `tournament.json` — `{ "matches": [], "elo": {} }`
   - `meta_review.md` — starts empty; the feedback appended to every agent each round
   - `research_overview.md` — final synthesis (written at the end)
   - `stats.json` — counters used to decide scheduling and termination
   - `lab.json`, `experiments/`, `progress.json` — the lab additions (see Step 0b)
   Run `elo.py init <run>` first.
4. Suggest adding `.coscientist_runs/` to the project's `.gitignore` if it isn't already.

### Step 0b — Lab setup: adapt to this project (Supervisor §C)
Follow `references/lab-config.md` exactly: **inspect** the project (how does it already measure itself?),
then **ask two short `AskUserQuestion` rounds** with your detected guesses as the recommended options:
(A) run experiments or reasoning-only · how ideas may change the project (config / code in worktrees /
manual) · stop rule (target-or-N-rounds / exactly N / plateau) · pause between rounds or autonomous;
(B) command · metric + direction · target · max rounds. Confirm guardrails, frozen/editable paths,
timeout, tiers and noise in one message. Write `lab.json`, then **measure the baseline**
(`run_experiment.py <run> --baseline --tier <t> [--repeats 3]`; in code mode inside a clean worktree).
A broken baseline (metric not parsed) must be fixed before round 1.

### Step 1 — Parse goal → research plan configuration (Supervisor)
Use `agents/supervisor.md` to turn the goal into `config.md` containing:
- **Preferences** (what to emphasize), **Attributes/Criteria** (the rubric a strong hypothesis must meet),
  **Constraints** (scope, methods, exclusions; novelty-required?), **stop conditions** (max iterations).
Start from the 5 default criteria in `references/criteria.md` (Alignment, Plausibility, Novelty,
Testability, Safety) and add goal-specific ones. **This `Attributes/Criteria` block is what makes the
engine domain-agnostic — it is the `{preferences}`/`{idea_attributes}` injected into every agent.**
Copy the user's target, max rounds and stop rule into **Stop conditions** so `config.md` and
`lab.json` agree. Confirm the parsed config **together with `lab.json` and the measured baseline** with
the user before the first round (expert-in-the-loop checkpoint #1).

### Step 2 — The improvement loop
Repeat rounds until a **terminal state** (Step 3). Each round, decide a task mix based on `stats.json`
(early rounds favor Generation; later rounds favor Evolution + Ranking). A typical round:

1. **Generate** — spawn 1–N Generation subagents (`agents/generation.md`). Each *returns* a JSON array of
   1–3 hypotheses. Save that array to a temp file and persist it with
   `elo.py ingest <run> <file.json> --origin generation:<strategy>` (auto-assigns ids,
   sets `elo:1200`, `status:"new"`). Do **not** hand-write `hypotheses.json`. Always pass the current
   `meta_review.md` and `research_overview.md` to the subagents so generation builds on prior lessons.
2. **Reflect** — for each `new` hypothesis, spawn a Reflection subagent (`agents/reflection.md`):
   initial review → (if it passes) full review → deep verification. Write the review to `reviews/<id>.md`
   and set the verdict with `elo.py setstatus <run> <id> reviewed|rejected` (not by editing
   the JSON). Reflection filters flawed / non-novel ideas.
   - **★ Experiment (lab extension, measured mode)** — pick up to `stop.max_experiments_per_round`
     reviewed, *testable-now* hypotheses not yet measured (favor new + top-Elo), and spawn one
     Experiment agent (`agents/experiment.md`) per hypothesis. Experiments that share a GPU / port /
     output dir must run **one at a time**; independent CPU-light ones may run in parallel (each writes
     its own result file). For each returned result, **sequentially**:
     `elo.py ingest-experiment <run> <run>/experiments/<id>.<tier>.json`, append the agent's empirical
     review to `reviews/<id>.md`, and in code mode `git worktree remove --force <worktree>` when the
     hypothesis is done with all automatic tiers. Manual-tier finalists go to `experiment_queue.md`.
     **Skipped entirely in reasoning-only mode.**
3. **Proximity** — spawn the Proximity agent (`agents/proximity.md`) (or compute embeddings), have it
   *return* the graph JSON, and persist it with `elo.py proximity <run> <graph.json>`.
   Records clusters + near-duplicates so Ranking pairs similar ideas and you can dedupe.
4. **Rank (Elo tournament)** — run matches with `agents/ranking.md`:
   - **Pairing priority:** (a) similar hypotheses (from Proximity), (b) newer and top-ranked hypotheses.
   - **Top-ranked pairs → multi-turn debate** prompt; **lower-ranked pairs → single-turn** comparison.
   - In measured mode, put both hypotheses' measured results + the target into `{notes}`
     (`agents/ranking.md` §1.3: measured beats reasoned; within-noise is not a win).
   - Parse the verdict token `better idea: 1|2` and record the match with
     `elo.py match <run> <id_a> <id_b> <1|2> --type debate|single --round <n>`
     (K=32 default; updates Elo and appends to `tournament.json` atomically). Run matches **one at a
     time**, not in a parallel batch — concurrent writers race.
5. **Evolve** — spawn Evolution subagents (`agents/evolution.md`) on the **top-ranked** hypotheses
   (feasibility, grounding, combination, simplification, out-of-the-box). Evolution **creates NEW
   hypotheses** (never edits winners); persist them with `elo.py ingest ... --origin evolution:<strategy>`
   so they enter at `status:"new"` and must re-win the tournament.
6. **Meta-review** — spawn the Meta-review agent (`agents/meta-review.md`) over all reviews + debates.
   **Overwrite `meta_review.md`** with the synthesized critique. This is appended to every agent's prompt
   next round — the system's "learning without back-propagation."
7. **Update `stats.json`** (counts, top Elo, generate-vs-evolve effectiveness), then
   `elo.py lab-status <run> --round <n> --record` and log a round summary:
   `round n/max · best <metric> <value> (id, tier) vs baseline <b> → target <t> (<p>% of the way) ·
   experiments this round: k (✓ improves / ✗ worse / ~ neutral) · top Elo · decision`.
8. **Autonomy** — if `lab.json` says `pause_each_round` (or there is no `lab.json`), show that summary
   plus the top 3 and wait for the user to continue, steer, or stop. If `autonomous`, keep going.

### Step 3 — Termination
Obey the `decision` from `elo.py lab-status` (Supervisor §D). It encodes the user's stop rule:
**target reached** (at `target_tier`, when `stop_on_target`), **max rounds**, **experiment budget**, or
**plateau** (best measured value — or top Elo in reasoning mode — not improving beyond noise for
`plateau_rounds`). Also stop if the user says so. Faithful to the paper's "Supervisor statistics OR max
iterations", with the statistics now including real measurements.

### Step 4 — Final synthesis & handoff
1. Spawn the Meta-review agent to write `research_overview.md`: top directions → per-direction rationale,
   recent findings, and concrete experiments/next-steps (optionally NIH Specific-Aims style), plus
   suggested expert contacts.
2. Present the user: **why it stopped**, baseline → best measured result (and whether the target was
   met), the **ranked hypothesis list** (top N with Elo, measured result, one-line rationale), how to
   reproduce each measured winner (overrides file or `git apply <run>/experiments/<id>.<tier>/change.patch`),
   and the **research overview** (expert-in-the-loop checkpoint #2 — the human selects what to pursue).
   Never apply a patch to the user's working tree unless they ask.
3. Clean up: remove any leftover experiment worktrees (`git worktree list`, `git worktree prune`).

## Model allocation (pass `model=` on each `Agent` spawn)
Quality scales with rounds, so spend the strongest model where reasoning decides the outcome and a fast
one on mechanical steps. The session model runs the Supervisor.

| Agent / mode | Model |
|---|---|
| Generation · Evolution · Meta-review | opus |
| Reflection — full + deep verification | opus |
| Reflection — quick initial filter | sonnet |
| Ranking — multi-turn debate (top pairs) | opus |
| Ranking — single-turn (low-stakes pairs) | sonnet |
| Experiment | sonnet (escalate hard implementations to opus) |
| Proximity | haiku |

---

## Expert-in-the-loop checkpoints (don't skip)
- **#1** confirm the parsed `config.md` (criteria/constraints) before round 1.
- **Anytime** the user may refine the goal, add their own hypotheses (they enter the tournament at Elo
  1200 and can be combined by Evolution), or submit manual reviews (they feed Ranking + Evolution).
- **#2** final review & selection of top candidates.

## Scaling (test-time compute)
The paper's core finding: **quality rises with rounds.** For a quick pass run 1–2 rounds with a few
hypotheses; for a thorough run, loop many rounds with larger fan-out until budget/plateau. For a
deterministic, heavily-parallel engine, use the orchestration script
`${CLAUDE_SKILL_DIR}/scripts/coscientist_workflow.js` via the Workflow tool (only when the user opts into
multi-agent orchestration). That script is **reasoning-only** (workflow scripts have no shell access), so
measured runs use the main-thread loop above.

## Tools the agents use
Web search/fetch for grounding (essential for novelty checks), domain databases for constrained spaces,
and any provided private corpus. In measured mode: the project itself (Bash, git worktrees) through
`scripts/run_experiment.py`. Worked example of a full lab setup: `${CLAUDE_PLUGIN_ROOT}/examples/silicongpt/`.

## Domain retargeting
To move from medicine to **any** domain, change only `references/criteria.md` (the rubric) and the goal's
preferences/constraints. The machinery (generate → reflect → tournament → evolve → meta-review) is fixed.
