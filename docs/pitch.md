# Produce Your Brand — investor & hackathon pitch

**This is not the capstone deck.** [`presentation.md`](presentation.md) argues *"this is well engineered"*. This argues *"this makes money"*. Different audience, different burden of proof.

**Two cuts:**
- **Slides 1–10** — accelerator / investor pitch (~8 minutes)
- **`HACKATHON CUT`** at the end — 3 minutes, 5 slides

**Number discipline:** every figure is marked **[M]** measured, **[D]** derived with assumptions shown, or **[E]** estimate needing verification. Do not present an **[E]** as fact — if pressed, say "that's our estimate, unverified". An investor forgives an honest gap and punishes a bluff.

---

# 0 — Selection round: run of show

**Thursday 16:30 · 5 minutes · 3 speakers — Katerina, Sebastian, Stefan.**

The judges are picking *a team to send to Berlin*, not grading a business plan.
They are asking two things: do I understand this in the first twenty seconds, and
will this team actually deliver at the event. So we lead with the one advantage
almost nobody else in the room has — **we are not bringing an idea, we are bringing
a deployed product.**

## The sentence everything hangs on

> **You describe what you want made. We tell you if it&rsquo;s possible, how to make it,
> and who can make it.**
>
> Today that is a week of emails. We do it in 30 seconds.

Nobody says "agent", "graph", "RAG", "pipeline" or "LLM" on stage. Not once.

## Timeline

| Time | Who | Block | Length |
|---|---|---|---|
| 0:00 | Katerina | What it is — the sentence, then the boundary line | 30 s |
| 0:30 | Katerina | Why it is hard — four unknowns, then the print shop quote | 30 s |
| 1:00 | Katerina | **Live demo** — four beats on the deployed product | 90 s |
| 2:30 | Sebastian | Who I am — strength, proof, what I own in the 48 hours | 30 s |
| 3:00 | Stefan | Who I am — same beats, different ownership | 30 s |
| 3:30 | Sebastian *or* Stefan | The concept and the close — ends on the one sentence | 60 s |
| 4:30 | — | Buffer, deliberately empty | 30 s |

## The lines

**Katerina, 0:00–1:00.** The one sentence, then stop for a beat. Then the boundary,
which answers half the questions before they are asked: *"500 hoodies with a logo?
Google solves that, and always will. 100 yoga mats you already own, printed in gold?
Nobody can tell you if that is even possible."* Then the four unknowns as a fast list
— can it physically be made · who accepts goods you already own · does the minimum
order fit · is the deadline real — closed with *"every one of these is knowable. You
just discover them one at a time, by email, over a week."* Then the interview:
*"We interviewed a Berlin print shop. Their words: ChatGPT macht keine Bewertungen —
it cannot evaluate suppliers. That is the gap we build in."*

**Katerina, 1:00–2:30 — live demo.** Paste *"100 black yoga mats, PVC, I own them,
gold logo, Berlin"*. Point at **"Not specified"** — *"it tells you what it does not
know instead of guessing."* Then the citation — *"it refuses laser on PVC, because
that releases hydrogen chloride, and it cites the document."* Then one supplier's
score breakdown — *"six factors, each with a reason. This is the screen ChatGPT
cannot produce."* Handoff: *"The two people who built this with me — Sebastian."*

**Sebastian and Stefan, 30 s each.** Three beats, ten seconds each: what you are
strong at, one concrete thing that proves it (with a number if you have one), and
**what you own in the 48 hours**. The third beat matters most and the two of you must
not overlap. Not a CV, not a stack list, nothing that any engineer in the room could
also say.

**The close, 3:30–4:30.** Why it holds: *"the model only handles language. Every
number and every fact is owned by code — our scoring has zero AI in it, checked
automatically on every build. Same input, same answer, every time. That is not about
purity: a supplier will only pay for leads from a system that cannot misrepresent
what they can do."* Then the hackathon plan, which is the strongest thing we say in a
round about execution: *"We are not bringing an idea. The hard part is built,
deployed, and covered by 309 tests. In 48 hours we close the loop: real Berlin
suppliers in the database, requests for quotation actually sent, replies parsed back
into one comparison. Right now we give you an answer. After Berlin we give you a
quote."* Then the final line, and then stop:

> *"You describe what you want made. We tell you if it is possible, how to make it,
> and who can make it. Send us to Berlin and we will make it a transaction."*

## Before Thursday

1. **Rehearse the two handoffs, twice.** Non-negotiable — handoffs are where
   three-person pitches stall, and each costs about five seconds.
2. **One laptop, one browser.** Katerina drives throughout; the demo never changes hands.
3. **Decide who closes at 3:30** — one name, and that person says the final sentence
   out loud three times beforehand.
4. **Agree the 48-hour split** so the two introductions do not overlap. Suggested: one
   owns real supplier data, one owns sending RFQs and parsing replies.
5. **Second tab with a finished project open**, in case the demo stalls. Never debug
   in front of judges.
6. **One warm-up run from the venue**, 15 minutes before.

---

# 1 — The hook

## Produce Your Brand
### Your customer wants 100 of their own yoga mats printed in gold. Which shop can even do that — and who says yes to goods they didn't sell you?

**We answer that in 30 seconds. Today it takes days.**

Live product, not a mockup: **produceyourstuff.up.railway.app**

*Speaker: open with the yoga mat. It is concrete, everyone pictures it, and it contains the whole problem.*

---

# 2 — The problem

## Custom production fails on four unknowns, and the buyer discovers them one at a time

**Real request. Four ways it dies:**

| Unknown | The trap |
|---|---|
| **Is it physically possible?** | PVC under a laser releases hydrogen chloride. No serious shop will touch it — but you find out after a week of emails |
| **Who accepts goods you already own?** | Many producers only decorate stock they sold you. **Almost nobody thinks to ask upfront** |
| **Does the minimum order fit?** | 100 units is below many minimums. Silent disqualification |
| **Is the deadline real?** | Lead time plus buffer. Discovered last, when it is most expensive |

**Each is individually knowable. The cost is that they surface serially, by email, over days — and you re-explain the same job to every supplier.**

**And this is not the €50 flyer market.** Ordinary print goes to Google or Flyeralarm and always will. This is the request where ordinary search stops working — which is exactly what our customer interview confirmed.

*Speaker: land the "goods you already own" line. It gets a reaction from anyone who has ordered merch.*

---

# 3 — Why now, and why it is still unsolved

## The catalogues cover standard products. Nobody has structured the hard requests.

| | Coverage |
|---|---|
| **Flyeralarm, Saxoprint, Vistaprint** | Standard print at scale. Consolidated, price-driven |
| **Promidata, PSI** (DACH catalogue data) | Standard promotional products. **Non-standard work: not covered** |
| **Google** | Finds companies. Does not know MOQs, lead times, or who accepts customer-owned goods |
| **ChatGPT** | Explains techniques well. **Cannot rate suppliers, cannot quote, answers differently each time** |

**Two things changed and made this buildable now:**

1. **Language models can finally turn messy free text into a reliable typed brief** — the step that used to require a human account manager.
2. **Structured feasibility reasoning is now cheap.** Our full pipeline costs **$0.0096 per request on gpt-4o** — the model the live demo runs — or **$0.0011 on gpt-4o-mini** **[M][D]**. Two years ago that arithmetic did not work.

**The direct quote from our interview, on the differentiator:**

> *"ChatGPT macht keine Bewertungen."*
> ChatGPT can't evaluate suppliers. It has no ratings, no proven offers, no discounts, no accountability.

*Speaker: this slide kills the "isn't this just ChatGPT" objection before it is asked. Do not skip it.*

---

# 4 — The product

## Describe the job in plain language. Get a feasibility-checked brief, the right method, and matched partners.

```
"100 black yoga mats, PVC, I own them, gold logo, Berlin"
                    │
                    ▼
   ①  PRODUCTION BRIEF          typed, gaps shown honestly as "Not specified"
                    │
   ②  METHOD + FEASIBILITY      heat transfer · high confidence
                                 ⚠ cited: "PVC must not be laser cut"
                    │
   ③  MATCHED PARTNERS          3 of 7 eligible, each scored on 6 factors
                                 Best match · Best price · Fastest
                    │
   ④  REQUEST FOR QUOTATION     9 questions the supplier must answer
```

**A human approves every one of the four steps.** Nothing is ordered, sent, or committed automatically.

**The one thing to demo live:** open a supplier's score breakdown. Six factors, each with a computed reason. **That is the screen ChatGPT cannot produce.**

*Speaker: 45 seconds of live product here beats any slide. Have a completed project pre-loaded as a fallback.*

---

# 5 — Why this is defensible

## The moat is proprietary structured capability data — not the model. Anyone can call the same model.

| Layer | What it is | How hard to copy |
|---|---|---|
| **Feasibility knowledge base** | 13 curated documents on what each technique can and cannot do — material limits, safety refusals, minimum line thickness | **Hard.** Domain expertise, not scrapeable. Grows with every job |
| **Structured capability data** | MOQ, lead time, materials, customer-owned-goods policy per supplier | **Hard.** Our interview established this **cannot be reliably scraped** — pricing sits in non-public business logic. Whoever collects it manually owns it |
| **Deterministic scoring** | 6 weighted factors, reproducible byte-for-byte | Medium — but it is what makes us auditable and ChatGPT not |
| The AI layer | Extraction, method reasoning | **Easy. Not our moat, and we don't claim it is** |

**The design decision behind the trust story:** the model handles language, **code owns every fact and number**. A supplier capability can never be invented, and a score cannot be argued up by rewording the request. This is enforced architecturally — the scorer has zero AI imports, checked automatically on every build.

**Why that matters commercially:** a supplier will only pay for leads from a system that cannot misrepresent their capabilities.

---

# 6 — Market

## A fragmented, low-digitisation segment where the hard requests are unserved

| | | |
|---|---|---|
| **TAM** | German promotional products & custom print | **~€3–4bn** industry revenue **[E]** |
| **SAM** | Non-standard requests — unusual material, customer-owned goods, odd quantity, tight deadline | **~15–25%** of enquiry volume **[E]** |
| **SOM** | Berlin + intermediaries who source repeatedly (merch agencies, promo distributors) | **~3,000–5,000** firms in Germany **[E]** |

> **These three are [E] — order of magnitude, from industry-association reporting. Unverified.** State that if asked. Sourcing them properly is on the 30-day plan.

**The structural fact that is not an estimate — and it decides the go-to-market:**

| Who | Frequency of a custom-production request |
|---|---|
| End business | **2–4 × per year** — no habit, no subscription |
| **Sourcing intermediary** (merch/event agency, promo distributor) | **5–30 × per week** |

**We sell to the second.** Same product, radically better economics — and they bring their own client demand with them.

---

# 7 — Business model

## Two revenue streams, ~99.9% gross margin, and the commission does the heavy lifting

**Priced as our interview partner proposed it:**

| Stream | Price | Status |
|---|---|---|
| **Qualified lead** | **€3** fixed, per lead delivered to a supplier | Proposed by the interviewed supplier |
| **Success fee** | **1.5–5%** of completed order value | Same source — **range not yet settled** |
| *(Layer 2)* Agency subscription | €99–499 / month for repeat sourcers | Our hypothesis, untested |

### Unit economics [D] — assumptions stated, arithmetic checkable

| Assumption | Value |
|---|---|
| Leads per converted order | 5 (20% conversion) |
| Average order value | €1,000 |
| Commission taken | 3% (midpoint of the quoted range) |
| Model priced | gpt-4o — the deployed default, not the cheap one |

| Per 5 leads delivered | |
|---|---|
| Lead fees — 5 × €3 | €15 |
| Success fee — 1 × €1,000 × 3% | €30 |
| **Revenue** | **€45** |
| **Our compute cost** — 5 × $0.0096 (gpt-4o, as deployed) | **≈ €0.044** |
| **Gross margin** | **99.90%** |

### Path to €5,000 MRR

**€5,000 ÷ €45 ≈ 111 orders/month → ~555 qualified leads/month → ~25 per working day** (22 working days).

**This is the number to remember.** Not thousands of leads — **about 25 a working day**, because the success fee carries roughly two-thirds of the revenue.

**Compute never becomes the constraint.** At the deployed gpt-4o price, €5,000 of monthly revenue consumes about **€4.90 of inference** — and about **€0.56** if we switch to gpt-4o-mini, which the code already supports. The constraint is supplier data and distribution — which is what we would use an accelerator for.

*We quote the expensive model on purpose. The margin survives it, so nobody has to take the cheap number on trust.*

*Speaker: slide 7 is the deck. If you only get one slide, make it this one. Lead with "25 leads a working day".*

---

# 8 — Where we are

## Working product, validated problem, instrumented to measure the next answer

**Built and live [M]:**

| | |
|---|---|
| Deployed product, full flow end to end | ✅ |
| Automated tests | **308**, none calling a live model |
| Behavioural evaluation | **19 cases, 19 pass** — table machine-generated, refuses to publish while failing |
| Total build spend | **$0.199** |

**Validated by customer discovery** — and it *changed* the product:

| What we learned | What we changed |
|---|---|
| Standard print is not defensible | Repositioned entirely to non-standard requests |
| Pricing cannot be scraped | Built a provenance model instead of pretending — every offer flagged `is_demo`, and code **refuses** an offer that claims to be both demo and verified |
| ChatGPT can't evaluate suppliers | Ratings and proven-offers are now the top of the roadmap |

**Instrumented to test the core hypothesis, not assume it.** After each project the product asks: *did this find you an option you couldn't easily find yourself?* · *would you contact this supplier?* · *how would you normally solve this?*

### What we do not have, stated plainly

- **No paying customers yet.** The product is ready; distribution has not started
- **Supplier records are synthetic**, labelled as such in every row. The algorithm is real; the partners are not
- **Monetisation is a hypothesis** — our own interview quoted 5% and 1.5%, a 3× spread, which tells us the number is not settled

*Speaker: say these out loud before you are asked. Volunteering them converts your weakest slide into your most credible one.*

---

# 9 — The 30-day plan

## We are not blocked on engineering. We are blocked on supply and distribution.

| Weeks | Action | Success measure |
|---|---|---|
| **1–2** | 15 conversations with Berlin merch agencies & promo distributors, live demo in each | 3 say they would pay |
| **1–3** | Onboard **10–15 real Berlin suppliers** by phone — capabilities, MOQ, lead time, customer-owned-goods policy | Synthetic dataset replaced. **This is the moat** |
| **3** | Turn on RFQ sending + lead attribution | The revenue loop closes end to end |
| **4** | 3 paid pilots | **First euro of revenue** |

**Then, from the interview, in this order:** supplier ratings → proven successful offers → time-based tariffs (rush vs standard) → partner-posted discounts.

**Deliberately not building:** copy shops (commodity — contradicts our own positioning), carpentry (no knowledge-base overlap), payments, a supplier portal. Breadth without depth turns an honest narrow product into a dishonest wide one.

---

# 10 — The ask

## We have built the hard part. We need supply and distribution.

**What is already de-risked:** the product works, the problem is validated by a real supplier interview, marginal cost is effectively zero, and the trust architecture means a supplier can rely on how they are represented.

**What we are joining an accelerator to solve:**

| Need | Why |
|---|---|
| **Supplier network access** | 10–15 real Berlin producers is a warm-intro problem, not a code problem |
| **B2B distribution** | German SMEs buy on referral and reference, not on ads |
| **Pricing validation** | Our interview gave a 3× range on commission. We need real transactions to settle it |

**What we bring:** a deployed product, 308 tests, one validated customer interview that already redirected the strategy, and near-zero marginal cost.

> **Custom production is a market where the reasoning is the bottleneck, not the search. We built the reasoning. Now we need the supply.**

---
---

# FALLBACK — 3 minutes, one speaker

The same argument with no handoffs, for a shorter slot or if you end up presenting alone.

### H1 — Hook (20s)
*"Your customer wants 100 of their own yoga mats printed in gold. Which shop can even do it — and who accepts goods they didn't sell you? Today: days of emails. With us: 30 seconds."*

### H2 — The problem, one line (20s)
**Four unknowns kill custom production orders — feasibility, customer-owned goods, minimum order, deadline — and buyers hit them one at a time.** Ordinary print goes to Google. This is everything else.

### H3 — LIVE DEMO (90s) ← *the majority of your time*
1. Paste: *"100 black yoga mats, PVC, I own them, gold logo, Berlin"*
2. Brief appears — **point at "Not specified"**: *"it tells you what it doesn't know instead of guessing"*
3. Method: heat transfer, **and the citation** — *"it refuses laser on PVC, because that releases hydrogen chloride. It cites the document."*
4. Open a score breakdown — **six factors, each with a reason** — *"this is the screen ChatGPT cannot produce"*

### H4 — Why not ChatGPT (30s)
*"ChatGPT explains techniques. It cannot rate a supplier, cannot tell you a minimum order, and answers differently every time you rephrase. Our scoring is arithmetic — same input, same answer, every factor auditable. That quote is from a real print shop we interviewed."*

### H5 — The money (20s)
**€3 per lead + 3% success fee. Compute costs $0.0096 per request on the model you just watched — 99.9% gross margin. €5,000 a month is ~25 qualified leads a working day.**

**Fallback:** have a completed project open in a second tab. If the API stalls, switch and keep talking. **Never debug in front of judges.**

---

# Before you present — 15 minutes of work

1. **Run the demo once from the venue, ~15 minutes before.** The API budget is confirmed healthy ($34.50 of $35 left, paid model verified serving), so the real risks are venue wifi and a cold container — one warm-up run removes both
2. **Pre-load a completed project** in a second browser tab as a fallback
3. **Rehearse slide 7 out loud.** "25 leads a working day" is the line that has to land
4. **Practise saying "we have no paying customers yet"** without flinching — it is followed by "and here is the 30-day plan to change that"
