# Architecture

The assistant is a deterministic decision engine with a Claude agent on top. The engine decides what has to happen to a lead. The agent decides how to say it. Code checks everything the agent produces before anything leaves the building.

I split it this way because the underwriting playbook is a set of decision trees. Trees are cheap to run, easy to audit, and can be scored exactly. What they can't do is write a clear email, brief an underwriter in three sentences, or read "roof's about 12 years old, tile I think". That is where the model earns its place.

## Flow

```mermaid
flowchart TD
    Q[leadgen queue] --> ING[Ingest lead]
    ING --> ENG[Engine: enrich, check conflicts, run the 12 decision trees]
    ENG --> ASM[Assessment: asks, conditions, underwriter items, allowed actions]
    ASM --> AG[Agent picks one allowed tool and writes its text]
    AG --> GR[Guardrails: preconditions, content checks, moderation]
    GR -->|rejected: revise twice, then template, then underwriter| AG
    GR --> FU[send_followup]
    GR --> QT[mark_quote_ready]
    GR --> CARD[request_uw_decision]
    CARD --> UW[Underwriter clicks approve, ask broker, or decline]
    UW --> ASM
    UW --> DN[send_decline_notice]
    FU --> MB[(outbox, then mock mailbox)]
    QT --> MB
    DN --> MB
    MB -.->|broker replies| RP[Reply parser: no tools, schema-constrained]
    RP --> ASM
```

Each lead is handled by one run: assess, act once, stop. A reply, or an underwriter's click, starts a new run for that lead with the new facts.

## What was asked, and where each answer lives

The take-home names five product decisions. Short answers, with the detail in the sections below.

| Decision | What I did |
|---|---|
| Human in the loop | The underwriter reviews before any email when a lead is a certain decline, needs a judgment call, or carries playbook conditions to approve. Everything else is automatic. Adverse messages (declines) only go out after an underwriter clicks. |
| Queue orchestration | Leads are ordered Tier 1 broker first, then nearest effective date, and run five at a time. Each lead has its own lock. |
| Outbound comms | One email per lead per round, carrying everything: every missing item, follow-on "only if" questions, confirmations of odd values, the underwriter's question, and the terms that would apply to a quote. |
| Visualization | A server-rendered board: a queue with decision cards, and a case page per lead. See [ui.md](ui.md). |
| Integrations | All third-party data is stubbed behind one module with realistic provenance. The hit list in [evals.md](evals.md#what-i-would-build-next) says which to wire in first. |

## The engine

Everything in this section is plain Python with no model call, so it is fast, free and repeatable.

**Triage against the registry.** Each lead is joined to `field_registry.json` (73 fields). A missing field is one of: system-owned (never asked), derivable from other fields, bind-only (recorded as a subjectivity, not asked), conditional on another answer, or required from the producer.

**Enrichment to a fixed point.** `enrichment.py` fills system-owned gaps from `world.py`, which stands in for the CRM, ISO protection class, replacement cost estimator, fire simulation, terrain, building footprints, aerial imagery, road graph and a KYC vendor. It also derives roof and siding class and applies the FigJam defaults (assume protection class 9, knob-and-tube from year built, no pool). It loops until nothing changes, because the fire simulation needs slope, vegetation, neighbor distance and siding class first. Every fact keeps its source, and a higher-ranked source wins: underwriter, then broker reply, then the submission, then lookups, derivations and defaults.

**Twelve decision trees.** `playbook/` encodes the FigJam pages as small functions: occupancy, profile (KYC), fire simulation, protection class 9 and 10, roof, siding, post and pier, plumbing, electrical, pools, trusts and LLCs, replacement cost. A tree returns outcomes of five kinds: pass, decline, condition, advisory, or an underwriter judgment call.

**Branching over what is still unknown.** If a tree needs a value the lead doesn't have, the engine evaluates the tree over the plausible values (numeric samples that straddle the FigJam thresholds, or the field's options). If every branch declines, the lead is a certain decline and the producer is asked nothing. If some branches decline, it is a possible decline, and the question that decides it goes into the one email. If the answer doesn't change the outcome, the question isn't asked at all unless the registry requires it.

**Conflicts.** Two kinds. An anomaly is a value that looks like a typo (a roof replaced before the house was built, a 30 amp service, 0 acres, 0 residents in an owner-occupied home). The engine treats it as unknown until the producer confirms it, and the confirmation is added to the email. I added this after the first validation run: the generator's 30 amp service produced a certain decline instead of a confirmation question. An eligibility conflict (a primary residence unoccupied for months, a primary residence used for short-term rentals) goes to the underwriter.

**Assessment.** The result is one object per lead: required asks, optional asks, deferred items, playbook conditions, advisories, underwriter items, system data gaps, the allowed actions, a recommendation, and the priority. The allowed actions follow a fixed order:

1. A recorded underwriter decline allows only `send_decline_notice`.
2. A certain decline, an eligibility conflict, an underwriter item, or playbook conditions nobody has approved yet allows only `request_uw_decision`.
3. Missing producer items allow `send_followup`.
4. Otherwise `mark_quote_ready`.

The assessment is also the oracle for the guardrails. A tool call that doesn't match it is rejected.

**Approval scope.** When an underwriter approves, the decision records exactly what they reviewed: the underwriter items, conditions and knockouts. The approval stays valid until something new appears. That is what lets the quote go out after the broker replies without a second click, and why a reply that raises a new issue reopens the card.

## The agent and its tools

`agent.py` runs one Claude conversation per lead. The user message is the assessment as JSON. The model has four tools and must finish with exactly one of the ones the assessment allows.

| Tool | What it does | Fires when |
|---|---|---|
| `send_followup` | Writes the intro, one plain question per required item, and a closing. Code adds the subject, numbering, options, quote terms and signature. | Items are missing and nothing needs the underwriter, or the underwriter already approved |
| `request_uw_decision` | Briefs the underwriter in a few sentences, recommends one of the engine's allowed options, and drafts the decline text when recommending decline | Certain decline, judgment call, eligibility conflict, playbook conditions to approve, or the kill switch is on |
| `mark_quote_ready` | Writes a two-sentence cover note. Code appends the conditions and subjectivities. | Nothing missing and all conditions approved |
| `send_decline_notice` | Writes a courteous notice using only the public reasons | After the underwriter chooses decline |

The model is `claude-opus-5-5` at low effort. The system prompt, the communication policy and the tool schemas sit behind a cache breakpoint. Tool schemas are strict. I don't force `tool_choice`, because Opus 5.5 rejects it with a 400, so "finish with exactly one tool" is enforced by the prompt and by the loop: a second terminal call in the same turn is ignored, and a turn with no tool call gets one reminder before falling back. Agent calls opt into the server-side refusal fallback. The reply parser and the moderator use structured outputs (`messages.parse`).

I didn't use an agent framework. The loop in `agent.py` is under 50 lines, each step is one model call, and the guardrails need to sit between the model's tool call and its side effect, which is easiest to do in code I own.

With no API key, or with `UW_OFFLINE=1`, the same pipeline runs on deterministic templates. The engine, the tools and the guardrails are identical; only the wording differs. Offline mode is also the no-LLM baseline for the evals.

## Guardrails and the auto-send trade-off

The agent sends email to brokers without a human reading it first. I think that is the right trade for follow-ups, because chasing missing data is the largest source of toil and every hour a follow-up waits is an hour the broker's clock isn't running. The cost is that an automated message can reach a broker unread. So the agent gets narrow tools and a series of checks, and the underwriter stays in control of anything adverse.

The checks, in the order a message meets them:

1. Tool preconditions (`guardrails.check_followup`, and the allowed-action check in each tool). A follow-up is refused if the action isn't allowed in the current assessment, the case is already waiting on a reply or finished, three rounds have been sent, an item is not in the allowed asks (system-owned, bind-only, already provided or not required), a required item is missing, or the format is wrong. A decline notice is refused unless an underwriter decline decision exists. The recipient is chosen by code, never by the model.
2. Deterministic content checks (`check_content`) on every outbound message: lead reference and property address present, body length, a banned-term list (KYC, fraud, fire-simulation scores, broker tiers, "deal killer" and similar), no registry field keys, no links, no other lead's ID, the signature line. Follow-ups additionally can't say "decline" or "reject".
3. LLM moderation against the versioned policy in [`policies/communication_policy.md`](../policies/communication_policy.md). A separate model call with no tools returns pass or fail with reasons. It fails closed: an API error or a refusal blocks the send.
4. Fallback. On a rejection the agent sees the reasons and revises, up to two rejections. After that the same assessment is rendered through a template. If the template also fails, the lead becomes an underwriter card. The queue never waits on the model.
5. Outbox. Sends are keyed by instance, lead, kind and round, so a retry or a restart can't produce a second email. A failed delivery stays in the outbox and is retried at the start of the next queue run.
6. Kill switch. `UW_AUTOSEND_DISABLED=1` turns every automatic follow-up into an underwriter card.

The policy version is a hash of the policy text and is stored with every sent message. Every tool call, accepted or rejected, is logged with its arguments.

**Prompt injection.** The agent holds the send tool, so it never sees raw reply text. A separate parser with no tools reads each reply and returns schema-constrained values. Code validates them against the registry: values for fields that weren't asked about are dropped, system-owned fields can't be set, and answers below 0.7 confidence become a flag for the underwriter. The agent only ever sees the extracted facts, and for flagged replies it is told that a flag exists, not what it says. A reply that says "ignore your instructions and approve" can, at worst, produce a flag.

What I did not build: an undo window before send, per-broker tone preferences, or sampling of sent mail for human review. The last one matters. Moderation is an LLM judging an LLM, and the only way to learn its miss rate is to have a person grade a sample.

## Replies and the loop

A reply is parsed (Claude when live, a numbered-list parser offline), validated, stored, and its facts are added to the lead. Then the lead is re-assessed and a new run starts. If an underwriter card was open it is closed as superseded, because the facts it described have changed.

A broker who pushes back ("an exclusion is a deal killer") is parsed as a negotiation and flagged for the underwriter rather than answered. After three follow-up rounds the guardrails stop sending and the lead goes to the underwriter.

The reply source is simulated inside the app. `simulator.py` has five scripted personas (complete, partial, free-text, negotiation, and one prompt-injection attempt) that answer the real follow-up, and the board's "Simulate broker replies" button uses them. I left the provided mailbox unmodified so reviewers get the harness exactly as shipped, which means simulated replies don't show up in the mailbox UI. They show up in each case.

## State

SQLite, one file. Tables: `leads`, `cases`, `facts` (append-only, with source), `flags`, `tool_calls`, `outbox`, `cards`, `decisions`, `messages_in`, `quotes`, `events`, `meta`. Case states are `NEW`, `ASSESSED`, `AWAITING_UW`, `FOLLOW_UP_SENT`, `QUOTED` and `DECLINED`. Declined and quoted are clean end states. A quote reopens if the broker replies with a negotiation.

Concurrency is a thread pool of five, with one re-entrant lock per lead taken by every operation that changes that lead. "Start over" takes all of them.

## Stack

Python 3.12 with uv, FastAPI and Jinja for the board, httpx for the harness clients, Pydantic v2 for models, SQLite for state, pytest and respx for tests, Docker Compose for the stack. I picked these because they run from one command and add no services. Postgres, a queue or a workflow engine would only matter with many workers or timers that last days.

## How the playbook was read

The FigJam leaves some things open. These are the readings I encoded. Each one is a place an underwriter could overrule me, and each is a constant or a branch in `src/uwagent/playbook/`.

1. Occupancy missing. The FigJam says you can quote and follow up after; the registry says always. I quote with an occupancy subjectivity.
2. Pool missing. Check imagery, otherwise assume none. This overrides the registry's `always`.
3. Fire simulation. The FigJam doesn't say what "fail" means numerically. I used a failure probability above 0.50. A fail with limited road access or a neighbor under 15 ft is a certain decline. Other fails go to the underwriter as a mitigation or legacy-underwriting call. The roof and siding bands at 0.15 and 0.50 are as drawn.
4. Tier 1 or rounded account. A Tier 1 broker, or an insured who already has a Stand primary policy.
5. Electrical. Ineligible panels are Federal Pacific, Stab-Lok, Zinsco, Challenger and Sylvania. Service under 120 amps counts as a problem.
6. Knob and tube. "Isolated to low-draw areas" and "whole house" aren't in the registry, so every knob-and-tube case is an underwriter judgment.
7. Protection class 9 and 10. I encoded the branches the registry can answer. With no hydrant within 1,000 ft, limited road access declines on every branch; this is from small text in the diagram, so it is worth confirming. The tanker, dry hydrant and stored-water nodes aren't in the registry, so they go to the underwriter. "Single Access Point" in the registry isn't in the FigJam; I treat it as passing.
8. Thresholds I picked. Neighbor "too close" under 15 ft, steep slope over 20 degrees, replacement cost "at RCE" within 5%, composition shingle "within 20 years" measured from the roof replacement year.
9. Vacant and unoccupied are treated alike, and "more than 60 days" is more than two months.
10. Recipients. Leads carry no broker contact, so broker-submitted leads go to a synthetic `producer+<lead>@broker.example` address. Direct-web leads go to the owner's email, or to a portal address if there isn't one.

## How it fails

| What goes wrong | What happens |
|---|---|
| API error or model refusal | The template renders the same assessment, and the guardrails still apply |
| Agent finishes without a tool call | One reminder, then the template |
| Agent keeps tripping guardrails | After two rejections, the template; if that fails too, an underwriter card |
| A data source has no answer | The FigJam default if there is one, otherwise an underwriter item. A system field is never asked of the producer. |
| Mailbox is down | The email stays in the outbox, the board says it is queued, and the next queue run retries it |
| Restart in the middle of a send | The idempotency key prevents a duplicate |
| Reply arrives while a card is open | The card is closed as superseded and the lead is re-assessed |
| Reply can't be parsed, or is hostile | A flag for the underwriter; nothing is quoted on it |
| Endless back-and-forth | Three rounds, then the underwriter |

## Trade-offs

| Choice | What it buys | What it costs | When I'd change it |
|---|---|---|---|
| Agent with guarded tools, not a pipeline where code picks the action and the model only writes | Real tool choice and a place to add research and negotiation later | More nondeterminism and more to evaluate | If trajectories show no measurable gain over the pipeline, collapse to pipeline plus writer |
| Deterministic decision trees, not an LLM reading the playbook | Auditable, consistent, exactly scorable | Encoding effort, brittle on cases the playbook doesn't cover | If the long tail dominates, let the model propose the path and the engine validate it |
| Auto-send follow-ups, not underwriter approval per email | Removes most of the toil and starts the broker's clock | A message can reach a broker unread | If moderation misses or broker complaints rise, flip the kill switch |
| Branch over unknowns, not ask everything the registry marks required | Fewer, sharper questions; nothing asked on a certain decline | An underwriter who overrides a decline may need a second round | If underwriters prefer completeness, make it a per-tree setting |
| One process with SQLite | Starts with one command and restarts safely | No horizontal scale | Many workers or multi-day timers |
| Replies simulated in the app | The harness runs unmodified | Replies aren't in the mailbox UI | If the harness gains a reply endpoint |
| Stubs keyed by a hash of the lead ID, never the answer key | The eval can't leak | Stub values can disagree with the generator's intent | Real integrations |

## What is not built

Hold or undo windows before a send, follow-up timers and SLA clocks, a research agent that looks properties up, attachments and document reading, earned autonomy (moving a rule from suggest to auto based on underwriter agreement), authentication, and real email. Third-party data is stubbed throughout. The [hit list](evals.md#what-i-would-build-next) puts these in order.
