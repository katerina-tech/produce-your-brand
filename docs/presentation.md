# Capstone presentation — Produce Your Brand

**Format:** 10 minutes presenting, 5 minutes questions.
**Spine:** SCR — Situation, Complication, Resolution.

Speaker notes, not slide text. Every number here is checkable in the repository; nothing is rounded up for effect.

**Suggested timing**

| Section | Minutes |
|---|---|
| 1. Problem | 1.5 |
| 2. Solution | 2.5 |
| 3. Data | 1.5 |
| 4. Evaluation | 2 |
| 5. Challenges | 2 |
| 6. What's next | 0.5 |

---

## 1. The problem

**Situation.** A Berlin business already owns its product and already has its branding. It wants 100 black yoga mats with a gold logo.

**Complication.** Before a single quote arrives, someone has to work out:

- which customisation technique is even *physically possible* on PVC (laser engraving is not — it releases hydrogen chloride)
- which production partners exist
- whether any of them accept **customer-owned goods** — most enquiries never think to ask
- minimum order quantities, lead times against the deadline
- and then re-explain the same job, by hand, to every supplier

That is days of undifferentiated work. And the failure mode is expensive: an enquiry that promises the impossible wastes real weeks.

**Who it's for.** Berlin SMEs, startups, agencies and event teams needing small-to-medium batches of customised physical goods.

**Why it matters now.** The reasoning is the hard part, not the search. That is exactly what an agent can do — *if* it can be stopped from inventing facts.

---

## 2. The solution

**One sentence:** an AI agent that turns a plain-English description into a supplier-ready request for quotation, with a human approving every step.

```
free text → typed Production Brief → production method → partner matches → RFQ
              ✋ confirm              ✋ confirm          ✋ select        ✋ approve
```

### The design decision everything follows from

> **The model handles language. Code handles every fact and every number.**

| Concern | Owner | Why |
|---|---|---|
| Extracting the brief from free text | **LLM** | natural language → typed object |
| Which fields are missing | **Python** | "is this field null" is not a judgement call |
| Production method | **LLM + RAG** | genuine technical reasoning, with citations |
| Supplier search & scoring | **Python** | must be reproducible; must not depend on phrasing |
| Match explanation prose | **LLM** | prose only, over a score it cannot change |
| RFQ structure | **Python** | a document shape is a contract, not a generation |

Consequence: a supplier capability can never be invented, and a match score can never be argued up by rewording the request.

### Architecture

- **One** LangGraph `StateGraph`, five `interrupt()` points. Human-in-the-loop is *structural* — the graph physically cannot pass a gate without a resume payload.
- **FastAPI** backend, **Next.js** frontend. The browser never talks to FastAPI: reads happen in server components, writes through server actions, so no credential ever reaches the client.
- **Two memory stores, deliberately separate:** LangGraph's SQLite checkpointer for conversation state; our own `projects` table for the durable business record — so a project survives a restart without depending on a checkpoint format we don't own.
- **FAISS** directly rather than through a framework wrapper: fewer dependencies, and persistence is an index file plus JSON instead of a pickle. A pickled index is arbitrary code execution waiting for someone to swap the file.
- Deployed on **Railway**, two Dockerised services, with a persistent volume for the databases.

### Agentic RAG — the part that is actually *agentic*

Retrieval does not fire on every request. A dedicated node decides, cheapest signal first:

1. **Deterministic fast path** — "which suppliers in Berlin do laser engraving?" → the supplier repository, **no model call at all**.
2. **Deterministic rule** — material unconfirmed → retrieve, because feasibility genuinely cannot be assumed.
3. **The model** — only for the genuinely ambiguous middle.

If the router itself fails, it errs toward retrieving: an unnecessary lookup is cheap, a confident wrong technical claim is not.

`retrieval_used` and `sources` are set **in code from what was actually retrieved** — so a recommendation made without sources cannot claim any.

---

## 3. The data

| Dataset | Size | How it's handled |
|---|---|---|
| Supplier records | 24 | **Synthetic and labelled as such**: every record carries `data_source: "synthetic"`, `website` is `null` on all of them so no entry points at a real company, and the file's own `_provenance` block says so |
| Knowledge base | 13 documents, ~21.5 KB | Curated, internally authored, YAML frontmatter (`title`, `production_method`, `materials`, `source`, `source_url`, `updated_at`). `source_url` is `null` throughout — **no citation points at a document this project did not write** |
| Supplier offers | 4 | **Demo data only** (`is_demo: true`), and a model validator *refuses* an offer that is both demo and `verified` |

### Pipeline

`load → markdown-header split → size split (800/120) → embed → FAISS`

The index **self-heals**: a fingerprint over document bytes plus the embedding model name means editing a document or switching model forces a rebuild rather than silently searching a stale corpus.

### The discipline the whole design turns on

> **`null` is not `false`.**

A supplier whose customer-owned-goods policy is `null` has *not been asked* — that scores partial credit with a visible risk flag. A supplier that has **explicitly refused** scores zero and is gated out entirely.

Conflating the two would either hide a real blocker or silently discard a viable partner. It is why the dataset stores `null` rather than defaulting to `false`, and the dataset is deliberately built to exercise every branch: suppliers that refuse customer goods, suppliers whose policy is unconfirmed, MOQs above and below the demo quantity, unknown lead times.

### Trust boundary

Retrieved passages are treated as **untrusted input, exactly like customer text** — screened, then fenced in a *user* message, never the system prompt.

---

## 4. Evaluation

### Test suite

**298 backend tests, 10 frontend tests.** No test calls a live model, and none calls the real Overpass API either. The graph runs on a scripted provider and retrieval on a hashing embedder whose similarity is real term overlap — so the suite is free, fast and deterministic.

### Behavioural eval: 19 cases (`docs/eval.md`)

Evaluates the **decision layer**, which is where correctness claims live: which field gets asked next, and how a supplier scores.

| Category | Cases |
|---|---|
| Complete brief proceeds without interrogation | 1 |
| Incomplete brief asks for exactly one field, in priority order | 2–6 |
| Non-blocking gaps do **not** trigger a question | 7–8 |
| Deadline feasibility, including past and impossible dates | 9–12 |
| Material compatibility, including an unsupported material | 13–14 |
| `null` scored differently from `false` | 12, 14, 15 |
| Hard gates: structural impossibilities excluded, never ranked | 16–17 |
| Quantity against published MOQ | 18 |
| The funnel over the real dataset | 19 |

**19 of 19 pass.** The table is *generated by the harness*, and `--write` refuses to update the doc while any case fails — so a published result cannot drift from what the code does.

### Proof the RAG earns its place

Same request, retrieval off vs on:

| | Without retrieval | Grounded |
|---|---|---|
| confidence | medium | **high** |
| constraints | 1, generic | **4**, including the corpus's "1–2 mm line thickness for weeded vinyl" |
| open questions | "type of gold finish" | **"the specific PVC compound, as this affects temperature settings"** |

Ask for *engraving* on those mats and the same corpus explains why no reputable shop will do it. A model working from recall might cheerfully suggest it.

### Live verification

Driven end to end against the real model through the HTTP API: extraction → RAG-grounded method (`heat_transfer`, high confidence, citing the two correct documents) → 3 eligible of 7 candidates → RFQ generated unapproved → completed only after explicit approval. **Zero errors.**

### Architecture audit

`scripts/audit_architecture.py` fails the build on a second LangGraph, prompt module, LLM factory, vector store, knowledge directory or supplier data source — and on any module under `app/` becoming unreferenced dead code. It also asserts **zero LLM imports in the deterministic scorer**.

### What the eval deliberately does *not* claim

It checks that stated rules hold — **not** that the weighting is *right*. Whether "material compatibility is worth 20 points" is good product design is a question for user evidence, not for a test.

---

## 5. Challenges

### The design challenge: making "unknown" a first-class answer

The instinct is to treat a missing capability as a "no". That is wrong in both directions, and it took real thought to get right:

- treat unknown as **no** → you discard viable partners and the buyer never learns they existed
- treat unknown as **yes** → you promise capability nobody confirmed

**Resolution:** three-way logic throughout. `null` scores partial credit *with a visible risk flag*; an explicit `false` is a hard gate that removes the supplier from ranking entirely and reports the reason separately. This one decision shaped the dataset schema, the scorer, the UI copy ("Not specified", never blank) and three eval cases.

### The debugging story: a 90% match with an impossible deadline

Found by hand on the deployed site. A supplier scored **90%** while the deadline factor read *"the deadline has already passed"* — per-factor correct, but a fatal, request-wide fact diluted into one of six weighted rows that nobody has to expand to see.

Traced to two causes, and fixed at both levels:

1. **Root cause** — the extraction prompt said "resolve relative dates against the reference date" without saying a year-less date must resolve *forward*. So "by September 15" could land in the past.
2. **Safety net** — a deterministic guard nulls out any deadline earlier than today, applied after *both* extraction and the clarification merge. A date is verifiable in code, so it is not left to model discretion — the same principle already used for verified design attachments.
3. **Coverage** — that branch had **no test at all**. Two now exist.

### The honest one: an opaque 500 in production

Design generation returned a bare *"An unexpected error occurred"*. Cause: `generate_image` wrapped only the API call in `try/except`, while the response *parsing* ran unguarded — so a response shape the SDK's own types don't rule out raised a raw `AttributeError` that the caller's `except LLMError` could never catch.

The class had **zero direct tests**, which is precisely how it shipped. Six now exist, two of them regression tests for the shapes that used to crash.

### Diagnosability as a feature

The recurring failure was a provider `402`, surfacing as an unhelpful *"ProductionRequirement generation failed"*. Now the failing call logs `status_code` and the provider's raw body, which names its own remedy:

```
status_code=402  body={"error":{"message":"You requested up to 1024 tokens,
                  but can only afford 881", ...}}
```

That one change turned a mystery into a one-line fix.

---

## 6. What's next

**Ranked by what would most change the product's usefulness, not by ease.**

1. **Real partner data.** 24 synthetic records is the honest gap. The matching algorithm is real; the partners are not. This is what turns a working prototype into something a buyer can act on — and it is field work, not engineering.
2. **Send the RFQ.** The document is complete and human-approved; nothing transmits it. This is also the prerequisite for measuring monetization at all.
3. **Authentication.** Projects are addressable by UUID today. Fine for a single-tenant prototype, not for real users.
4. **Per-field provenance.** `verified`/`data_source` describe a whole supplier record, not the individual capability a buyer is trusting.

**And the finding that matters most**, from the first customer-discovery interview: for *standard* printing, users can already use Google or ask ChatGPT. The product's real edge is **non-standard requests** — unusual material, customer-owned goods, odd quantity, tight deadline. Positioning shifted accordingly, and the app now carries instrumentation (`POST /projects/{id}/feedback`) to gather evidence for or against that hypothesis rather than assume it.

---

## Anticipated questions

**"Why not just ask ChatGPT to find printers in Berlin?"**
For a plain lookup, ChatGPT is a real competitor and I say so in the README. The difference is structured production intelligence it cannot fabricate: published MOQs, lead times, materials, customer-owned-goods policy — and a *reproducible* score over them. ChatGPT will not tell you consistently which of 24 partners clears a 12-day deadline at 500 units, and it will phrase a different answer if you reword the question.

**"Your supplier data is synthetic — what did you actually prove?"**
The algorithm, not the market. Every record is labelled synthetic, `website` is `null` throughout, and the provenance is in the data itself. What is genuinely demonstrated: the workflow, the scoring, the null discipline, the injection defence, and that retrieval changes the answer. Swapping in real data changes no schema.

**"Why deterministic scoring instead of letting the model rank?"**
Reproducibility and defensibility. An LLM ranking drifts with phrasing and with name familiarity, and cannot be audited. Identical inputs here produce byte-identical output, tie order included, and the weights are published *and pinned by a test* so the docs cannot drift from the code. The buyer can also see every factor's award and reason.

**"How do you know the RAG isn't decorative?"**
Two ways. The A/B above shows retrieval changes confidence and constraints. And routing is tested for *selectivity*: a supplier lookup does not retrieve and does not even call the model, while a feasibility question does.

**"No authentication?"**
Correct, and it is the first item that must change before real users. Listed openly in Known limitations and in ETHICS.md rather than glossed over.

**"What stops the model inventing a supplier?"**
Three independent things: it has no access to the dataset (tool-only, and the system prompt says so); every id is resolved through the repository, with unknown ids dropped rather than guessed; and an id that is neither offered nor real is refused at the selection gate. There is a test named for exactly that.

**"Why FAISS and not Chroma?"**
Fewer dependencies, and persistence is a plain index file plus JSON rather than a pickle — a pickled index is arbitrary code execution waiting for a file swap. At 13 documents the retrieval quality difference is not the deciding factor; the safety and dependency footprint are.
