#!/usr/bin/env python3
"""Generic experiment harness for co-scientist-lab: run the project's command, read its metrics,
compare against the baseline, write one result record.

Everything project-specific lives in <run_dir>/lab.json (written once at setup — schema in
references/lab-config.md). This script only renders the command, runs it, and parses numbers.

Usage:
  python run_experiment.py <run_dir> --baseline [--tier T] [--repeats N]
  python run_experiment.py <run_dir> --id h3 [--tier T] [--config FILE] [--workdir DIR]
  python run_experiment.py <run_dir> --id h3 --tier T --render          # print the command, don't run
  python run_experiment.py <run_dir> --id h3 --tier T --log FILE         # parse output of an external run
  python run_experiment.py <run_dir> --id h3 --tier T --set acc=0.81     # record numbers reported by hand

Writes <run_dir>/experiments/<id>.<tier>.json (+ .log). Exit code 0 = done, 1 = failed/timeout,
2 = bad lab.json/usage. Standard library only.
"""
import argparse, fnmatch, json, os, re, shlex, signal, subprocess, sys, tempfile, time, contextlib

PLACEHOLDER = re.compile(r"\{(config|args|id|tier|out_dir|project_dir|workdir|run_dir)\}")


def _load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(path, obj):
    # Atomic write (unique temp + os.replace) — same discipline as elo.py.
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".exp-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise


def _quote(s):
    s = str(s)
    if os.name == "nt":
        return f'"{s}"' if (" " in s or not s) else s
    return shlex.quote(s)


def config_to_args(cfg):
    """{"lr": 0.001, "use_rope": true, "layers": [2, 4]} -> --lr 0.001 --use_rope --layers 2 4"""
    out = []
    for k, v in cfg.items():
        flag = k if k.startswith("-") else f"--{k}"
        if v is None or v is False:
            continue
        if v is True:
            out.append(flag)
        elif isinstance(v, (list, tuple)):
            out += [flag] + [_quote(x) for x in v]
        else:
            out += [flag, _quote(v)]
    return " ".join(out)


def render(template, ctx):
    # Only known {placeholders} are substituted, so shell braces like awk '{print $1}' survive.
    return PLACEHOLDER.sub(lambda m: ctx[m.group(1)], template)


def _dig(obj, dotted):
    for part in dotted.split("."):
        if isinstance(obj, list) and part.lstrip("-").isdigit():
            obj = obj[int(part)]
        elif isinstance(obj, dict) and part in obj:
            obj = obj[part]
        else:
            raise KeyError(dotted)
    return obj


def read_metric(spec, log_text, ctx, workdir):
    """Return a float, or raise ValueError/KeyError with a reason."""
    src = spec.get("source", "stdout_regex")
    if src in ("stdout_regex", "file_regex"):
        text = log_text
        if src == "file_regex":
            path = os.path.join(workdir, render(spec["path"], ctx))
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        matches = list(re.finditer(spec["pattern"], text, re.MULTILINE))
        if not matches:
            raise ValueError(f"pattern {spec['pattern']!r} not found")
        m = matches[-1]  # last occurrence = final value (e.g. last epoch)
        return float(m.group(1) if m.groups() else m.group(0))
    if src == "json_file":
        path = os.path.join(workdir, render(spec["path"], ctx))
        return float(_dig(_load(path, {}), spec["key"]))
    raise ValueError(f"unknown metric source {src!r}")


def all_metric_specs(lab):
    m = lab["metrics"]
    return [m["primary"]] + list(m.get("guardrails", []))


def run_command(cmd, workdir, env, log_path, timeout):
    start = time.time()
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        log.write(f"$ {cmd}\n")
        log.flush()
        kw = {"start_new_session": True} if os.name != "nt" else {}
        p = subprocess.Popen(cmd, shell=True, cwd=workdir, env=env, stdout=log,
                             stderr=subprocess.STDOUT, **kw)
        try:
            code = p.wait(timeout=timeout)
            status = "done" if code == 0 else "failed"
        except subprocess.TimeoutExpired:
            # Kill the whole process group, not just the shell, so training jobs don't linger.
            if os.name != "nt":
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(p.pid, signal.SIGTERM)
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(p.pid, signal.SIGKILL)
            else:
                p.kill()
            p.wait()
            code, status = None, "timeout"
    return status, code, round(time.time() - start, 1)


def _git(workdir, *args):
    r = subprocess.run(["git", "-C", workdir, *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def _untracked(workdir):
    return set(filter(None, (_git(workdir, "ls-files", "--others", "--exclude-standard") or "").splitlines()))


def is_frozen(path, patterns):
    for pat in patterns:
        if pat.endswith("/") and (path + "/").startswith(pat):
            return True
        if fnmatch.fnmatch(path, pat) or path == pat.rstrip("/"):
            return True
    return False


def prepare_worktree(lab, run_dir, workdir, out_dir, ctx):
    """Code mode, isolated worktree: run workspace_setup once, then capture the hypothesis's change
    as a patch and refuse to run if it touched a frozen path (eval code, test data, ...)."""
    marker = os.path.join(run_dir, "experiments", ".setup", re.sub(r"[^\w.-]", "_", workdir) + ".json")
    state = _load(marker)
    if state is None:
        before = _untracked(workdir)
        setup = lab.get("workspace_setup")
        if setup:
            r = subprocess.run(render(setup, ctx), shell=True, cwd=workdir, capture_output=True, text=True)
            if r.returncode != 0:
                return {"status": "failed", "error": f"workspace_setup failed: {r.stderr.strip()[-500:]}"}
        state = {"setup_paths": sorted(_untracked(workdir) - before)}
        _save(marker, state)
    new_files = sorted(_untracked(workdir) - set(state["setup_paths"]))
    if new_files:
        _git(workdir, "add", "-N", "--", *new_files)  # intent-to-add so new files show up in the diff
    changed = [f for f in (_git(workdir, "diff", "--name-only", "HEAD") or "").splitlines() if f]
    patch = _git(workdir, "diff", "--binary", "HEAD") or ""
    info = {"changed_files": changed}
    if patch:
        pp = os.path.join(out_dir, "change.patch")
        with open(pp, "w", encoding="utf-8") as f:
            f.write(patch)
        info["patch"] = os.path.relpath(pp, run_dir)
    editable = lab.get("editable") or []
    outside = [f for f in changed if editable and not is_frozen(f, editable)]
    if outside:
        info["outside_editable"] = outside  # allowed, but flagged for Reflection/Meta-review
    touched = [f for f in changed if is_frozen(f, lab.get("frozen", []))]
    if touched:
        info.update(status="invalid", error=f"touched frozen paths: {touched}")
    return info


def better(goal, a, b):
    """Signed improvement of a over b (positive = better) for a max/min goal."""
    return (a - b) if goal == "max" else (b - a)


def judge(lab, metrics, baseline):
    """Deltas vs baseline, guardrail checks, verdict, target."""
    prim = lab["metrics"]["primary"]
    name, goal = prim["name"], prim.get("goal", "max")
    noise = max(float(lab.get("noise") or 0), float((baseline or {}).get("noise") or 0))
    out = {"noise": noise, "delta": {}, "guardrails": [], "improvement": None,
           "verdict": "unbaselined", "target_met": None}
    value = metrics.get(name)
    target = (lab.get("stop") or {}).get("target")
    if value is not None and target is not None:
        out["target_met"] = better(goal, value, float(target)) >= 0
    base = (baseline or {}).get("metrics") or {}
    for k, v in metrics.items():
        if k in base:
            out["delta"][k] = round(v - base[k], 6)
    regressed = False
    for g in lab["metrics"].get("guardrails", []):
        gv, gb = metrics.get(g["name"]), base.get(g["name"])
        row = {"name": g["name"], "value": gv, "baseline": gb, "tolerance": g.get("tolerance", 0)}
        if gv is not None and gb is not None:
            row["regressed"] = better(g.get("goal", "max"), gv, gb) < -float(g.get("tolerance", 0))
            regressed |= row["regressed"]
        out["guardrails"].append(row)
    if value is None or name not in base:
        return out
    imp = better(goal, value, base[name])
    out["improvement"] = round(imp, 6)
    if regressed:
        out["verdict"] = "regresses-guardrail"
    elif imp > noise:
        out["verdict"] = "improves"
    elif imp < -noise:
        out["verdict"] = "worse"
    else:
        out["verdict"] = "neutral"
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    ap.add_argument("--id", help="hypothesis id (e.g. h3)")
    ap.add_argument("--baseline", action="store_true", help="measure the unmodified project")
    ap.add_argument("--tier", help="tier name from lab.json (default: first tier)")
    ap.add_argument("--config", help="hypothesis config/override file → {config} and {args}")
    ap.add_argument("--workdir", help="where to run (default: lab.json project_dir; a worktree in code mode)")
    ap.add_argument("--repeats", type=int, default=1, help="baseline only: runs to estimate noise")
    ap.add_argument("--render", action="store_true", help="print the rendered command and exit")
    ap.add_argument("--log", help="parse metrics from this existing output file instead of running")
    ap.add_argument("--set", nargs="+", metavar="NAME=VALUE", help="record metric values reported by hand")
    a = ap.parse_args()

    run_dir = os.path.abspath(a.run_dir)
    lab = _load(os.path.join(run_dir, "lab.json"))
    if not lab:
        sys.exit(f"no lab.json in {run_dir} — run the lab setup first (references/lab-config.md)")
    if lab.get("mode") == "reasoning":
        sys.exit("lab.json mode is 'reasoning' — there is no experiment harness to run")
    tiers = lab.get("tiers") or {}
    if not tiers or "metrics" not in lab or "primary" not in lab["metrics"]:
        sys.exit("lab.json needs 'tiers' and 'metrics.primary' (see references/lab-config.md)")
    tier = a.tier or next(iter(tiers))
    if tier not in tiers:
        sys.exit(f"unknown tier {tier!r}; lab.json has {list(tiers)}")
    if not a.baseline and not a.id:
        sys.exit("pass --id <hypothesis> or --baseline")
    hid = "baseline" if a.baseline else a.id
    t = tiers[tier]

    project_dir = os.path.abspath(lab.get("project_dir") or ".")
    workdir = os.path.abspath(a.workdir or project_dir)
    exp_dir = os.path.join(run_dir, "experiments")
    out_dir = os.path.join(exp_dir, f"{hid}.{tier}")
    os.makedirs(out_dir, exist_ok=True)

    cfg_path = os.path.abspath(a.config) if a.config else ""
    args_str = ""
    if cfg_path.endswith(".json") and os.path.exists(cfg_path):
        args_str = config_to_args(_load(cfg_path, {}))
    ctx = {"config": _quote(cfg_path) if cfg_path else "", "args": args_str, "id": hid, "tier": tier,
           "out_dir": _quote(out_dir), "project_dir": _quote(project_dir), "workdir": _quote(workdir),
           "run_dir": _quote(run_dir)}
    # Unquoted copies for paths inside metric specs (joined with workdir, never passed to a shell).
    path_ctx = dict(ctx, config=cfg_path, out_dir=out_dir, project_dir=project_dir,
                    workdir=workdir, run_dir=run_dir)
    cmd = render(t["command"], ctx)

    if a.render:
        print(cmd)
        return

    result_path = os.path.join(exp_dir, f"{hid}.{tier}.json")
    log_path = os.path.join(exp_dir, f"{hid}.{tier}.log")
    rec = {"id": hid, "tier": tier, "command": cmd, "workdir": workdir, "config": cfg_path or None,
           "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "log": os.path.relpath(log_path, run_dir)}

    metrics, missing = {}, []
    if a.set:
        for kv in a.set:
            k, _, v = kv.partition("=")
            metrics[k] = float(v)
        rec.update(status="done", source="manual", exit_code=None, wall_s=None)
        rec.pop("log")
    else:
        if lab.get("change_mode") == "code" and workdir != project_dir and not a.log:
            info = prepare_worktree(lab, run_dir, workdir, out_dir, path_ctx)
            rec.update(info)
            if info.get("status"):
                rec.update(metrics={}, verdict=("touched-frozen" if info["status"] == "invalid" else "failed"))
                _save(result_path, rec)
                print(f"[{hid}.{tier}] {info['status']}: {info['error']}")
                sys.exit(1)
        runs = []
        repeats = max(1, a.repeats if a.baseline else 1)
        for i in range(repeats):
            if a.log:
                rec.update(status="done", source="external-log", exit_code=None, wall_s=None,
                           log=os.path.abspath(a.log))
                lp = a.log
            else:
                env = dict(os.environ, COSCI_ID=hid, COSCI_TIER=tier, COSCI_CONFIG=cfg_path,
                           COSCI_OUT_DIR=out_dir, COSCI_RUN_DIR=run_dir)
                lp = log_path if repeats == 1 else log_path.replace(".log", f".r{i + 1}.log")
                status, code, wall = run_command(cmd, workdir, env, lp, t.get("timeout_s"))
                rec.update(status=status, exit_code=code, wall_s=wall, source="run")
                if repeats > 1:
                    rec["log"] = os.path.relpath(lp, run_dir)
            with open(lp, encoding="utf-8", errors="replace") as f:
                text = f.read()
            got, miss = {}, []
            for spec in all_metric_specs(lab):
                try:
                    got[spec["name"]] = read_metric(spec, text, path_ctx, workdir)
                except (ValueError, KeyError, OSError, TypeError) as e:
                    miss.append(f"{spec['name']}: {e}")
            runs.append(got)
            missing = miss
            if rec["status"] != "done" or a.log:
                break
        names = {k for r in runs for k in r}
        metrics = {k: round(sum(r[k] for r in runs if k in r) / sum(1 for r in runs if k in r), 6)
                   for k in names}
        if len(runs) > 1:
            prim = lab["metrics"]["primary"]["name"]
            vals = [r[prim] for r in runs if prim in r]
            rec["repeats"] = runs
            if len(vals) > 1:
                rec["noise"] = round(max(vals) - min(vals), 6)

    rec["metrics"] = metrics
    if missing:
        rec["missing_metrics"] = missing
    prim_name = lab["metrics"]["primary"]["name"]
    if rec["status"] == "done" and prim_name not in metrics:
        rec["status"] = "failed"  # ran, but the primary metric could not be read

    if not a.baseline:
        baseline = _load(os.path.join(exp_dir, f"baseline.{tier}.json"))
        rec["baseline"] = (baseline or {}).get("metrics")
        rec.update(judge(lab, metrics, baseline))
        if rec["status"] != "done":
            rec["verdict"] = rec["status"]  # failed | timeout
    _save(result_path, rec)

    shown = ", ".join(f"{k}={v:g}" for k, v in metrics.items()) or "no metrics"
    line = f"[{hid}.{tier}] {rec['status']}: {shown}"
    if not a.baseline:
        line += f" | verdict={rec['verdict']}"
        if rec.get("improvement") is not None:
            line += f" improvement={rec['improvement']:+g} (noise {rec['noise']:g})"
        if rec.get("target_met") is not None:
            line += f" target_met={rec['target_met']}"
    elif "noise" in rec:
        line += f" | noise≈{rec['noise']:g} over {len(rec['repeats'])} runs"
    print(line)
    if missing:
        print("  missing:", "; ".join(missing))
    print("  result:", os.path.relpath(result_path, os.getcwd()) if result_path.startswith(os.getcwd()) else result_path)
    sys.exit(0 if rec["status"] == "done" else 1)


if __name__ == "__main__":
    main()
