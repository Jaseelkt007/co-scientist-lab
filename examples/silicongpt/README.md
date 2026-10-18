# Worked example — SiliconGPT

The lab was first built to design **[SiliconGPT](https://github.com/Jaseelkt007/SiliconGPT)**, a
from-scratch transformer for semiconductor process logic, where the deciding number was
out-of-distribution next-step accuracy on an unseen product family.

- [`lab.json`](lab.json) — that project expressed in the generic lab format: config-mode overrides, a
  local **smoke** tier that runs automatically, a **full** tier on a Slurm cluster that is queued for the
  human (`"manual": true`), OOD top-1 as the primary metric, in-distribution top-1 as a guardrail, and
  `stop_on_target: false` (keep exploring for the full round budget).
- [`PROJECT_CONFIG.md`](PROJECT_CONFIG.md) — the seed `config.md` (goal + criteria rubric) for that run.
- [`DESIGN.md`](DESIGN.md) — the original design notes for the Experiment agent and the tiered
  validation ladder. Historical: the generic version of everything in it now lives in
  `skills/co-scientist-lab/` (`references/lab-config.md`, `scripts/run_experiment.py`).

Paths and commands in these files belong to that project — they illustrate the shape, they won't run here.
