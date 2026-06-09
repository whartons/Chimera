# Assistant-Workflow self-correction backend

The **highest-quality** self-correction backend: the orchestrating AI assistant
(Claude Code) drives a `generate → multi-judge vision consensus → refine → repeat`
loop using its **Workflow/subagent tooling and its own vision**, scoring each
candidate against a brand/brief **rubric** until one passes (or a cap is hit).

This is **not** a headless CLI — it needs the assistant runtime in the loop. For an
unattended/offline equivalent, see the **local standalone** backend
([`../../modules/agent/self-correction.md`](../../modules/agent/self-correction.md)).
Both backends share the same model-free core in `scripts/agent/`.

## Why multi-judge consensus

A single look at a render misses failure modes that several **independent** judges
catch. Running M judges that each score the image fresh — then taking the **majority
PASS** — rejects candidates that one lenient pass would have waved through, and the
**union of their unmet criteria** becomes a precise refinement signal for the next
render.

This was proven live: a hard "**is this anatomically a real chimera?**" brief
(lion body + goat protruding from the back + serpent tail — no extra heads, no wings)
was put to a **3-judge anatomy vote**. The independent judges rejected the
wrong-anatomy candidates (two-headed, winged, missing the goat) that a single pass
rated "good enough," and the consensus issues drove the prompt fix that landed a
correct one. That generalizes to any brief where correctness is subtle.

## The recipe

The loop reuses the shared core so it stays brand-neutral and consistent with the
headless backend:

- **Rubric** — `scripts/agent/rubric.py` `build_rubric(manifest, subject)` composes
  the scorable checklist from the brand (subject, style, palette, negative); with a
  brandless `default_manifest()` it collapses to just subject + quality, so the same
  consensus loop works for general briefs too (the live anatomy example below was one).
  `rubric.as_prompt()` renders the numbered MET / NOT-MET + PASS/FAIL + `score: 0-1`
  instructions each judge is handed.
- **Expander** — `scripts/agent/expander.py` `TemplatedExpander.expand(subject,
  manifest, prior_issues)` builds the on-brand `(positive, negative)` and, when given
  the consensus issues, appends `". Emphasize and correct: <issues>"` so the next
  batch corrects them.
- **Generate** — `scripts/generate.py image` produces candidates; vary `--seed` for a
  batch and pass `--comfy-output-dir` so finished files route into the brand folder.

### Step by step

1. **Build the rubric** from the brand manifest + the subject/brief:
   `r = build_rubric(load_manifest(<brand>), "<subject>")`. Keep `r.as_prompt()` — it
   is the exact text every judge scores against.
2. **Generate a batch** of N candidates with varied seeds:
   ```
   python scripts/generate.py image --brand <brand> --subject "<subject>" \
       --seed <s> --comfy-output-dir <comfy_out>     # repeat for N seeds
   ```
3. **Judge each candidate with M independent vision passes.** For every candidate,
   the assistant looks at the image M separate times (independent subagents/Workflow
   calls), each handed `r.as_prompt()`, each emitting its own MET/NOT-MET +
   PASS/FAIL + score. Parse each with `scripts/agent/judge.py` `parse_verdict()`.
4. **Take the consensus.** A candidate **passes** when a majority of its M judges
   voted PASS. Among passing candidates, keep the highest mean score. If none pass,
   carry forward the **consensus issues** — the unmet criteria most judges flagged.
   `scripts/agent/judge.py` `consensus_verdict(texts)` does this in one call (parse each
   pass → strict-majority PASS → mean score → de-duplicated union of issues); `CallableJudge`
   wraps a single vision pass as a `Judge`, so a panel of them drops straight into
   `ConsensusJudge` / `run_loop`.
5. **Refine** the prompt from those consensus issues via
   `TemplatedExpander().expand(subject, manifest, prior_issues=consensus_issues)`.
6. **Regenerate the failures** with the refined prompt + fresh seeds and repeat from
   step 3 until a candidate reaches consensus PASS or you hit the **iteration cap**
   (4 is a sane default). On exhaustion, return the best-scoring candidate seen.

### Illustrative Workflow sketch

Brand-neutral pseudocode for the assistant-driven loop (`<brand>` / `<subject>` are
placeholders; use the bundled `example-brand` to try it):

```
manifest = load_manifest("<brand>")
rubric   = build_rubric(manifest, "<subject>")
expander = TemplatedExpander()

prior_issues = None
best = None
for it in range(MAX_ITERS):              # cap, e.g. 4
    pos, neg = expander.expand("<subject>", manifest, prior_issues)
    batch = [generate_image("<brand>", "<subject>", seed) for seed in seeds(it, N)]

    for img in batch:
        verdicts = [assistant_vision_judge(img, rubric.as_prompt())  # parse_verdict()
                    for _ in range(M)]                                # M independent passes
        passes   = sum(v.passed for v in verdicts)
        score    = mean(v.score for v in verdicts)
        if best is None or score > best.score:
            best = Candidate(img, score)
        if passes > M / 2:               # majority PASS -> consensus accept
            return img

    # no consensus winner this round: refine from what most judges flagged
    prior_issues = consensus_issues(batch_verdicts)   # union of common NOT-MET

return best.img                          # cap reached: best-scoring candidate
```

`assistant_vision_judge` is the assistant looking at the image and producing a
free-text verdict that `parse_verdict()` normalizes — there is **no API key and no
local VLM** in this backend; the "judge" is the Claude Code runtime itself. Swapping
that single call for a `LocalVLMJudge` over a Qwen2.5-VL graph is exactly the local
standalone backend — and that backend is **built and live-validated**
(`python scripts/agent/auto_generate.py --backend local …`), with the same rubric,
expander, and loop shape.

`auto_generate.py` also exposes `--backend assistant`, but as an **explicitly gated** opt-in:
a headless subprocess has no assistant vision to call, so the CLI refuses it and points back
here — the assistant consensus backend runs only with the agent in the loop. A real
fail→pass driven exactly this way (an off-brand toy corrected into an on-brand tactical rover,
3/3 consensus) is captured in
[`../../modules/agent/self-correction.md`](../../modules/agent/self-correction.md).

## When to use this

- The brief has **subtle correctness** (anatomy, layout, count, "no X") where one
  pass is unreliable — multi-judge consensus is the strongest filter available.
- You want the **best result** and are willing to keep the assistant in the loop.

For unattended batches, scheduled jobs, or fully offline runs with no assistant, use
the **local standalone** backend instead.
