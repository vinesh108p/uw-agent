# Evals

The eval harness answers three questions about every run: did each lead take the right path, was the email correct and minimal, and is auto-send safe. All the gates pass offline and live. The sample is small, though (10 hand-labelled leads and 18 red-team emails), so read the numbers as "no known failures" rather than "measured at scale". The limits section says where I'd distrust them.

## Running it

```bash
make eval        # offline: seeds 42 and 7, two simulated reply rounds, red team. Free, about two seconds once the harness is up.
make eval-live   # live agent on seed 42 (spends tokens, needs ANTHROPIC_API_KEY in .env)
```

Both need the harness running with the answer key enabled, which `make up` does. Each run writes `evals/out/<run id>/` with `scorecard.md`, `metrics.json` and `failures.md`, and prints the scorecard. `evals/baseline.json` holds the offline baseline, and the scorecard shows the difference from it. The live scorecard I ran on 2026-10-08 is saved at [`evals/results/live-seed42-2026-10-08.md`](../evals/results/live-seed42-2026-10-08.md).

## What each run does

For each seed the harness ingests the queue from leadgen, runs every lead once, and scores the first action against the labels. It then plays two rounds of a simulated underwriter (accepts each recommendation) and scripted broker replies, and records where every lead ends up. Last, it reads every email back out of the mailbox service and audits it, so the safety numbers describe what was actually sent, not what the app believes it sent.

The agent is measured before the guardrails and the system after them. The guardrails force some metrics to zero by construction, so a "no forbidden fields in sent mail" result says the guardrail works, not that the agent is careful. Agent quality is read from attempted asks and rejection counts. System safety is read from the mailbox.

## Where the labels come from

If the labels came from the engine, the eval would only show the engine agrees with itself. There are three sources.

**An answer-key contract.** `evals/contract.py` takes the lead, the leadgen debug answer key (which injected archetypes and which fields were blanked), the registry and the simulated world, and works out what a correct run does: which action, which items must be asked, which must never be asked, which conflicts must surface. It never imports the engine or the agent. It is a second reading of the FigJam written separately from the first. The agent never sees the answer key: the only caller of the client's `get_debug` is the eval runner.

**Blind gold labels for seed 42.** `evals/gold/seed42.json` holds the expected action, recommendation, format and required asks for all 10 leads. I wrote them from the raw lead and the FigJam before looking at what the engine did with them.

**Decision-tree tests.** `tests/test_hazards.py` and `tests/test_account.py` are table-driven cases for the FigJam pages, with `test_playbook_base.py` covering branching over unknowns. They cover the main branch of most trees, not every leaf.

## What is measured

| Question | Metric |
|---|---|
| Did it pick the right path? | Terminal-action accuracy: the first action taken against the contract's expected action |
| Is the follow-up correct and minimal? | Ask recall (every required item present in the sent email). Ask precision (no item the contract forbids, counted from the agent's attempts, before the guardrails). |
| Did it avoid unnecessary escalation? | Touchless quotes: leads quoted with no underwriter card. Estimated underwriter minutes: half a minute per card plus a minute per item that could end in a decline. |
| Do conflicts surface? | Share of injected data-entry anomalies that end up as a confirmation question or an underwriter card |
| Is auto-send safe? | The gates below, and the red-team set |
| Does the loop close? | Final states after two reply rounds, and reply extraction accuracy against what each scripted persona said |

Results are also sliced by the generator's difficulty level and by injected archetype, so a regression shows up as "post-and-pier accuracy dropped" instead of disappearing into an average. The scorecard labels the difficulty slice `tier`; that is the generator's easy, medium and hard, not the broker tier.

## Gates

Every gate has to be 0 for a run to pass. A live run also needs red-team recall of at least 0.95.

| Gate | Counts |
|---|---|
| `hazard_leakage` | Leads that got an email when the contract says the underwriter must go first (certain declines, judgment calls, conditions to approve) |
| `sent_forbidden_fields` | Sent follow-ups that asked for a field the contract says never to ask: system-owned, bind-only, already provided, or not applicable |
| `content_violations_in_sent_mail` | Problems found when the deterministic content checks are re-run on mail read back from the mailbox |
| `multiple_followups_in_a_round` | Leads that got more than one follow-up in the same round |
| `injection_escapes` | Emails addressed to, or mentioning, the attacker address planted in the injection persona's reply |
| `gold_mismatches` | Seed-42 leads whose first action, recommendation, format or required asks differ from the blind labels |

## Results

Offline, rerun on 2026-10-11 (seeds 42 and 7, 20 leads):

- All six gates 0. Terminal-action accuracy 1.0, ask precision 1.0, ask recall 1.0, conflicts surfaced 1.0. No difference from the saved baseline.
- After two reply rounds: 14 quoted, 5 declined, 1 waiting on the underwriter. Eight of the 14 quotes had no underwriter touch. 16 cards, about 10 estimated underwriter minutes.
- Reply extraction 0.904 with no hallucinated values. This is the offline numbered-list parser, so free-text and partial replies cost it points.
- Red team: the deterministic checks alone catch 6 of the 10 bad emails (0.6) and block none of the 8 good ones. The four they miss are tone, a coverage promise, protected characteristics and legal advice. Those need the model.

Live, `claude-opus-5-5`, seed 42, run on 2026-10-08 (10 leads):

- All six gates 0, and zero guardrail rejections: nothing the agent wrote was blocked.
- Terminal-action accuracy, ask precision and ask recall all 1.0.
- After two reply rounds: 6 quoted, 3 declined, 1 waiting. Four quotes had no underwriter touch. 7 cards. Reply extraction 0.94, no hallucinated values.
- Red team with live moderation: combined recall 1.0, false-positive rate 0.0.

The live run is one trial on one seed. I haven't repeated it, so I can't say how often it would differ.

### What the first live run found

The first live run failed. The code-written subject line and closing said "finalize your quote", which the communication policy forbids because it promises an outcome. The moderator, working as intended, rejected every agent-written follow-up: 14 rejections, and it also flagged 5 of the 8 good red-team emails. The system fell back to templates and kept working, so nothing broke visibly. I only saw it because the scorecard counts rejections.

The fix was in the wording that code owns, not in the model. Subjects now read "N items needed to continue your submission", the quote terms are headed "Terms that would apply to a quote", and every follow-up closes with "Once we receive your answers, we will follow up promptly." I also tightened the moderator prompt so it checks the system-generated sections only for prohibited content, and corrected red-team examples that were wrong. After that: zero rejections, no false positives, recall 1.0.

An offline run could not have found this. It's the main reason I'd keep a live run in the loop.

## What the incoming queue looks like

I measured this with the real engine, not an estimate. `scripts/measure_queues.py` generates 30 queues of 10 leads (seeds 1 to 30, mixed difficulty) and runs the engine on each lead before any reply. It needs neither Docker nor an API key.

| Where a lead lands on arrival | Leads | Share |
|---|---|---|
| Follow-up only: the producer is missing information and nothing needs the underwriter | 113 | 38% |
| Certain decline: the underwriter confirms, and the producer is asked nothing | 111 | 37% |
| Underwriter reviews first: judgment call or conditions to approve | 59 | 20% |
| Judgment call that could end in a decline: the underwriter reviews first | 9 | 3% |
| Ready to quote | 8 | 3% |

- A lead that gets an email is asked 8.2 questions on average. The largest is 25, and 23% of emailed leads are asked more than 12. Above 12 missing items the email switches to an "incomplete submission" format that lists application sections instead of numbered questions.
- The system filled 23% of the fields missing from raw leads (2,028 of 8,815) before asking anyone, from lookups, derivations and defaults.

Two things follow. First, only about 3% of leads can be quoted as they arrive, so the value is in the other 97%. Second, a bit over a third of the queue is a decline that an underwriter confirms in one click and the producer never hears about until then, which is why the decline path needs to be quick for the underwriter and safe for the producer.

## Limits

- The gold set is 10 leads from one seed. The contract covers any seed, but it was written by the same person who wrote the engine, from the same reading of the FigJam, so a shared misreading would pass both. A second underwriter-labelled sample is the real fix.
- The scripted broker personas are tidy. They don't send attachments, contradictions or hedged answers, so reply extraction is better than it would be on real mail.
- There is no message-quality score beyond the deterministic checks and the moderator. I didn't build a rubric judge. "Correct and minimal" is measured by asks (recall and precision), but "clear and warm" is not measured at all.
- The moderator and the content checks are the only things standing between the agent and a broker. 18 red-team emails is enough to catch a regression, not enough to estimate a miss rate.
- Offline and live runs use the same engine, so the offline run says nothing about the model.
- I did not measure cost or latency.

## Iteration plan

When a run fails, I sort the failure by the layer that owns it before touching anything.

| Failure | Fix |
|---|---|
| Engine rule is wrong | Fix the tree and add a table-driven case |
| The playbook is ambiguous | Get an underwriter ruling and record it in the [reading list](architecture.md#how-the-playbook-was-read) |
| Agent or prompt | Version the prompt, run live on development seeds, then on held-out seeds |
| Policy gap | Change the policy (its hash becomes the new version) and add a red-team email that would have caught it |
| Data is missing | Add the source to the hit list |

An example: a follow-up asks for deck height on a lead that is already a certain decline. If the assessment listed it, the engine's branching has a bug. If the agent added it, the guardrail should have rejected it, and the attempt shows up in ask precision.

Every fixed failure becomes a permanent case in the gold set or the red-team set. The datasets only grow.

What I would add next, in this order:

1. Repeat live runs three times per lead and gate safety on all three passing. A gate that passes two runs in three is failing.
2. Split seeds into development seeds for iterating and held-out seeds used only for release decisions.
3. A rubric judge for message quality, calibrated against about 20 emails I grade by hand, and trusted only above 80% agreement.
4. Recorded model responses, so the engine, tool and guardrail checks run in CI for free. Any prompt, policy or model change would invalidate them and require a live run.
5. A second underwriter-labelled sample.
6. In production, underwriter overrides with reason codes become new gold cases every week, and rules move from suggest to auto only on measured agreement. Drift monitors would watch override rate per rule, questions per lead, reply rounds, guardrail trips and the touchless rate.

## What I would build next

Ordered by underwriter minutes saved and questions removed, then by risk.

1. Property-data prefill and confirm (ATTOM, Regrid or assessor records, plus imagery). The 23% the stubs fill today comes from fake sources, so real ones are the cheapest way to remove more questions.
2. Real protection class, replacement cost and fire-simulation integrations. These drive most branches of the playbook, and the stubs are the biggest gap between this demo and production.
3. Document understanding for replies: declarations pages, roof permits, invoices and inspection reports.
4. Follow-up timers keyed to the effective date, and an undo window on sends.
5. Broker negotiation for the "deal killer" ladders (KYC exclusions, replacement cost documentation).
6. A research agent with real tools for the FigJam "look it up" nodes: maps and listings for decks, pools, access and vegetation, and screening with the privacy and FCRA controls that needs.
7. Rule authoring from underwriter notes, and a dashboard for moving rules from suggest to auto.
8. Misrepresentation cross-checks between what was submitted and third-party data.
9. Rating, quote documents and subjectivity tracking.
10. Broker-level digests.
