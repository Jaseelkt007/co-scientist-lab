# Co-Scientist Lab

> A **measurement-grounded multi-agent discovery engine** — a faithful replica of Google's
> **AI Co-Scientist**, extended with an **Experiment agent** that *actually trains and benchmarks*
> every hypothesis, so the tournament ranks ideas on **measured results, not just argument**.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Claude Code skill](https://img.shields.io/badge/Claude%20Code-skill-blue.svg)
![Multi-agent](https://img.shields.io/badge/multi--agent-8%20agents-purple.svg)

Instead of answering a hard, open-ended question *once*, a **team of specialized agents** keeps
**generating → reviewing → experimenting → Elo-ranking → evolving** candidate solutions, while a
**meta-review** feeds the round's lessons back into every agent. More rounds = better results
(test-time compute). It's **domain-agnostic** — science, engineering, ML, product, business, strategy.

![The Co-Scientist Lab discovery loop](docs/agent_orchestration.png)

---

## What makes it a "lab" — the Experiment agent ★

The base Co-Scientist ranks ideas by *argument*. **Co-Scientist Lab adds an 8th agent — Experiment —
that actually *runs* each promising hypothesis** (train + benchmark) and writes a **measured result**,
so the Elo tournament weights **measured > simulated > reasoned**. Ideas climb a **three-tier ladder**
so only finalists consume real compute:

- **Tier 0 — debate** (free): every idea.
- **Tier 1 — smoke** (cheap, fast): shortlisted ideas — a directional signal.
- **Tier 2 — full** (real run): finalists only.

It turns open-ended search from *trial-and-error* into **measured, falsifiable evidence** — and it
surfaces honest *negatives*, not just wins.

---

## The agent roster (8)

| Agent | Role |
|---|---|
| 🧭 **Supervisor** | Orchestrates each round; decides when to stop. |
| 💡 **Generation** | Proposes novel, testable hypotheses. |
| 🔍 **Reflection** | Peer-reviews & filters; triages *config-expressible* vs *needs-code*. |
| 🧪 **Experiment ★** | *Trains + benchmarks* each idea → a measured result (the lab's addition). |
| 🧲 **Proximity** | Clusters / de-duplicates hypotheses. |
| 🏆 **Ranking** | Elo tournament (pairwise debate); weights measured > reasoned. |
| 🧬 **Evolution** | Recombines/refines the winners into new hypotheses. |
| 📝 **Meta-review** | Synthesizes the round's lessons; fed into every agent next round. |

---

## Install (as a Claude Code skill)

Clone it straight into your Claude Code skills directory:

```bash
# user-level (available in every project)
git clone https://github.com/Jaseelkt007/co-scientist-lab.git ~/.claude/skills/co-scientist-lab

# …or project-level
git clone https://github.com/Jaseelkt007/co-scientist-lab.git <your-project>/.claude/skills/co-scientist-lab
```

Start a new Claude Code session — the **`co-scientist-lab`** skill is now available. (Python 3 is only
needed for `scripts/elo.py`, which manages the tournament state; no extra packages required.)

---

## Use it — run a discovery loop

Just describe a hard, open-ended goal:

> *"Run a co-scientist-lab discovery loop on: **\<your goal + any constraints / success criteria\>**."*

What happens:

1. **Setup** — the Supervisor turns your goal into a `config.md` (a **criteria rubric** + constraints +
   stop conditions) and confirms it with you (expert-in-the-loop checkpoint #1).
2. **Rounds** — each round: **Generation** proposes → **Reflection** reviews/filters →
   **★ Experiment** trains+benchmarks (if wired — see below) → **Proximity** de-dupes →
   **Ranking** runs an Elo tournament → **Evolution** recombines winners → **Meta-review** synthesizes
   lessons (fed back next round).
3. **Output** — it stops on plateau / your iteration cap / budget and hands you a **ranked shortlist**
   + a **research overview** (checkpoint #2 — you pick what to pursue).

All shared state is plain files under `.coscientist_runs/<slug>/`, so runs **survive interruptions**
and you can resume by re-reading the run directory. **Quality scales with rounds** — 1–2 for a quick
pass, many for a thorough search.

> **Retarget to any domain** by changing only the **criteria rubric** (`references/criteria.md`) and
> your goal's preferences/constraints. The machinery stays fixed.

---

## Wiring the Experiment agent to *your* task

The Experiment agent is task-agnostic, but to actually *run* experiments it needs a small bridge:
a **`run_experiment.py`** that takes an **experiment spec** (a hypothesis as config overrides) and
returns a **measured result JSON**. The spec/result schemas, the tiered-validation ladder, the
methodology guard, and a **full worked example** are in **[`DESIGN.md`](DESIGN.md)**.

**Without the bridge, the loop still runs** as the standard reasoning-based Co-Scientist (Tiers 0
only) — you just don't get the measured grounding.

---

## Worked example — it designed a real model

This engine designed the architecture of **[SiliconGPT](https://github.com/Jaseelkt007/SiliconGPT)** —
a 1.37M-parameter, from-scratch transformer for semiconductor **process logic**. Over two rounds it
tested **eight design levers, rejected five with measured negatives**, and found a counter-intuitive
winner: *shrinking* the model improved out-of-distribution generalization. Measured, reproducible
science — not a guess.

---

## What's in here

```
SKILL.md            the orchestration (the Supervisor's playbook)
agents/             8 agent personas — supervisor · generation · reflection · proximity ·
                    experiment ★ · ranking · evolution · meta-review
references/         architecture rationale · criteria rubric · memory schema
scripts/            elo.py (tournament + state, atomic writes) · coscientist_workflow.js (optional
                    deterministic orchestration via the Workflow tool)
PROJECT_CONFIG.md   an example seed config (goal + criteria rubric)
DESIGN.md           the experiment-grounding design (with a worked example)
docs/               the discovery-loop diagram
```

---

## Credits & attribution

- **Method:** a faithful replica + extension of **Google's AI Co-Scientist** — Gottweis et al.,
  *"Towards an AI co-scientist,"* Nature 2026 / [arXiv:2502.18864](https://arxiv.org/abs/2502.18864).
  All credit for the original multi-agent design goes to that work; this repo replicates it and adds
  the experiment-grounding layer.
- **The Experiment-grounding extension + this packaging:** Mohammed Jaseel Kunnathodika.
- Runs on **Claude Code** (each agent is a Claude subagent).

## License

**MIT** — see [`LICENSE`](LICENSE). Use it freely.
