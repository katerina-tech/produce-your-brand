# Produce Your Brand — Capstone presentation

**Deck copy, ready for design.** Structured on the consulting convention of *action titles*: every slide title states the conclusion, not the topic, so the deck reads as an argument even without the speaker.

**Format:** 10 minutes presenting, 5 minutes Q&A.
**Core deck:** slides 1–10. **Appendix:** A1–A4, for questions only.

**Provenance of every number in this deck:**

| Marker | Meaning |
|---|---|
| **[M]** | Measured in this repository or from the provider's own API response. Reproducible. |
| **[D]** | Derived arithmetically from **[M]** figures. Formula shown. |
| **[E]** | Estimate, order-of-magnitude. **Requires verification before external use.** |

Nothing in this deck is rounded in the project's favour. Where a figure is weak, it is marked **[E]** and says so.

---

# SLIDE 1 — Cover

## Produce Your Brand
### An AI agent that turns a plain-English production request into a supplier-ready quotation — without inventing a single supplier fact

Ekaterina Kuznetsova · AI Engineering Capstone · Turing College
Live: produceyourstuff.up.railway.app · 29 commits · 308 tests

*Design note: full-bleed charcoal `#191C23`, cobalt `#3240EB` accent on "without inventing". Logo top-left. Nothing else on this slide.*

---

# SLIDE 2 — Executive summary

## An agent that reasons about manufacturing feasibility, where the model writes language and code owns every fact

**The problem.** A business that owns 100 yoga mats and wants a gold logo on them must first establish whether the technique is even physically possible, then find partners, then discover one-by-one who accepts customer-owned goods. Days of work before one quote. **[E]**

**Why it is not solved.** Generic search and general-purpose chat assistants answer *"who prints in Berlin"*. Neither answers *"which of 24 partners clears a 12-day deadline at 500 units on PVC"* — and neither gives the same answer twice.

**What was built.** One LangGraph workflow, five human interrupt points, four approval gates. An LLM extracts a typed brief and reasons about production method against a curated knowledge base. **Supplier filtering and scoring run in pure Python with zero LLM imports** — enforced by an automated architecture audit.

**Why it holds up.** 308 automated tests, none calling a live model. A 19-case behavioural eval, all passing, whose results table is machine-generated and refuses to publish while any case fails.

**What it costs to run.** **$0.0011 per complete project** — roughly 929 projects per dollar. Total development spend across the entire build: **$0.199**. **[M][D]**

**The honest gap.** Supplier records are synthetic and labelled as such in every row. The algorithm is real; the partners are not. Closing that is field work, not engineering.

*Design note: six blocks, two columns. This slide alone must carry the argument if the audience reads nothing else.*

---

# SLIDE 3 — The problem is feasibility reasoning, not search

## Four sequential unknowns, each of which can invalidate the order — and the buyer discovers them one at a time

**Worked example, used throughout this deck:** *100 black yoga mats, PVC, customer already owns them, gold logo, Berlin.*

| # | Unknown | Why it blocks | Cost of getting it wrong |
|---|---|---|---|
| 1 | **Is the technique physically possible?** | PVC under a laser releases hydrogen chloride. No reputable shop will do it | Weeks lost pursuing an impossible route |
| 2 | **Who accepts customer-owned goods?** | Many producers only work on stock they supply. Most enquiries never think to ask | Quote arrives, then collapses |
| 3 | **Does the MOQ fit?** | 100 units sits below many minimums | Silent disqualification |
| 4 | **Is the deadline feasible?** | Lead time plus buffer against the date | Committed delivery that cannot be met |

**The compounding failure.** Each unknown is individually knowable. The cost is that they are discovered *serially*, by email, over days — and the same brief must be re-explained to every supplier.

**So what:** the scarce resource is not a directory of printers. It is *structured reasoning over capability constraints*. That is what this system automates.

*Design note: four numbered rows, escalating cobalt intensity. Right column = consequence, in the semantic red `#C94A3B`.*

---

# SLIDE 4 — Neither search nor a general chat assistant closes this gap

## The differentiator is proprietary structured capability data, not language ability

| Capability | Google / Flyeralarm | General chat assistant | **Produce Your Brand** |
|---|---|---|---|
| Find printers in a city | ✅ | ✅ | ✅ |
| Explain a technique | ⚠️ generic | ✅ | ✅ **with citation to a specific document** |
| Refuse an unsafe pairing (PVC + laser) | ❌ | ⚠️ inconsistent | ✅ **grounded in the corpus** |
| Filter by published MOQ | ❌ | ❌ | ✅ |
| Filter by customer-owned-goods policy | ❌ | ❌ | ✅ **including "unconfirmed" as distinct from "no"** |
| Deadline feasibility vs. lead time | ❌ | ❌ | ✅ |
| **Same answer to a reworded question** | ✅ | ❌ | ✅ **byte-identical, tie order included** |
| Auditable reason per factor | ❌ | ❌ | ✅ **six factors, each with a computed reason** |

**Two rows carry the whole argument.**

**Reproducibility.** A language model asked to rank suppliers drifts with phrasing and with name familiarity, and cannot be audited. Here, identical inputs produce byte-identical output — because ranking is arithmetic, not generation.

**"Unconfirmed" ≠ "no".** No competitor makes this distinction, and it changes outcomes: a partner whose policy was never asked about is a *lead with a risk flag*, not a rejection.

**So what:** the moat is not the model. Any competitor can call the same model. The moat is the structured capability data plus deterministic logic over it.

*Design note: comparison matrix. Grey out the first two columns; the last two rows get a cobalt highlight band.*

---

# SLIDE 5 — Market: a fragmented, low-digitisation segment where the hard requests are unserved

## The commodity end is taken; the value sits in non-standard work

| Layer | Definition | Scale |
|---|---|---|
| **TAM** | German promotional-products and custom-print production | **~€3–4bn annual industry revenue [E]** |
| **SAM** | Non-standard requests — unusual material, customer-owned goods, odd quantity, tight deadline, or a combination | **~15–25% of enquiry volume [E]** |
| **SOM (entry)** | Berlin + intermediaries who source repeatedly (promotional-products distributors, merch and event agencies) | **~3,000–5,000 such firms in Germany [E]** |

> ⚠️ **All three figures are [E] — order-of-magnitude, from industry-association reporting and interview inference. They must be sourced and verified before any external or investor use.** They are shown to frame the segment, not to size a business case.

**Three structural facts that are not estimates:**

1. **The commodity end is consolidated.** Flyeralarm, Saxoprint and Vistaprint own standard print at scale. Competing there is competing on price.
2. **Catalogue data already exists** for standard promotional products in DACH (Promidata, PSI). It does **not** cover non-standard work — which is precisely the wedge.
3. **Frequency separates a tool from a novelty.** An end business needs custom production 2–4 times a year. **A sourcing intermediary does it weekly.** Only the second builds a habit.

**So what:** the addressable entry point is the intermediary who sources repeatedly, on requests catalogues cannot answer.

*Design note: TAM/SAM/SOM as nested blocks, NOT concentric circles — the nesting is definitional, not proportional. Put the [E] warning in a visible box, not a footnote. Credibility comes from flagging weak data, not hiding it.*

---

# SLIDE 6 — Why this architecture: the model handles language, code owns every fact

## One design decision, from which every guarantee in the system follows

> **The LLM never touches a number that matters.**

| Concern | Owner | Rationale |
|---|---|---|
| Extract brief from free text | **LLM** | Natural language → typed object. Genuine model work |
| Which fields are missing | **Python** | "Is this field null" is not a judgement call |
| Production method | **LLM + retrieval** | Real technical reasoning, with citations |
| Supplier search | **Python** | Structural filter. Results must not depend on phrasing |
| Match scoring | **Python** | Must be reproducible and defensible |
| Match explanation prose | **LLM** | Prose only, over a score it cannot alter |
| RFQ structure | **Python** | A document shape is a contract, not a generation |
| RFQ intro/closing | **LLM** | Tone only |

**Three guarantees this buys — each mechanically enforced, not promised:**

| Guarantee | Enforcement |
|---|---|
| A supplier capability can never be invented | The model has **no access path** to the dataset — tool-only. Every id resolved through the repository; unknown ids dropped |
| A score cannot be argued up by rewording | `matching.py` has **zero LLM imports**, asserted by `scripts/audit_architecture.py` on every run |
| No step completes without a human | Four gates enforced by LangGraph `interrupt()`. The graph **physically cannot** advance without a resume payload |

**So what:** these are architectural properties, not prompt instructions. A prompt can be talked out of a rule. A missing import cannot.

*Design note: the pull-quote is the hero. Two tables below, the second visually heavier — enforcement is the point.*

---

# SLIDE 7 — Technology: one graph, five interrupts, two memory stores

## Deliberately single-implementation, with an automated audit that fails the build on duplication

```
                    ┌─────────────── Next.js 16 / React 19 ───────────────┐
                    │  Marketing page  │  Product (route group)           │
                    └──────────────────┬──────────────────────────────────┘
                                       │ server components (read)
                                       │ server actions (write)   ← browser never calls the API
                    ┌──────────────────▼──────────────────────────────────┐
                    │              FastAPI · 10 endpoints                 │
                    │      only ONE of them advances the workflow         │
                    └──────────────────┬──────────────────────────────────┘
                                       │
        ┌──────────────────────────────▼──────────────────────────────────┐
        │                 ONE LangGraph StateGraph                        │
        │                                                                 │
        │  extract → validate ─┬─► ask (PAUSE) → merge ─┐                 │
        │                      │                        └─► re-validate   │
        │                      └─► brief review (PAUSE)                   │
        │                            │                                    │
        │                       assess retrieval need ← the agentic choice │
        │                       ├── retrieve ──┐                           │
        │                       └──────────────┴─► method rec (PAUSE)      │
        │                            │                                    │
        │                       search → score → select (PAUSE)            │
        │                            │                                    │
        │                       generate RFQ → approve (PAUSE)             │
        └────┬──────────────┬──────────────┬──────────────┬────────────────┘
             │              │              │              │
        ┌────▼────┐   ┌─────▼─────┐  ┌─────▼─────┐  ┌─────▼──────┐
        │  LLM    │   │   FAISS   │  │ suppliers │  │  SQLite    │
        │ factory │   │ 51 chunks │  │ 24 records│  │  ×2 stores │
        │ (1 site)│   │           │  │           │  │            │
        └─────────┘   └───────────┘  └───────────┘  └────────────┘
```

**Stack:** Python 3.12 · FastAPI · LangGraph · LangChain · OpenAI API via OpenRouter · FAISS · fastembed (optional on-device) · SQLite · TypeScript · Next.js · Tailwind · Leaflet · Docker · Railway

**Four decisions worth defending:**

| Decision | Alternative rejected | Reason |
|---|---|---|
| **FAISS directly** | Chroma / a framework wrapper | Persistence is an index file + JSON, not a pickle. **A pickled index is arbitrary code execution waiting for a file swap** |
| **Two separate memory stores** | One store | LangGraph's checkpointer holds conversation state; our own `projects` table holds the durable record — so a project survives a restart without depending on a checkpoint format we do not own |
| **Browser never calls FastAPI** | Direct client → API | Reads in server components, writes through server actions. No credential reaches the client, and CORS becomes a non-problem rather than a configuration |
| **`output: standalone` Docker** | Full `node_modules` in image | Smaller deployed image, faster cold start |

**The anti-duplication audit** — `scripts/audit_architecture.py`, run on every verification, **fails the build** if a second LangGraph, prompt module, LLM factory, vector store, knowledge directory or supplier data source appears, or if any module under `app/` becomes unreferenced dead code. It also asserts zero LLM imports in the deterministic scorer.

*Design note: the ASCII diagram must be redrawn properly. Highlight the "assess retrieval need" branch in cobalt — it is the agentic decision and slide 8's subject. Mark all five PAUSE points with the same human icon.*

---

# SLIDE 8 — Agentic RAG: the system decides whether to retrieve, and that decision demonstrably changes the answer

## Retrieval fires on feasibility questions and is skipped on lookups — cheapest signal first

**The routing ladder.** A dedicated node decides. It does not retrieve; it only decides.

| Layer | Example | Cost |
|---|---|---|
| 1. Deterministic fast path | *"Which Berlin suppliers do laser engraving?"* → supplier repository | **zero model calls** |
| 2. Deterministic rule on the brief | Material unconfirmed → retrieve; feasibility cannot be assumed | **zero model calls** |
| 3. The model | Only the genuinely ambiguous middle | 1 classifier call |

If the router itself fails, it **errs toward retrieving**: an unnecessary lookup costs $0.0002; a confident wrong technical claim costs a customer.

**Evidence it is not decorative — the same request, retrieval off vs on: [M]**

| | Without retrieval | Grounded |
|---|---|---|
| Confidence | medium | **high** |
| Constraints returned | 1, generic | **4**, incl. *"1–2 mm minimum line thickness for weeded vinyl"* |
| Open questions | *"type of gold finish"* | ***"the specific PVC compound, as this affects temperature settings"*** |
| Citations | none | **2 documents, named** |

**The anti-hallucination mechanism.** `retrieval_used` and `sources` are set **in code from what was actually retrieved** — never asserted by the model. A recommendation made without sources is structurally incapable of claiming any.

**Selectivity is tested, not assumed:** `test_supplier_lookup_does_not_even_call_the_model` and `test_technical_question_routes_to_the_knowledge_base` both pass.

**Trust boundary.** Retrieved passages are treated as untrusted input *exactly like customer text* — screened, then fenced inside a user message, never the system prompt. A poisoned document cannot become an instruction.

**So what:** "agentic" here means a measurable branch that changes cost and output — not a framework label.

*Design note: routing ladder as a descending funnel, with the cost column emphasised. The A/B table is the proof — give it the most space on the slide.*

---

# SLIDE 9 — The design insight: "unknown" is a third answer, not a soft "no"

## One decision that shaped the schema, the scorer, the interface and the test suite

**The trap.** Capability data is incomplete. The instinct is to treat a missing value as absence of capability. **That is wrong in both directions:**

| Treatment | Failure |
|---|---|
| unknown → **no** | Viable partners silently discarded. The buyer never learns they existed |
| unknown → **yes** | Capability promised that nobody confirmed. Order collapses later |

**The resolution — three-way logic, end to end:**

| State | Score | Ranked? | Shown to user |
|---|---|---|---|
| Confirmed capable | full points | yes | ✓ factor met |
| **Not asked (`null`)** | **partial credit** | **yes** | **⚠ explicit risk flag** |
| Explicitly refused (`false`) | hard gate | **no — excluded, reason reported separately** | ✕ incompatible |

**The scoring model — six factors, 100 points, published and pinned by a test so documentation cannot drift from code:**

| Factor | Points | Partial credit when |
|---|---|---|
| Method compatibility | 30 | — *(hard gate)* |
| Material compatibility | 20 | material or list unknown → 10 |
| MOQ / quantity | 15 | limits unpublished → 7.5 |
| Accepts customer-owned goods | 15 | **unconfirmed → 7.5 + flag** |
| Deadline feasibility | 10 | lead time unknown, or ≤20% over → 5 |
| Location | 10 | same country 6 · same region 3 |

**Ties are broken deterministically** — `(-score, not verified, lead_time, id)`. The trailing id makes the order *total*, so two otherwise identical partners cannot swap places between runs.

**Where this shows up:**

- **Schema** — the dataset stores `null` rather than defaulting to `false`
- **Interface** — unknown values render as *"Not specified"*, never as blank. An honest gap is information the buyer needs before approving
- **Tests** — three eval cases exist solely to pin this distinction (cases 12, 14, 15)
- **Dataset design** — deliberately includes suppliers who refuse, and suppliers whose policy is unconfirmed, so both branches are exercised

**So what:** this is the intellectual core of the product. It is also the hardest thing to copy, because it is a modelling decision rather than a feature.

*Design note: the three-state table is the hero exhibit of the deck. Use the semantic palette — green confirmed, amber unknown, red refused. The amber row should visually dominate.*

---

# SLIDE 10 — Engineering economics: $0.0011 per project, and every figure is measured

## Marginal cost is effectively zero; the constraint is data, not compute

### Token consumption per prompt — input measured exactly [M]

Counted with `tiktoken` (`o200k_base`) over the real prompt objects, then **validated against the provider's own accounting**: measured 614, provider reported 625 — **1.8% variance**, confirming the method.

| # | Prompt | Model tier | Input tokens |
|---|---|---|---|
| 1 | Extraction — free text → typed brief | main | **614** |
| 2 | Clarifying question — one field | classifier | 497 |
| 3 | Merge answer into brief | main | 517 |
| 4 | Method recommendation — **no** retrieval | main | 635 |
| 5 | Method recommendation — **with** retrieval | main | **1,205** |
| 6 | Match explanation *(×3 per run)* | classifier | 619 each |
| 7 | RFQ prose | classifier | 448 |

**Retrieval overhead: +570 tokens** (635 → 1,205). That is the measured price of grounding, and slide 8 shows what it buys.

### One complete project run

| | Value |
|---|---|
| LLM calls, complete brief | **5** |
| LLM calls, +1 clarification round | 7 |
| **Input tokens, full run** | **4,124** **[M]** |
| Output tokens, full run | ~763 **[D]** — extraction measured at **103** **[M]**; remainder derived from schema size |
| **End-to-end model latency** | **~15–25 s** across four human gates **[M]** — extraction measured at **4.6 s** |

### Cost per complete project [D]

Arithmetic shown so it can be checked.

| Configuration | Formula | **Cost / project** | Projects per $1 |
|---|---|---|---|
| **gpt-4o-mini throughout** *(current)* |  (4,124 × $0.15 + 763 × $0.60) ÷ 10⁶ | **$0.0011** | **~929** |
| gpt-4o main + 4o-mini classifier | (1,819 × $2.50 + 453 × $10) + (2,305 × $0.15 + 310 × $0.60), ÷ 10⁶ | $0.0096 | ~104 |

### Every other resource, to scale

| Resource | Cost | Note |
|---|---|---|
| Knowledge index build | **$0.0001** one-time | 51 chunks, ~5.4k tokens. **$0 on the local backend** |
| Design image generation | **$0.04 per image** | **37× an entire project run** — which is why it is opt-in and the price is shown in the UI |
| **Total development spend, whole build** | **$0.199** **[M]** | Provider's own accounting |

**So what:** at $0.0011 per project, inference is not a cost driver at any plausible volume. A **$249** monthly subscription would fund roughly **231,000 project runs** before compute became material — about 7,700 per day, every day. **The binding constraint on this business is supplier data and distribution, not compute.**

*Design note: three stacked exhibits. The $0.0011 and the 37× contrast are the two numbers the audience should leave with. Show the formulas in small type — auditability is the credibility.*

---

# SLIDE 11 — Evidence: 308 tests, 19/19 behavioural cases, and a machine-generated results table

## Verification designed so a published claim cannot drift from the code

| Layer | Scale | Property |
|---|---|---|
| Backend tests | **298** | **Zero live model calls.** Scripted provider; retrieval on a hashing embedder whose similarity is real term overlap |
| Frontend tests | **10** | Covers the one place the client holds logic — translating the API error envelope |
| Behavioural eval | **19 cases, 19 pass** | Deterministic decision layer. No API key, no network — so it can run in CI on every change |
| Architecture audit | **15 invariants** | Fails the build on duplication or dead code |
| Live verification | full flow | Real model, real HTTP, end to end |

### The eval covers exactly the failure modes that matter

| Category | Cases |
|---|---|
| Complete brief proceeds without interrogation | 1 |
| Incomplete brief asks for one field, in published priority order | 2–6 |
| Non-blocking gaps do **not** trigger a question | 7–8 |
| Deadline feasibility, incl. past and impossible dates | 9–12 |
| Material compatibility, incl. an unsupported material | 13–14 |
| **`null` scored differently from `false`** | 12, 14, 15 |
| Hard gates: structural impossibilities excluded, never ranked | 16–17 |
| Quantity against published MOQ | 18 |
| Funnel over the real dataset | 19 |

**The integrity mechanism:** the results table in `docs/eval.md` is **generated by the harness**, and `--write` **refuses to update the document while any case fails**. A published result therefore cannot silently diverge from behaviour.

### Live end-to-end, verified [M]

Extraction → RAG-grounded method (`heat_transfer`, high confidence, correct documents cited) → 3 eligible of 7 candidates, each with a computed breakdown → RFQ generated unapproved → completed only after explicit approval. **Zero errors.**

**What the eval deliberately does *not* claim.** It verifies that stated rules hold — **not** that the weighting is *correct*. Whether material compatibility deserves 20 of 100 points is a question for customer evidence, not for a test. Claiming otherwise would be the exact overreach this project is built to avoid.

*Design note: the last paragraph matters as much as the numbers. A reviewer who sees a project state the limits of its own evaluation trusts the rest more.*

---

# SLIDE 12 — What broke, and what the fixes reveal about the engineering standard

## Both production defects shared one root cause: a code path with no test

### Defect 1 — a 90% match with an already-expired deadline

**Found by hand on the deployed site.** A supplier scored **90%** while the deadline factor read *"the deadline has already passed"*. Per-factor correct — but a **fatal, request-wide fact had been diluted into one of six weighted rows** that nobody has to expand to see.

**Fixed at three levels, not one:**

| Level | Fix |
|---|---|
| **Root cause** | The extraction prompt said *"resolve relative dates against the reference date"* without requiring a year-less date to resolve **forward**. So *"by September 15"* could land in the past |
| **Safety net** | A deterministic guard nulls any deadline earlier than today, applied after **both** extraction and the clarification merge. A date is verifiable in code — so it is not left to model discretion |
| **Coverage** | That branch **had no test at all.** Two now exist |

### Defect 2 — an opaque HTTP 500 in production

Design generation returned a bare *"An unexpected error occurred"*. Cause: `generate_image` wrapped only the API call in `try/except`, while **response parsing ran unguarded** — so a response shape the SDK's own types do not exclude raised a raw `AttributeError` that the caller's `except LLMError` could never catch.

The class had **zero direct tests**, which is precisely how it shipped. **Six now exist, two of them regression tests for the exact shapes that used to crash.**

### Diagnosability treated as a feature

The recurring operational failure was a provider `402` surfacing as *"ProductionRequirement generation failed"* — technically true, practically useless. The failing call now logs `status_code` and the provider's raw body, **which names its own remedy**:

```
status_code=402  body={"error":{"message":"You requested up to 1024 tokens,
                  but can only afford 881", ...}}
```

That one change converted a recurring mystery into a one-line configuration fix.

**So what:** the transferable lesson is not "write more tests". It is that **both defects lived in code paths that were mocked away everywhere else** — the image provider and the past-deadline branch were each invisible to a suite that otherwise passed 300 times.

*Design note: two defect cards side by side, then the log snippet as a full-width dark code block. The "so what" is the takeaway — set it apart.*

---

# SLIDE 13 — Customer discovery changed the positioning, and the product now measures whether that was right

## The first interview invalidated the original target segment

**What the interview established:**

| Finding | Consequence |
|---|---|
| For **standard** printing, buyers already use Google, Flyeralarm or a chat assistant | Standard print is not a defensible wedge. **Repositioned to non-standard requests** |
| Plain supplier discovery is **not** differentiation | Value must come from structured capability data + matching logic, not lookup |
| **Real supplier pricing cannot be reliably scraped** — it lives in non-public business logic | The product does not pretend otherwise. Every offer is flagged `is_demo: true`, and a validator **refuses** an offer that is both demo and `verified` |

**The hypothesis now under test:**

> For complex, non-standard production requests, users obtain more useful and actionable supplier options through Produce Your Brand than through generic search or a general chat assistant.

**Instrumentation shipped to test it, not to decorate it.** After a project completes: *did this help you find an option you could not easily find yourself* (yes/partly/no) · *would you contact this supplier* · *how would you normally solve this*. Stored as ordinary audit rows; readable at `GET /api/analytics/feedback`.

**Deliberately a flat list, not a dashboard.** With a handful of responses there is no aggregate worth computing, and a chart would overstate what the sample supports.

**So what:** the product was changed by evidence, and now generates evidence. That loop is the asset — not the feature list.

*Design note: three-row findings table, then the hypothesis as a bordered pull-quote, then the three survey questions as UI-style chips.*

---

# SLIDE 14 — What is next, ranked by impact on usefulness rather than by effort

## The binding constraint is data and distribution, not engineering

| # | Next | Why it ranks here | Type |
|---|---|---|---|
| 1 | **Real partner data** | 24 synthetic records is the honest gap. The algorithm is real; the partners are not. **This is what turns a prototype into something a buyer can act on** | Field work |
| 2 | **Send the RFQ** | The document is complete and human-approved; nothing transmits it. Also the precondition for measuring monetisation at all | Engineering |
| 3 | **Authentication** | Projects are addressable by UUID today. Adequate for a single-tenant prototype; **not** for real users | Engineering |
| 4 | **Per-field provenance** | `verified`/`data_source` describe a whole record, not the specific capability a buyer is trusting | Schema |
| 5 | **Price-aware matching** | `Offer.price_from` exists and drives the "best price" view, but cost is not one of the six scored factors | Engineering |

**Explicitly not built, and why:** payments, supplier self-service portal, additional production categories. Each would broaden a product that does not yet have a paying user — and **breadth without depth converts an honest narrow tool into a dishonest wide one.**

**Known limitations, stated rather than discovered by the audience:** synthetic supplier data · demo-only offers · no authentication · location scored in city/country/region tiers rather than by distance, which favours domestic suppliers · no streaming · single light theme.

*Design note: ranked table with a Type column, so the audience sees items 1 and 3 are not the same kind of work. Put the "not built" paragraph in a bordered box — deliberate scope reads as judgement, not omission.*

---

# APPENDIX

## A1 — Repository metrics [M]

| Metric | Value |
|---|---|
| Backend application code | 7,418 lines |
| Backend tests | 4,789 lines |
| Backend scripts (audit, eval, index, demo) | 764 lines |
| Frontend source | 3,506 lines |
| Documentation | 1,726 lines |
| Source files (`.py`/`.ts`/`.tsx`) | 90 |
| Commits | 29 |
| **Test-to-application code ratio** | **0.65 : 1** |
| Knowledge base | 13 documents · 21,522 bytes · 51 indexed chunks |
| Supplier dataset | 24 records, all `data_source: "synthetic"` |
| Offers dataset | 4 records, all `is_demo: true` |
| HTTP endpoints | 10 — only one advances the workflow |

## A2 — Security: five layers, and the two that matter are not detection

| # | Layer | Mechanism |
|---|---|---|
| 1 | Normalisation | NFKC, strip invisible and bidi-control characters, fold Cyrillic/Greek homoglyphs, decode base64 for inspection, cap length |
| 2 | Heuristic signals | Weighted evidence → a **score**, never a verdict. Individually weak signals accumulate |
| 3 | Model classifier | Consulted **only above a threshold**, so cost falls on suspicious input rather than every request |
| 4 | **Structure** | Untrusted content never enters a system message; fence tokens inside it are neutralised so it cannot escape its own delimiters |
| 5 | **Output validation** | Every response is a closed Pydantic schema (`extra="forbid"`), so a successful injection still cannot produce a field the system acts on |

**Layers 4 and 5 are load-bearing, and are tested as such.** `test_injected_request_cannot_reach_the_system_prompt` **disables screening entirely** and still proves an overt attack cannot become an instruction.

**Policy differs by provenance, deliberately.** Customer text is the *subject of analysis* — a brief saying *"please ignore the scratches on two of them"* must not be rejected, because blocking real work is a worse failure than reading a hostile string that structure already contains. So customer text is logged, never blocked. **Uploaded files fail closed. The curated knowledge base fails open**, because it should not be able to take itself offline.

**Uploads:** extension allowlist ∩ sniffed magic bytes — name and content must agree. PNG, JPEG, PDF only; **SVG refused outright** (XML that can carry script). 5 MB cap, stored under a generated name so a crafted filename cannot traverse directories. Nothing parses, renders or executes the body.

## A3 — Optional on-device embeddings

Retrieval is the one component needing no hosted model. `PYS_EMBEDDING_BACKEND=local` embeds via **fastembed** + `BAAI/bge-small-en-v1.5`.

| Consideration | Detail |
|---|---|
| Why fastembed, not sentence-transformers | ONNX Runtime instead of PyTorch: **measured +81 MB** to the environment, versus 2–3 GB for torch. On a container host that is the entire decision |
| Why it matters | Removes the only recurring cost in the retrieval path — the knowledge base keeps working when the provider balance is exhausted, **which is the failure this project actually hit** |
| Quality trade-off | 384 dimensions vs 1,536. On a 21 KB corpus the difference is negligible; **on a large corpus it would not be**, which is why hosted remains the default |
| Correctness catch | Switching backend changes vector dimensionality, so an index built by the other backend is **unusable, not merely stale**. The effective model name feeds the index fingerprint, making that a rebuild rather than a silent wrong-shape read |
| Verification status | Wrapper logic covered by 12 tests. **The weight download was not exercised in the build environment** (no network access to huggingface.co) and must be confirmed on a connected machine |

## A4 — Anticipated questions

**"Why not just ask a chat assistant to find printers in Berlin?"**
For a plain lookup it is a genuine competitor, and the README says so. The difference is structured production intelligence it cannot fabricate — published MOQs, lead times, materials, customer-owned-goods policy — and a *reproducible* score over them. It will not tell you consistently which of 24 partners clears a 12-day deadline at 500 units, and it will answer differently if you reword the question.

**"Your supplier data is synthetic — what did you actually prove?"**
The algorithm, not the market. Every record is labelled synthetic, `website` is `null` throughout, and the provenance is stated in the data itself. Genuinely demonstrated: the workflow, the scoring, the null discipline, the injection defence, and that retrieval changes the answer. Substituting real data changes no schema.

**"Why deterministic scoring rather than letting the model rank?"**
Reproducibility and defensibility. Model ranking drifts with phrasing and name familiarity, and cannot be audited. Here identical inputs give byte-identical output, tie order included; the weights are published *and pinned by a test*; and the buyer sees every factor's award and reason.

**"How do you know the retrieval is not decorative?"**
Two ways. The A/B on slide 8 shows it changes confidence, constraint count and open questions. And routing is tested for *selectivity*: a supplier lookup does not retrieve and does not even call the model, while a feasibility question does.

**"No authentication?"**
Correct, and it is the first thing that must change before real users. Listed openly in Known limitations and in ETHICS.md rather than glossed over.

**"What stops the model inventing a supplier?"**
Three independent mechanisms: it has no access to the dataset (tool-only, and the system prompt states the rule); every id is resolved through the repository with unknown ids dropped rather than guessed; and an id that is neither offered nor real is refused at the selection gate. A test is named for exactly that case.

**"Why FAISS and not Chroma?"**
Fewer dependencies, and persistence is a plain index file plus JSON rather than a pickle — a pickled index is arbitrary code execution waiting for a file swap. At 13 documents, retrieval quality is not the deciding factor; safety and dependency footprint are.

**"$0.199 total spend — is that credible?"**
It is the provider's own accounting. At 4,124 input tokens per run on gpt-4o-mini, the arithmetic on slide 10 gives $0.0011 per project; development involved a few hundred runs, most of them against a scripted provider that makes no API call at all. The test suite is free by design, which is why it can run on every change.
