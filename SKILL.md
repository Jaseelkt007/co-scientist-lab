---
name: co-scientist-lab
description: >-
  A measurement-grounded multi-agent discovery engine: replicate Google's AI Co-Scientist
  (generate → debate → Elo-rank → evolve → synthesize) and extend it with an Experiment agent that
  actually trains + benchmarks each hypothesis, so the tournament ranks on measured results, not just
  argument. Use for rigorous multi-agent ideation/discovery on a hard, open-ended goal — e.g. "run a
  discovery loop on …", "tournament-rank hypotheses for …", "find a novel approach/architecture for …".
  Domain-agnostic (science, business, engineering, ML, product, strategy). Quality scales with rounds.
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
> It runs *after* Reflection and *feeds* Ranking: it turns config-expressible hypotheses into real
> train/benchmark runs and writes a measured result, so the tournament weights **measured > simulated >
> reasoned**. Wiring it to your own pipeline needs a small `run_experiment.py` bridge — the spec/result
> schemas and the tiered-validation design are in **[`DESIGN.md`](DESIGN.md)**. Without that bridge, the
> loop still runs as the standard reasoning-based Co-Scientist.

> Verbatim agent prompts and provenance: `references/`. Architecture rationale: `references/architecture.md`.
> The discovery loop, end to end: `docs/agent_orchestration.png`.

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
   `ingest` / `proximity` / `rank`. Hand-writing `hypotheses.json` with the Write tool while `elo.py` also
   touches it is the exact pattern that corrupted a run. (If a subcommand you need is missing, add it to
   `elo.py` rather than hand-editing the JSON.)
4. **Verify with a fresh programmatic read, never trust a stale viewer.** Right after a write, the file
   viewer can show a stale/empty version. To confirm state, run a quick `python -c "import json; ..."`
   read — that reflects what's actually on disk.
5. **Shell variables don't survive a Python heredoc.** Set `RUN=...` in bash itself (not inside a
   `python <<'PY'` block) or later commands get an empty path.

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

### Step 1 — Parse goal → research plan configuration (Supervisor)
Use `agents/supervisor.md` to turn the goal into `config.md` containing:
- **Preferences** (what to emphasize), **Attributes/Criteria** (the rubric a strong hypothesis must meet),
  **Constraints** (scope, methods, exclusions; novelty-required?), **stop conditions** (max iterations).
Start from the 5 default criteria in `references/criteria.md` (Alignment, Plausibility, Novelty,
Testability, Safety) and add goal-specific ones. **This `Attributes/Criteria` block is what makes the
engine domain-agnostic — it is the `{preferences}`/`{idea_attributes}` injected into every agent.**
Confirm the parsed config with the user before the first round (expert-in-the-loop checkpoint #1).

### Step 2 — The improvement loop
Repeat rounds until a **terminal state** (Step 3). Each round, decide a task mix based on `stats.json`
(early rounds favor Generation; later rounds favor Evolution + Ranking). A typical round:

1. **Generate** — spawn 1–N Generation subagents (`agents/generation.md`). Each *returns* a JSON array of
   1–3 hypotheses. Save that array to a temp file and persist it with
   `python scripts/elo.py ingest <run> <file.json> --origin generation:<strategy>` (auto-assigns ids,
   sets `elo:1200`, `status:"new"`). Do **not** hand-write `hypotheses.json`. Always pass the current
   `meta_review.md` and `research_overview.md` to the subagents so generation builds on prior lessons.
2. **Reflect** — for each `new` hypothesis, spawn a Reflection subagent (`agents/reflection.md`):
   initial review → (if it passes) full review → deep verification. Write the review to `reviews/<id>.md`
   and set the verdict with `python scripts/elo.py setstatus <run> <id> reviewed|rejected` (not by editing
   the JSON). Reflection filters flawed / non-novel ideas.
   - **★ Experiment (lab extension)** — after Reflection, spawn the Experiment agent
     (`agents/experiment.md`) on the top *config-expressible* hypotheses: it runs a smoke (and later
     full) train + benchmark and writes a **measured result record**, which Ranking then weights above
     un-measured ideas (**measured > simulated > reasoned**). Needs a project-specific
     `run_experiment.py` bridge (spec/result schemas + the tiered ladder in [`DESIGN.md`](DESIGN.md));
     **skip this step to run as the base reasoning-only loop.**
3. **Proximity** — spawn the Proximity agent (`agents/proximity.md`) (or compute embeddings), have it
   *return* the graph JSON, and persist it with `python scripts/elo.py proximity <run> <graph.json>`.
   Records clusters + near-duplicates so Ranking pairs similar ideas and you can dedupe.
4. **Rank (Elo tournament)** — run matches with `agents/ranking.md`:
   - **Pairing priority:** (a) similar hypotheses (from Proximity), (b) newer and top-ranked hypotheses.
   - **Top-ranked pairs → multi-turn debate** prompt; **lower-ranked pairs → single-turn** comparison.
   - Parse the verdict token `better idea: 1|2` and record the match with
     `python scripts/elo.py match <run> <id_a> <id_b> <1|2> --type debate|single --round <n>`
     (K=32 default; updates Elo and appends to `tournament.json` atomically). Run matches **one at a
     time**, not in a parallel batch — concurrent writers race.
5. **Evolve** — spawn Evolution subagents (`agents/evolution.md`) on the **top-ranked** hypotheses
   (feasibility, grounding, combination, simplification, out-of-the-box). Evolution **creates NEW
   hypotheses** (never edits winners); persist them with `elo.py ingest ... --origin evolution:<strategy>`
   so they enter at `status:"new"` and must re-win the tournament.
6. **Meta-review** — spawn the Meta-review agent (`agents/meta-review.md`) over all reviews + debates.
   **Overwrite `meta_review.md`** with the synthesized critique. This is appended to every agent's prompt
   next round — the system's "learning without back-propagation."
7. **Update `stats.json`** (counts, top Elo, generate-vs-evolve effectiveness) and log a one-line round summary.

### Step 3 — Termination
Stop when **any** holds: criteria/stop-conditions in `config.md` are satisfied; top Elo plateaus across
rounds; the user's iteration cap or token budget is reached; or the user stops it. (The Supervisor checks
this each round, faithfully to the paper: "Supervisor statistics OR max iterations.")

### Step 4 — Final synthesis & handoff
1. Spawn the Meta-review agent to write `research_overview.md`: top directions → per-direction rationale,
   recent findings, and concrete experiments/next-steps (optionally NIH Specific-Aims style), plus
   suggested expert contacts.
2. Present the user: the **ranked hypothesis list** (top N with Elo + one-line rationale) and the
   **research overview** (expert-in-the-loop checkpoint #2 — the human selects what to pursue).

---

## Expert-in-the-loop checkpoints (don't skip)
- **#1** confirm the parsed `config.md` (criteria/constraints) before round 1.
- **Anytime** the user may refine the goal, add their own hypotheses (they enter the tournament at Elo
  1200 and can be combined by Evolution), or submit manual reviews (they feed Ranking + Evolution).
- **#2** final review & selection of top candidates.

## Scaling (test-time compute)
The paper's core finding: **quality rises with rounds.** For a quick pass run 1–2 rounds with a few
hypotheses; for a thorough run, loop many rounds with larger fan-out until budget/plateau. For a
deterministic, heavily-parallel engine, use the orchestration script `scripts/coscientist_workflow.js`
via the Workflow tool (only when the user opts into multi-agent orchestration).

## Tools the agents use
Web search/fetch for grounding (essential for novelty checks), domain databases for constrained spaces,
and any provided private corpus. Specialized models (e.g. AlphaFold-style) plug in as tools when relevant.

## Domain retargeting
To move from medicine to **any** domain, change only `references/criteria.md` (the rubric) and the goal's
preferences/constraints. The machinery (generate → reflect → tournament → evolve → meta-review) is fixed.
