/**
 * Wire types, mirroring `backend/app/api/dto.py`.
 *
 * These describe the shape of the API, nothing more. There are no business
 * rules here and there must not be: scoring, field requirements and stage
 * transitions all live server-side, and this client only renders what it is
 * told. That is what makes the frontend replaceable.
 */

export type Stage =
  | "draft"
  | "clarifying"
  | "brief_review"
  | "method_review"
  | "supplier_selection"
  | "rfq_review"
  | "completed"
  | "failed";

export type ResumeAction =
  | "answer_clarification"
  | "confirm_brief"
  | "edit_brief"
  | "confirm_method"
  | "select_supplier"
  | "approve_rfq"
  | "edit_rfq";

export type Verdict = "match" | "partial" | "unknown" | "mismatch";

export interface Requirement {
  product: string | null;
  product_category: string | null;
  material: string | null;
  quantity: number | null;
  customer_owns_product: boolean | null;
  customization_description: string | null;
  design_available: boolean | null;
  preferred_finish: string | null;
  deadline: string | null;
  location: string | null;
  priority: string | null;
  additional_constraints: string[];
}

export interface FactorScore {
  factor: string;
  awarded: number;
  max_points: number;
  verdict: Verdict;
  explanation: string;
}

export interface MatchResult {
  supplier_id: string;
  supplier_name: string;
  score: number;
  eligible: boolean;
  exclusion_reason: string | null;
  factors: FactorScore[];
  risk_flags: string[];
  ai_explanation: string | null;
}

export interface KnowledgeCitation {
  title: string;
  source: string | null;
  source_url: string | null;
  updated_at: string | null;
}

export interface MethodRecommendation {
  primary: string;
  alternative: string | null;
  rationale: string;
  constraints: string[];
  artwork_requirements: string[];
  open_questions: string[];
  confidence: "low" | "medium" | "high";
  sources: KnowledgeCitation[];
  retrieval_used: boolean;
}

export interface Rfq {
  supplier_id: string;
  supplier_name: string;
  subject: string;
  product_summary: string;
  quantity: number | null;
  customer_supplies_product: boolean | null;
  customization: string;
  preferred_method: string;
  design_status: string;
  deadline: string | null;
  delivery_location: string | null;
  intro: string;
  confirmations_requested: string[];
  additional_notes: string[];
  closing: string;
  approved: boolean;
}

/**
 * Whatever the paused node published. Which keys are present depends on the
 * stage, which is why this is a union of optionals rather than per-stage types:
 * the server decides, and the shell narrows on `stage`.
 */
export interface StagePayload {
  stage?: Stage;
  question?: string;
  field?: string;
  reason?: string | null;
  requirement?: Requirement;
  field_labels?: Record<string, string>;
  still_unknown?: string[];
  recommendation?: MethodRecommendation;
  selectable_methods?: string[];
  matches?: MatchResult[];
  rfq?: Rfq;
  rendered?: string;
}

export interface ProjectState {
  project_id: string;
  stage: Stage;
  /** From the durable record, so the title is stable across every stage. */
  product: string | null;
  payload: StagePayload | null;
  expected_action: string | null;
  errors: string[];
  is_complete: boolean;
}

export interface ProjectSummary {
  id: string;
  stage: Stage;
  product: string | null;
  quantity: number | null;
  updated_at: string;
}

export interface HealthChecks {
  api_key_configured: boolean;
  suppliers_file_present: boolean;
  supplier_count: number;
  knowledge_dir_present: boolean;
  knowledge_doc_count: number;
  search_index_built: boolean;
  injection_guard_enabled: boolean;
}

export interface Health {
  status: "ok" | "degraded";
  version: string;
  checks: HealthChecks;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    stage: Stage | null;
    recoverable: boolean;
    expected_action?: string | null;
  };
}

/** Human-readable stage names. Presentation only. */
export const STAGE_LABELS: Record<Stage, string> = {
  draft: "Draft",
  clarifying: "Clarification",
  brief_review: "Production brief",
  method_review: "Production method",
  supplier_selection: "Partner matches",
  rfq_review: "Request for quotation",
  completed: "Completed",
  failed: "Needs attention",
};

/** The four gates a project passes through, in order, for the stepper. */
export const WORKFLOW_STAGES: Stage[] = [
  "brief_review",
  "method_review",
  "supplier_selection",
  "rfq_review",
];

export function titleise(value: string): string {
  return value.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}
