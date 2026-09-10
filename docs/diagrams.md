# Architecture diagrams

Five views of the same system, each answering a different question. All are generated from the actual code — node names, edge names and routing functions match `backend/app/graph/workflow.py` exactly, so a diagram that drifts from the code is a bug in the diagram.

GitHub renders Mermaid natively; these are viewable directly in the browser.

| Diagram | Answers |
|---|---|
| 1. The workflow graph | What are the nodes, and where does a human intervene? |
| 2. Layers and import direction | What may depend on what? |
| 3. Who owns which decision | Where does the model act, and where does code? |
| 4. The retrieval decision | What makes the RAG "agentic"? |
| 5. Pause and resume over HTTP | How does a human gate work mechanically? |

---

## 1. The workflow graph

**One `StateGraph`. Five `interrupt()` points. Four of them are approval gates; the fifth is the clarification question.**

Diamonds are conditional edges — each is a named routing function in `workflow.py`, not an inline lambda. Every model-calling node can fail to `END` rather than raising.

```mermaid
flowchart TD
    START([START]) --> extract

    extract["extract_requirement<br/><i>LLM · free text → typed brief</i>"]
    validate["validate_requirement<br/><i>Python · which fields are missing</i>"]
    ask["ask_clarifying_question<br/>⏸ INTERRUPT 1"]
    update["update_requirement<br/><i>LLM · fill-only merge</i>"]
    review["human_review_requirement<br/>⏸ INTERRUPT 2 · GATE 1"]
    assess["assess_knowledge_need<br/><i>the agentic decision</i>"]
    retrieve["retrieve_production_knowledge<br/><i>FAISS · degrades on failure</i>"]
    method["recommend_production_method<br/><i>LLM + retrieved context</i>"]
    revmethod["human_review_method<br/>⏸ INTERRUPT 3 · GATE 2"]
    search["search_suppliers<br/><i>Python · structural filter</i>"]
    score["calculate_matches<br/><i>Python · 6 weighted factors</i>"]
    select["human_select_supplier<br/>⏸ INTERRUPT 4 · GATE 3"]
    rfq["generate_rfq<br/><i>Python structure + LLM prose</i>"]
    approve["human_review_rfq<br/>⏸ INTERRUPT 5 · GATE 4"]

    extract --> r1{{"route_after_extraction"}}
    r1 -->|ok| validate
    r1 -->|failed| FAIL

    validate --> r2{{"route_after_validation<br/>capped at 3 rounds"}}
    r2 -->|"critical field missing"| ask
    r2 -->|"complete, or budget spent"| review
    r2 -->|failed| FAIL

    ask --> r3{{"route_after_clarification_answer"}}
    r3 -->|"answered"| update
    r3 -->|"customer rewrote the request"| extract
    update --> validate

    review --> assess
    assess --> r4{{"route_after_knowledge_assessment"}}
    r4 -->|"feasibility question"| retrieve
    r4 -->|"routine pairing"| method
    r4 -->|failed| FAIL
    retrieve --> method

    method --> r5{{"route_after_method_recommendation"}}
    r5 -->|ok| revmethod
    r5 -->|failed| FAIL

    revmethod --> search --> score --> select --> rfq --> approve

    approve --> r6{{"route_after_rfq_review"}}
    r6 -->|"approved"| DONE([COMPLETED])
    r6 -->|"declined"| FAIL

    FAIL([FAILED<br/>nothing committed])

    classDef llm fill:#EEF0FE,stroke:#3240EB,stroke-width:2px,color:#191C23
    classDef py fill:#F1F0ED,stroke:#6B6F7A,stroke-width:2px,color:#191C23
    classDef gate fill:#191C23,stroke:#191C23,color:#FFFFFF
    classDef route fill:#FAF9F7,stroke:#C9C9CD,color:#6B6F7A
    classDef terminal fill:#FFFFFF,stroke:#191C23,stroke-width:2px,color:#191C23

    class extract,update,method llm
    class validate,search,score,assess,retrieve,rfq py
    class ask,review,revmethod,select,approve gate
    class r1,r2,r3,r4,r5,r6 route
    class START,DONE,FAIL terminal
```

**Three things this diagram makes visible:**

- **The clarification loop is bounded.** `ask → update → validate` can cycle, but `route_after_validation` stops at three rounds and proceeds to review with the gap visible rather than interrogating forever.
- **A customer can rewrite the original request** instead of answering. `route_after_clarification_answer` sends that back to `extract_requirement` for a fresh extraction, rather than merging an answer that was never given.
- **Failure is a route, not an exception.** Every LLM-calling node returns a `FAILED` delta on error; the graph routes to a controlled stop. The client receives a typed error, never a stack trace.

---

## 2. Layers and import direction

**Import direction is one-way and enforced by `scripts/audit_architecture.py`.** Nothing imports upward. `graph/` never imports `api/`. `services/matching.py` imports no LLM code at all.

```mermaid
flowchart TD
    subgraph FE["frontend/ · Next.js"]
        MKT["app/page.tsx<br/>marketing, own chrome"]
        APP["app/(app)/<br/>the product"]
    end

    subgraph API["app/api/ · HTTP boundary"]
        ROUTES["routes.py · 10 endpoints<br/>only 1 advances the workflow"]
        DTO["dto.py · wire contract"]
    end

    subgraph SVC["app/services/ · deterministic business logic"]
        COMP["completeness.py"]
        MATCH["matching.py<br/><b>zero LLM imports</b>"]
        RECO["recommendations.py"]
        RFQB["rfq_builder.py"]
        PROJ["project_service.py<br/>pause/resume + persistence"]
        OSM["osm_search.py<br/>not a graph tool"]
    end

    subgraph GRAPH["app/graph/ · THE workflow"]
        WF["workflow.py · one StateGraph"]
        NODES["nodes.py · thin nodes"]
        STATE["state.py · ProductionState"]
    end

    subgraph TOOLS["app/tools/"]
        REG["registry.py · typed function tools"]
    end

    subgraph LLM["app/llm/"]
        FACT["factory.py<br/>the only model construction"]
        PROMPT["prompts.py<br/>the only prompt text"]
    end

    subgraph RAG["app/rag/"]
        STORE["store.py · THE vector store"]
        RETR["retriever.py · routing decision"]
    end

    subgraph SEC["app/security/"]
        GUARD["guard.py · layered screening"]
        UP["uploads.py · magic bytes"]
    end

    subgraph DATA["Persistence"]
        APPDB[("app.db<br/>projects · long-term")]
        CKPT[("checkpoints.db<br/>threads · short-term")]
        SUP["suppliers.json · 24"]
        OFF["offers.json · 4 demo"]
        KB["knowledge/ · 13 docs"]
        IDX[("FAISS · 51 chunks")]
    end

    MKT -.->|"CTA"| APP
    APP -->|"server components / actions<br/>browser never calls the API"| ROUTES
    ROUTES --> DTO
    ROUTES --> PROJ
    PROJ --> WF
    PROJ --> APPDB
    WF --> NODES --> STATE
    WF --> CKPT
    NODES --> REG
    NODES --> FACT
    NODES --> PROMPT
    NODES --> GUARD
    NODES --> COMP
    NODES --> RFQB
    REG --> MATCH
    REG --> RECO
    REG --> SUP
    REG --> OFF
    RETR --> STORE --> KB
    RETR --> IDX
    NODES --> RETR
    ROUTES --> OSM
    ROUTES --> UP

    classDef llmbox fill:#EEF0FE,stroke:#3240EB,color:#191C23
    classDef nolm fill:#EAF5EF,stroke:#1E8E5A,stroke-width:2px,color:#191C23
    class FACT,PROMPT llmbox
    class MATCH nolm
```

**Note `osm_search.py` bypasses the graph entirely** — it is called straight from a route. Overpass is a shared public service with no uptime guarantee, and a human-approval gate must never be able to stall on a dependency like that.

---

## 3. Who owns which decision

**The single design decision from which every guarantee follows: the model handles language, code owns every fact and every number.**

```mermaid
flowchart LR
    subgraph MODEL["🗣 LLM — language only"]
        direction TB
        M1["Extract brief from free text"]
        M2["Phrase the clarifying question"]
        M3["Merge the answer<br/><i>fill-only, enforced in code</i>"]
        M4["Reason about production method"]
        M5["Explain a score in prose<br/><i>cannot change it</i>"]
        M6["RFQ intro and closing<br/><i>tone only</i>"]
    end

    subgraph CODE["⚙ Python — every fact and number"]
        direction TB
        C1["Which fields are missing"]
        C2["Which supplier can do the method"]
        C3["The 100-point score"]
        C4["Deadline arithmetic"]
        C5["RFQ document structure"]
        C6["retrieval_used and sources"]
    end

    subgraph GUARANTEE["✅ What this buys, mechanically"]
        direction TB
        G1["A capability cannot be invented<br/><i>tool-only access; unknown ids dropped</i>"]
        G2["A score cannot be argued up<br/><i>zero LLM imports, audit-enforced</i>"]
        G3["No step self-completes<br/><i>interrupt() needs a resume payload</i>"]
        G4["Retrieval cannot be falsely claimed<br/><i>set in code from what was retrieved</i>"]
    end

    MODEL -.->|"output validated by<br/>closed Pydantic schema"| CODE
    CODE ==> GUARANTEE

    classDef m fill:#EEF0FE,stroke:#3240EB,color:#191C23
    classDef c fill:#F1F0ED,stroke:#6B6F7A,color:#191C23
    classDef g fill:#EAF5EF,stroke:#1E8E5A,stroke-width:2px,color:#191C23
    class M1,M2,M3,M4,M5,M6 m
    class C1,C2,C3,C4,C5,C6 c
    class G1,G2,G3,G4 g
```

**Why the dotted arrow matters.** Every model response crosses into code through a closed Pydantic schema (`extra="forbid"`). A hallucinated field is a validation error, not silent data — so even a successful prompt injection cannot produce a field the system acts on.

---

## 4. The retrieval decision — what makes the RAG agentic

**Retrieval does not fire on every request.** A dedicated node decides, cheapest signal first. Two of the three layers cost nothing.

```mermaid
flowchart TD
    Q["Brief confirmed<br/>assess_knowledge_need"] --> L1

    L1{{"Layer 1 — deterministic fast path<br/><b>zero model calls</b>"}}
    L1 -->|"'which suppliers do laser engraving?'<br/>→ supplier lookup"| SKIP
    L1 -->|"'is laser ok on anodised aluminium?'<br/>→ feasibility question"| GO
    L1 -->|"neither pattern matches"| L2

    L2{{"Layer 2 — deterministic rule on the brief<br/><b>zero model calls</b>"}}
    L2 -->|"material unconfirmed →<br/>feasibility cannot be assumed"| GO
    L2 -->|"material known"| L3

    L3{{"Layer 3 — the model decides<br/>1 classifier call"}}
    L3 -->|"needs grounding"| GO
    L3 -->|"routine pairing"| SKIP
    L3 -->|"<b>router itself failed</b>"| GO

    GO["retrieve_production_knowledge<br/>+570 tokens measured<br/>retrieval_used = true"]
    SKIP["recommend_production_method<br/>retrieval_used = false<br/><i>cannot cite sources it never got</i>"]

    GO --> REC["recommend_production_method<br/>with fenced knowledge"]
    SKIP --> REC

    classDef route fill:#FAF9F7,stroke:#C9C9CD,color:#6B6F7A
    classDef go fill:#EEF0FE,stroke:#3240EB,stroke-width:2px,color:#191C23
    classDef skip fill:#F1F0ED,stroke:#6B6F7A,color:#191C23
    class L1,L2,L3 route
    class GO,REC go
    class SKIP skip
```

**It fails toward retrieving, on purpose.** An unnecessary lookup costs about $0.0002. A confident wrong technical claim costs a customer.

**Measured effect of grounding — same request, retrieval off vs on:**

| | Off | On |
|---|---|---|
| Confidence | medium | **high** |
| Constraints | 1, generic | **4**, including the corpus's line-thickness limit |
| Citations | none | **2 named documents** |

---

## 5. Pause and resume over HTTP

**How a human gate actually works.** The graph does not "wait" in memory — it *stops*, persists, and is re-entered later. This is what makes "close the browser and come back tomorrow" work.

```mermaid
sequenceDiagram
    actor U as User
    participant FE as Next.js<br/>(server actions)
    participant API as FastAPI
    participant PS as ProjectService
    participant G as LangGraph
    participant CP as checkpoints.db
    participant DB as app.db

    U->>FE: describes the job in free text
    FE->>API: POST /api/projects
    API->>PS: create(raw_request)
    PS->>DB: save project (stage=draft)
    PS->>G: invoke(initial_state)

    G->>G: extract → validate
    Note over G: brief complete → gate 1
    G->>CP: persist full state
    G--)PS: interrupt payload
    PS->>DB: mirror confirmed facts
    PS--)API: {stage, payload, expected_action}
    API--)FE: brief_review
    FE--)U: renders the brief

    Note over U,G: process may end here.<br/>State lives in checkpoints.db, not memory.

    U->>FE: confirms the brief
    FE->>API: POST /:id/resume {confirm_brief}
    API->>PS: resume(action, data)
    PS->>PS: reject if action ≠ expected_action → 409
    PS->>DB: append project_events (actor='human')
    PS->>G: invoke(Command(resume=payload))
    G->>CP: load state from checkpoint
    G->>G: assess retrieval → recommend method
    G->>CP: persist
    G--)PS: next interrupt
    PS--)API: method_review
    API--)FE: renders recommendation
```

**Two properties worth naming:**

- **The graph is the authority on where it is.** One `/resume` endpoint rather than seven. A mismatched action returns `409` naming the action actually expected — so a stale browser tab gets a correctable answer instead of silently resuming the wrong branch.
- **Every human decision is written to `project_events` with `actor='human'`.** "Who confirmed this method, and when" is answerable after the fact rather than inferred from final state.

---

## Regenerating these

The node and edge names above are copied from `backend/app/graph/workflow.py`. If the graph changes, these diagrams must be updated by hand — there is no generator. To check they still match:

```bash
cd backend && sed -n '/^def build_graph/,/^    return graph/p' app/graph/workflow.py \
  | grep -E "add_node|add_edge|add_conditional"
```
