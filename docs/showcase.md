# Showcase submission — copy/paste source

Text prepared for [showcase.turingcollege.com](https://showcase.turingcollege.com/). The upload itself is manual — the showcase is an external site, so nothing here posts it for you.

**After uploading:** paste the resulting URL into `README.md`, on the `**Showcase:**` line near the top. The capstone brief requires that link to be present, near the top, before booking the review.

Field names below are a best guess at the form's shape — map them onto whatever it actually asks for.

---

## Title

```
Produce Your Brand — an AI sourcing agent for custom physical production
```

## One-line summary

```
Turns a plain-English production request into a supplier-ready request for
quotation, with a human approving every step.
```

## Short description (~50 words)

```
A Berlin business with 100 yoga mats and a gold logo has to work out which
technique is even possible, find partners, check who accepts customer-owned
goods, and re-explain the job to each one. This agent does that reasoning in
one guided workflow — and never invents a supplier fact.
```

## Full description

```
Produce Your Brand is an AI agent that turns a plain-English description of a
custom production job into a supplier-ready request for quotation.

The problem: a business that wants 100 of its own yoga mats printed with a gold
logo currently has to work out which customisation technique is physically
possible (laser engraving on PVC is not — it releases hydrogen chloride), hunt
for production partners, discover one by one whether any accept customer-owned
goods or can meet the deadline, then re-explain the same job by hand to every
supplier. Days of undifferentiated work before a single quote arrives.

How it works: one LangGraph workflow with four human approval gates. An LLM
extracts a typed Production Brief from free text and asks about only the fields
that genuinely block progress. A retrieval step grounds the production-method
recommendation in a curated knowledge base — but only when the question
warrants it; a plain supplier lookup skips retrieval and does not even call the
model. Suppliers are then filtered and scored in plain Python against six
published weighted factors. The resulting RFQ is assembled deterministically
for a human to edit and approve.

The design decision everything follows from: the model handles language, and
code handles every fact and every number. A supplier capability can never be
invented, and a match score can never be argued up by rewording the request.

One idea worth calling out: "unknown" is not "no". A supplier whose
customer-owned-goods policy is unconfirmed scores partial credit with a visible
risk flag; one that has explicitly refused is excluded entirely. Conflating the
two would either hide a real blocker or silently discard a viable partner.

Honest about its limits: the 24 supplier records are synthetic and labelled as
such in every row, supplier offers are demo data, and there is no
authentication yet. The matching algorithm is real; the partners are not.
```

## Tech stack

```
Python, FastAPI, LangGraph, LangChain, OpenAI API (via OpenRouter), FAISS,
fastembed (optional on-device embeddings), SQLite, TypeScript, Next.js,
Tailwind, Leaflet, Docker, Railway
```

## Key features

```
- One LangGraph StateGraph with five human-in-the-loop interrupt points —
  the graph physically cannot pass a gate without an explicit human action
- Agentic RAG: a routing node decides whether retrieval is needed at all,
  cheapest signal first; retrieval demonstrably changes the answer
- Deterministic supplier scoring in pure Python — no LLM import, reproducible
  byte-for-byte, weights published and pinned by a test
- Five-layer prompt-injection defence where the two load-bearing layers are
  structural (untrusted text never enters a system prompt) and schema
  validation, not detection
- Two memory stores: LangGraph's checkpointer for conversation state, a
  separate projects table for the durable record
- 298 backend + 10 frontend tests, none calling a live model; plus a 19-case
  behavioural eval harness whose results table is generated, not hand-written
```

## Links

```
Live demo:  https://produceyourstuff.up.railway.app/
Repository: https://github.com/katerina-tech/produce-your-brand
```

> Note: the deployed URL still carries the previous product name. Only
> user-facing copy was rebranded — renaming the Railway service and the
> repository were deliberately left out of scope, and the old repository URL
> redirects.

## Suggested screenshots

Both already in the repository, and both are of the live deployment rather than mockups:

- `docs/assets/homepage-desktop.png`
- `docs/assets/homepage-mobile.png`

Worth capturing additionally, since they show the reasoning rather than the marketing:

1. **Production brief** — with "Not specified" visible on an unknown field, which is the null-discipline made visible
2. **Method recommendation** — showing confidence, open questions, and the knowledge-base citations
3. **Partner matches** — with a score breakdown expanded, so the six factors and their reasons are on screen
