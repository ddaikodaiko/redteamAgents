# Related work and positioning (draft)

This note situates the paper in the LLM-driven offensive-security literature
(2023–2026), states honestly what is already established, and isolates the
contributions that remain novel. Citations are by arXiv id / venue; verify each
before the camera-ready.

## 1. What is already established (and we do NOT claim)

**Capability — can LLMs exploit?** Fang et al. 2024 ("LLM Agents can Autonomously
Hack Websites"; "…Exploit One-Day Vulnerabilities") showed GPT-4 exploiting 87 %
of one-day CVEs *given the CVE description*, collapsing to 7 % *without* it, while
GPT-3.5 and open-source models scored 0 %. The dependence on being handed the
objective is theirs; our `blind`→`informed` jump is the controlled, per-cell
version of the same phenomenon.

**The context problem + scaffolding as the fix.** PentestGPT (Deng et al., USENIX
Security 2024, 2308.06782) found LLMs proficient at sub-tasks but unable to
"maintain an integrated understanding of the overall testing scenario," and built
three self-interacting modules to fix it. Many follow-ups (HackSynth 2412.01778;
AutoPenBench 2410.03225; APT-Agent 2605.24949, 84 % on Metasploitable 2) add
planners, summarizers, memory, RAG, or classical planning — all reporting that
*more/structured* scaffolding *helps* (and that *removing* it hurts).

**Failure modes are known.** The 400-run consistency study (2605.30096) ran
`qwen2.5-coder:14b` and three frontier models against OWASP Juice Shop and two
services, and already catalogues the model-distinctive failure modes we also see:
qwen "premature completion" (52/100 — our *capitulation*) and iteration-budget
*exhaustion*. PentestGPT v2 / "What Makes a Good LLM Agent for Real-world
Penetration Testing?" (2602.17622) names the core limitation as "Type B" failures
— agents "misallocate effort, over-commit to low-value branches, and **exhaust
context before completing attack chains**," with "state management limitations" —
and claims this root cause is "**largely invariant to the underlying LLM**."

**Local small models are an active topic.** 2611.06257 and vendor benchmarks
evaluate open-weight models (4B–32B) on offensive/vuln-reproduction tasks; mid-
size Qwen is the common sweet spot.

Consequently we do **not** claim as novel: "a local LLM can/can't pentest," "the
context window is the bottleneck," "capitulation and exhaustion are failure
modes," or "statefulness limits attack chains." These are established.

## 2. The gap we fill

Across this literature, three things are missing — and they define our
contribution:

1. **Scaffolding is treated as monotonically beneficial.** Every system above adds
   structure and reports gains; ablations only ever *remove* a component and show
   a drop. **No work demonstrates that a *standard* scaffold can be net-negative.**
   We give a controlled ablation in which imposing a human-style recon→confirm→
   exploit methodology (`guided`) *reduces* success relative to no methodology
   (`informed`) on a budget-limited exploitation task — A03 SQLi 23 %→0 %, Fisher
   p≈0.01, 26/30 runs lost to `context_exhaustion`. This is the
   **reconnaissance-vs-context-budget tradeoff**: under a fixed window, recon is a
   cost that can starve exploitation. It inverts the field's implicit assumption.

2. **Information, autonomy, and methodology are conflated.** Prior work varies the
   *system* (2602.17622: 28 systems) or the *model* (2605.30096: 4 models, prompt
   fixed). **No work runs a clean factorial on one model that separates these
   factors.** Our `oneshot`/`blind`/`informed`/`guided` design isolates them and
   shows **information dominates autonomy** (`blind` 0 % → `informed` up to 40 %
   with no other change), while autonomy itself is *double-edged* (it beats one-
   shot on the hard task, loses to it on the trivial one).

3. **The "LLM-invariant" claim is untested against scale.** 2602.17622 asserts the
   core failure is invariant to the model. We **test that directly** with a model
   sweep (Qwen2.5-Coder 7B→14B→32B, + Qwen2.5-72B-Instruct-abliterated): do the
   recon-vs-budget tradeoff and the stateful ceiling persist or break with size?
   A resource-constrained regime is exactly where a context-budget cost should be
   most acute and most likely to ease with scale.

## 3. Secondary contributions enabled by our setup

- **A defensive reading of the operational failure modes.** 2605.30096 asks
  whether autonomous attacks produce "predictable signatures amenable to
  detection" and finds frontier models *diverse* (hard to signature). We show the
  opposite for a small local model: its high loop/redundancy (identical command
  and output hash repeated) makes its traffic **trivially signaturable**, and its
  reliable exhaustion on stateful/budget-limited targets suggests
  **exhaustion-inducing defenses** (stateful gates, WAFs, tarpits) as a primitive
  complementary to the deception line (Cloak-Honey-Trap, USENIX'25; AgentSnare
  2607.26998; ZERO-APT 2606.05567). The operational weakness *is* the defense.
- **WAF evasion by a local autonomous agent.** PACEbench (2510.11688) reports all
  agents score 0 on WAF tasks; rule-based WAFs stop autonomous SQLi (0–5.7 % vs
  ModSecurity, 2605.11188). No one studies a *small local* agent against a WAF, nor
  how the WAF shifts the failure modes. Our A03W cell (sqli-labs behind
  ModSecurity/CRS) measures WAF-induced degradation and whether the agent
  *detects/attempts* evasion versus loops to exhaustion.
- **A labelled failure-trace artifact.** The field's benchmarks over-represent
  successful paths; the survey (2607.02605) flags generating counterfactual
  failure traces as an open problem. We release hundreds of step-level,
  token-accounted, failure-mode-labelled runs.
- **Scoring rigor / reproducibility.** Because output is stored hashed, success
  must be calibrated at run time; we pin every detector against live-exploit and
  legitimate-baseline fixtures, and document the subtlety that a *legitimate*
  sqli-labs query already returns a real credential (so "contains a secret" is not
  proof of injection). Three infrastructure defects that would have silently
  corrupted results (ports, UTF-8 decode, missing DVWA DB) are documented.

## 4. One-line positioning

> Not "another characterization of a local offensive agent" (now well covered),
> but **a controlled ablation (information × autonomy × methodology × model scale)
> that demonstrates scaffolding is non-monotonic — mandated reconnaissance is
> net-negative under a fixed context budget — and tests whether the
> recently-claimed "LLM-invariant" failure holds with scale**, with a defensive
> reading (loops as signatures, exhaustion as a defense) and a WAF axis.

## Key references (verify before camera-ready)

- Fang et al. 2024 — LLM agents hack websites / exploit one-day CVEs.
- PentestGPT — Deng et al., USENIX Security 2024 (2308.06782).
- "What Makes a Good LLM Agent for Pentesting?" / PentestGPT v2 (2602.17622).
- 400-Run Consistency study (2605.30096).
- HackSynth (2412.01778); AutoPenBench (2410.03225); APT-Agent (2605.24949).
- Local open-weight agents on vuln-reproduction (2611.06257).
- Survey: LLM-Driven Penetration Testing (2607.02605).
- WAF: PACEbench (2510.11688); adversarial SQLi vs ModSecurity (2605.11188).
- Defense: Cloak-Honey-Trap (USENIX'25); AgentSnare (2607.26998); ZERO-APT (2606.05567).
- Long-horizon agent failure: "Long-Horizon Task Mirage" (2604.11978); "Infinite
  Agentic Loops" (2607.01641).
