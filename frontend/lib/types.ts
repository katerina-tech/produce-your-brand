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
  | "restart_request"
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
  budget_eur: number | null;
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

/** A supplier's demonstrated history: ratings and completed orders.
 *
 * Shown next to the score and deliberately not inside it. A rating resting on
 * three reviews must not be able to reorder a ranking whose whole claim is that
 * six stated capability factors explain it - so the server attaches this after
 * scoring and the client renders it as separate evidence.
 *
 * Every field is nullable because "no history yet" is a real state for a new
 * partner and has to read as information, never as a bad score. */
export interface TrackRecord {
  supplier_id: string;
  average_rating: number | null;
  rating_count: number;
  completed_orders: number;
  last_completed_on: string | null;
  is_demo: boolean;
  source: string | null;
  last_updated: string | null;
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
  track_record: TrackRecord | null;
}

/** One supplier, framed for one specific buyer question ("cheapest?",
 * "fastest?"). Absent - not filled with a guess - when the data behind it
 * doesn't exist; see backend/app/services/recommendations.py. */
export interface RecommendationPerspective {
  supplier_id: string;
  supplier_name: string;
  headline: string;
  detail: string | null;
  offer_id: string | null;
  is_demo: boolean;
}

export interface RecommendationPerspectives {
  best_match: RecommendationPerspective | null;
  best_price: RecommendationPerspective | null;
  fastest: RecommendationPerspective | null;
}

/** The product-validation instrumentation - see FeedbackSurvey.tsx and the
 * README's Product hypothesis section. */
export type FoundUseful = "yes" | "partly" | "no";
export type AlternativeApproach =
  | "google"
  | "chatgpt"
  | "existing_platform"
  | "known_supplier"
  | "other";

export interface FeedbackRequest {
  found_useful: FoundUseful;
  would_contact_supplier: boolean;
  alternative_approach: AlternativeApproach;
  missing?: string;
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
  /** The original free-text description, offered back for editing - see
   * ClarifyPrompt's "edit the original request instead" path. */
  raw_request?: string;
  requirement?: Requirement;
  field_labels?: Record<string, string>;
  still_unknown?: string[];
  recommendation?: MethodRecommendation;
  selectable_methods?: string[];
  matches?: MatchResult[];
  /** How many partners structurally could do the job, before scoring. */
  candidate_count?: number;
  perspectives?: RecommendationPerspectives | null;
  rfq?: Rfq;
  rendered?: string;
}

export interface ProjectState {
  project_id: string;
  stage: Stage;
  /** From the durable record, so the title is stable across every stage. */
  product: string | null;
  /** Id of an uploaded or generated design, if one is attached. */
  design_upload_id: string | null;
  payload: StagePayload | null;
  expected_action: string | null;
  errors: string[];
  is_complete: boolean;
  /** Whether this project belongs to you. False means unowned, never somebody
   *  else's - a project with a different owner answers 404. */
  mine: boolean;
}

/** Metadata for a stored design file. The body is never returned here. */
export interface UploadResponse {
  upload_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
}

/**
 * An {@link UploadResponse} plus a one-time preview of what was generated.
 *
 * `preview_data_url` is returned exactly once, by the generate call itself -
 * the only moment the user can see what they just paid to generate. Nothing
 * else (including reloading the project later) returns it again.
 */
export interface GeneratedDesign extends UploadResponse {
  preview_data_url: string;
}

/**
 * A real, unscored OpenStreetMap lead - deliberately not a {@link MatchResult}.
 * OpenStreetMap has no capability, MOQ or lead-time data, so these are never
 * ranked or compared the way a scored supplier match is.
 */
export interface NearbyStudio {
  osm_id: string;
  name: string;
  osm_category: string;
  address: string | null;
  website: string | null;
  phone: string | null;
  /** Published by the business to OpenStreetMap, where it published one. */
  email: string | null;
  lat: number;
  lon: number;
}

export interface NearbyStudiosResponse {
  studios: NearbyStudio[];
  source: "openstreetmap";
  note: string;
}

export interface FieldEvidenceItem {
  field: string;
  quote: string;
}

export interface Quote {
  id: string;
  supplier_name: string;
  feasible: boolean | null;
  proposed_method: string | null;
  unit_price_eur: number | null;
  total_price_eur: number | null;
  setup_cost_eur: number | null;
  quoted_quantity: number | null;
  price_basis: "net" | "gross" | "unstated";
  price_is_estimate: boolean | null;
  currency: string | null;
  lead_time_days: number | null;
  sample_available: boolean | null;
  accepts_customer_owned_goods: boolean | null;
  open_questions: string[];
  evidence: FieldEvidenceItem[];
  /** Figures the verifier deleted because their words were not in the reply. */
  unverified_fields: string[];
  corrected_fields: string[];
  source_text: string;
  received_on: string;
  confirmed_by_human: boolean;
  needs_manual_entry: boolean;
}

export interface ComparisonRow {
  quote_id: string;
  supplier_name: string;
  comparable_total_eur: number | null;
  total_basis: "net" | "gross" | "unstated";
  lead_time_days: number | null;
  answered_count: number;
  unanswered: string[];
  /** Why this row carries no total. Never empty when the total is null. */
  blockers: string[];
}

export interface QuoteFollowUp {
  supplier_name: string;
  subject: string;
  questions: string[];
  asks: string[];
}

export interface QuoteDesk {
  quotes: Quote[];
  rows: ComparisonRow[];
  requested_quantity: number | null;
  cheapest_quote_id: string | null;
  fastest_quote_id: string | null;
  unanswered_by_everyone: string[];
  note: string;
  followups: QuoteFollowUp[];
}

export interface Outreach {
  supplier_name: string;
  /** Always empty: the backend stores no supplier addresses. */
  to: string;
  subject: string;
  body: string;
  gmail_url: string;
  mailto_url: string;
  fits_in_a_url: boolean;
  /** The address belongs to a sample partner and cannot receive mail. */
  address_is_sample: boolean;
}

export interface ProjectSummary {
  id: string;
  stage: Stage;
  product: string | null;
  quantity: number | null;
  updated_at: string;
  /** Yours, as opposed to unowned. A project belonging to somebody else is
   *  never in this list at all, so there is no third case to render. */
  mine: boolean;
}

export interface HealthChecks {
  api_key_configured: boolean;
  /** Whether this deployment can issue sessions. False means sign-in is off
   *  and everything else works exactly as it did before accounts existed. */
  sign_in_configured: boolean;
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
