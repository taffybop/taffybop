/**
 * Public types shared by the document API client and the UI.
 *
 * The backend intentionally permits additive schema evolution. These types
 * describe its normalized fields while retaining index signatures so a newer
 * parser can add metadata without first requiring a frontend release.
 */

export type ParseOutputFormat = "json" | "markdown";

export type ContentSource = "native" | "ocr" | "mixed" | "derived";

export interface BoundingBox {
  x: number;
  y: number;
  width?: number;
  height?: number;
  /** Backward-compatible aliases currently included by the parser. */
  w?: number;
  h?: number;
  unit?: "pt" | string;
  [key: string]: unknown;
}

export interface NestedContentItem {
  value?: unknown;
  text?: string;
  md?: string;
  bbox?: BoundingBox | null;
  source?: ContentSource | string | null;
  confidence?: number | null;
  level?: number;
  marker?: string;
  word_count?: number;
  [key: string]: unknown;
}

export interface TableCell {
  row: number;
  column: number;
  row_span?: number;
  col_span?: number;
  text?: string;
  column_header?: boolean;
  row_header?: boolean;
  bbox?: BoundingBox | null;
  source?: ContentSource | string | null;
  [key: string]: unknown;
}

export interface DetectedImage {
  page_index?: number;
  object_index?: number;
  bbox?: BoundingBox | null;
  pixel_width?: number | null;
  pixel_height?: number | null;
  area_ratio?: number;
  text?: string;
  ocr_text?: string;
  lines?: NestedContentItem[];
  confidence?: number | null;
  warnings?: string[];
  [key: string]: unknown;
}

export interface LayoutRelationship {
  id: string;
  type: string;
  source_id: string;
  target_id: string;
  [key: string]: unknown;
}

export type OutlineSequenceKind = "unordered" | "ordered" | "legal";

export type OutlineMarkerStyle = "bullet" | "decimal" | "lower_alpha";

export type OutlineMarkerOwnership = "separate" | "value_prefix";

export type OutlineConcernCode =
  | "outline_source_evidence_unavailable"
  | "outline_source_limit"
  | "outline_candidate_limit"
  | "outline_geometry_ambiguous"
  | "outline_marker_ambiguous"
  | "outline_sequence_invalid"
  | "outline_interstitial_ambiguous"
  | "outline_relationship_limit"
  | "outline_canonical_custody_invalid"
  | "outline_projection_failed_closed"
  | "outline_concerns_truncated";

export interface OutlineBoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
  unit: "pt";
}

export interface OutlineConfidence {
  scope: "evidence";
  score: null;
  unavailable_reason:
    | "not_calibrated"
    | "source_state_unavailable";
}

export interface OutlineSourceObject {
  reader: "pdfplumber";
  page_index: number;
  word_index: number;
}

export type OutlinePublicPath = Array<string | number>;

export interface OutlineRelationshipCardinality {
  contains: number;
  outline_parent_of: number;
  outline_next: number;
  outline_continuation_of: number;
}

interface OutlineRelationshipBase {
  id: string;
  source_id: string;
  target_id: string;
  evidence_ids: string[];
  canonical_inert: true;
  outline_group_id: string;
  outline_policy: "p03-outline-structure-v1";
  [key: string]: unknown;
}

export type OutlineRelationship =
  | (OutlineRelationshipBase & {
      type: "contains" | "outline_parent_of";
    })
  | (OutlineRelationshipBase & {
      type: "outline_next";
      intervening_element_ids: string[];
    })
  | (OutlineRelationshipBase & {
      type: "outline_continuation_of";
      interstitial_kind: "table";
    });

export interface OutlineGroup {
  id: string;
  element_id: string;
  page_id: string;
  sequence_kind: OutlineSequenceKind;
  marker_style: OutlineMarkerStyle;
  anchor_public_item_id: string;
  anchor_element_id: string;
  anchor_public_path: OutlinePublicPath;
  group_bbox: OutlineBoundingBox;
  member_item_ids: string[];
  member_element_ids: string[];
  continuation_ids: string[];
  continuation_element_ids: string[];
  relationship_ids: string[];
  relationship_cardinality: OutlineRelationshipCardinality;
  canonical_block_id: string;
  canonical_primary_element_id: string;
  canonical_contributor_element_ids: string[];
  canonical_relationship_ids: string[];
  canonical_markdown_sha256: string;
  canonical_text_sha256: string;
  source_method: "native";
  confidence: OutlineConfidence;
  concern_codes: OutlineConcernCode[];
}

export interface OutlineItem {
  id: string;
  element_id: string;
  source_public_item_id: string;
  source_public_path: OutlinePublicPath;
  source_bbox_id: string;
  source_evidence_ids: string[];
  source_object: OutlineSourceObject;
  sequence_kind: OutlineSequenceKind;
  marker_style: OutlineMarkerStyle;
  raw_marker: string;
  marker_bbox: OutlineBoundingBox;
  marker_ownership: OutlineMarkerOwnership;
  marker_separator: string;
  body_text: string;
  predecessor_value_sha256: string;
  level: number;
  ordinal: number;
  parent_id: string | null;
  marker_bbox_id: string;
  marker_evidence_id: string;
  source_method: "native";
  confidence: OutlineConfidence;
  concern_codes: OutlineConcernCode[];
  relationship_ids: string[];
  continuation_ids: string[];
}

export interface OutlineContinuation {
  id: string;
  element_id: string;
  source_public_item_id: string;
  source_public_path: OutlinePublicPath;
  source_type: "table";
  bbox_id: string;
  bbox: OutlineBoundingBox;
  source_evidence_ids: string[];
  target_node_id: string;
  source_method: "native";
  confidence: OutlineConfidence;
  concern_codes: OutlineConcernCode[];
  relationship_ids: string[];
}

export type FormEvidenceMethod =
  | "native"
  | "vector"
  | "embedded"
  | "recovered"
  | "derived";

export type FormValueState =
  | "empty"
  | "present"
  | "ambiguous"
  | "not_applicable";

export type FormControlState =
  | "checked"
  | "unchecked"
  | "ambiguous"
  | "not_applicable";

export type FormLabelRole = "field" | "group" | "control" | "key";

export interface FormBoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
  unit: "pt";
}

export type FormSourceObject =
  | { kind: "character_range"; start: number; end: number }
  | { kind: "line" | "rect"; index: number }
  | {
      kind: "field" | "widget" | "annotation";
      object_ref_digest: string;
    };

export type FormConfidenceDimension =
  | { score: number }
  | {
      unavailable_reason:
        | "not_calibrated"
        | "not_applicable"
        | "source_state_unavailable"
        | "transcription_not_applicable";
    };

export interface FormConfidenceDimensions {
  geometry: FormConfidenceDimension;
  role: FormConfidenceDimension;
  transcription: FormConfidenceDimension;
  state: FormConfidenceDimension;
}

export interface FormSemanticRecordBase {
  id: string;
  element_id: string;
  page_index: number;
  bbox: FormBoundingBox;
  evidence_methods: FormEvidenceMethod[];
  source_objects: FormSourceObject[];
  confidence_dimensions: FormConfidenceDimensions;
  concern_codes: string[];
  relationship_ids: string[];
}

export interface FormGroup extends FormSemanticRecordBase {
  group_key: string;
  status: "resolved" | "unresolved";
  interactivity: "none" | "static" | "interactive" | "mixed" | "unknown";
  canonical_mode: "inert" | "replace";
  anchor_public_item_id: string;
  anchor_element_id: string;
  anchor_relationship_ids: string[];
  contributor_public_item_ids: string[];
  contributor_element_ids: string[];
  field_ids: string[];
  label_ids: string[];
  value_region_ids: string[];
  control_ids: string[];
  key_value_pair_ids: string[];
}

export interface FormField extends FormSemanticRecordBase {
  group_id: string;
  field_key: string;
  label_ids: string[];
  value_region_id: string;
  control_ids: string[];
  value: string | null;
  value_state: FormValueState;
}

export interface FormLabel extends FormSemanticRecordBase {
  group_id: string;
  label_role: FormLabelRole;
  text: string;
  raw_text: string;
  label_of_ids: string[];
  key_of_ids: string[];
}

export interface FormValueRegion extends FormSemanticRecordBase {
  group_id: string;
  owner_id: string;
  excluded_label_ids: string[];
  value: string | null;
  value_state: FormValueState;
}

export interface FormControl extends FormSemanticRecordBase {
  group_id: string;
  owner_field_id: string | null;
  label_id: string | null;
  control_type: "checkbox" | "radio";
  state: FormControlState;
  origin: "static_vector" | "interactive_widget";
}

export interface FormKeyValuePair extends FormSemanticRecordBase {
  group_id: string;
  pair_key: string;
  key_label_id: string;
  value_region_id: string;
  key: string;
  value: string;
  value_state: "present";
  key_source_item_id: string;
  value_source_item_id: string;
}

export interface FormRelationship extends LayoutRelationship {
  type:
    | "contains"
    | "label_of"
    | "value_of"
    | "control_of"
    | "key_of"
    | "form_overlay_of";
  evidence_ids: string[];
  canonical_inert: true;
}

export type TextRunTargetPath =
  | ["value"]
  | ["cells", number, "text"]
  | ["items", number, "value" | "text"];

export interface TextRunBoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
  unit: "pt";
}

export interface TextRunColor {
  space: "gray" | "rgb" | "cmyk" | "unknown";
  components: number[];
}

export type TextRunChangeState =
  | "deleted"
  | "inserted"
  | "replacement"
  | "unknown"
  | "unchanged";

export type TextRunDecoration = "strikethrough" | "underline";

export interface TextRun {
  id: string;
  element_id: string;
  target_path: TextRunTargetPath;
  text: string;
  source_text: string;
  start: number;
  end: number;
  bbox: TextRunBoundingBox;
  font_name: string;
  font_size: number;
  bold: boolean;
  italic: boolean;
  color: TextRunColor;
  change_state: TextRunChangeState;
  decorations: TextRunDecoration[];
  placeholder: boolean;
  rule_ids: string[];
  evidence_method: string;
  semantic_derivation: string;
  extraction_policy_id: string;
  association_policy_id: string;
  change_group_id?: string;
}

export interface TextRule {
  id: string;
  bbox: TextRunBoundingBox;
  source_object_kind: "line" | "rect";
  source_object_index: number;
  color: TextRunColor;
  width: number;
  thickness: number;
  evidence_method: "vector";
  extraction_policy_id: string;
}

export type NoteItemType = "source_note" | "footnote";

export type NoteRelationshipType = "source_note_of" | "footnote_of";

/**
 * A source-visible or PDF-annotation-grounded link retained as evidence.
 *
 * Consumers must treat `target` as data unless they independently validate it
 * for an interactive use. The parsed-content renderer deliberately displays
 * note text only and never turns this descriptor into an anchor.
 */
export interface SourceGroundedLink {
  kind: string;
  target: string;
  [key: string]: unknown;
}

/**
 * Source-visible text retained inside a visual owner.
 *
 * Contained visual text is relationship evidence, not document prose. It is
 * therefore intentionally separate from `items`, which continues to describe
 * OCR line diagnostics used by older responses.
 */
export interface ContainedVisualItem {
  id: string;
  type: "visual_text";
  value: unknown;
  bbox: BoundingBox;
  source: ContentSource | string | null;
  confidence: number | null;
  presentation_role: "subordinate";
  contained_by: string;
  relationship_id: string;
  relationship_type: "contains";
  relationship_basis: string;
  [key: string]: unknown;
}

export interface VisualBoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
  unit: "pt" | "px";
}

export interface VisualConfidenceDimensions {
  geometry?: number | null;
  calibration?: number | null;
  category?: number | null;
  series?: number | null;
  value?: number | null;
  direction?: number | null;
}

export type VisualLabelRole =
  | "title"
  | "caption"
  | "axis_title"
  | "tick"
  | "category"
  | "unit"
  | "legend"
  | "node"
  | "node_detail"
  | "connector"
  | "other";

export interface VisualLabel {
  id: string;
  text: string;
  role: VisualLabelRole;
  page_bbox?: VisualBoundingBox | null;
  raster_pixel_bbox?: VisualBoundingBox | null;
  evidence_ids: string[];
  occurrence_index: number;
}

export interface DiagramNode {
  id: string;
  shape: "rectangle" | "rounded_rectangle" | "ellipse" | "diamond";
  label_id?: string | null;
  detail_label_ids?: string[];
  page_bbox: VisualBoundingBox;
  evidence_ids: string[];
  confidence: VisualConfidenceDimensions;
}

export interface DiagramConnector {
  id: string;
  source_node_id: string;
  target_node_id: string;
  directed: true;
  label_id?: string | null;
  path_evidence_id: string;
  endpoint_evidence_ids: [string, string];
  direction_evidence_id: string;
  evidence_ids: string[];
  confidence: VisualConfidenceDimensions;
}

export interface VisualSerialization {
  status: "fallback" | "structured_chart" | "diagram_topology";
  markdown: string;
  caption_occurrences: number;
  row_count: number;
}

export interface VisualStructure {
  schema_version: "1.0";
  region: {
    id: string;
    kind: "chart" | "diagram";
    page_bbox: VisualBoundingBox;
    evidence_ids: string[];
  };
  transforms: unknown[];
  labels: VisualLabel[];
  axes: unknown[];
  legends: unknown[];
  panels: unknown[];
  series: unknown[];
  points: unknown[];
  nodes: DiagramNode[];
  connectors: DiagramConnector[];
  evidence: unknown[];
  vector_inventory?: unknown | null;
  confidence: VisualConfidenceDimensions;
  concerns: unknown[];
  fallback: {
    active: boolean;
    reason: string;
    predecessor_concern: string;
  };
  serialization: VisualSerialization | null;
}

/**
 * A normalized item in page reading order.
 *
 * Common `type` values are heading, text, list, table, image, header, footer,
 * code, and formula. Type-specific fields remain optional because not every
 * extraction engine can populate every representation.
 */
export interface DocumentContentItem {
  id: string;
  type: string;
  reading_order: number;
  value?: unknown;
  md?: string | null;
  bbox?: BoundingBox | null;
  source?: ContentSource | string | null;
  confidence?: number | null;
  label?: string;

  level?: number;
  language?: string;
  ordered?: boolean;
  items?: NestedContentItem[];

  rows?: string[][];
  cells?: TableCell[];
  row_bboxes?: BoundingBox[];
  row_count?: number;
  column_count?: number;
  html?: string;
  csv?: string;
  parse_concerns?: string[];
  engine?: string;
  embedded_images?: DetectedImage[];

  ocr_text?: string;
  include_ocr_in_primary?: boolean;
  layout_visual_relationships_projected?: boolean;
  layout_source_notes_projected?: boolean;
  detected_text?: boolean;
  pixel_width?: number | null;
  pixel_height?: number | null;
  area_ratio?: number;
  warnings?: string[];
  /** Source-grounded Phase 03 layout relationships. */
  caption_of?: string | string[];
  caption_ids?: string[];
  source_note_of?: string;
  footnote_of?: string;
  source_note_ids?: string[];
  footnote_ids?: string[];
  links?: SourceGroundedLink[];
  contains_ids?: string[];
  contained_items?: ContainedVisualItem[];
  /** Closed Phase 05 chart/diagram evidence and serialization sidecar. */
  visual_structure?: VisualStructure;
  relationships?: LayoutRelationship[];
  relationship_id?: string;
  relationship_type?: string;
  relationship_basis?: string;
  /** Source-grounded sparse text-run semantics (P03-US05). */
  text_run_policy?: "p03-text-run-semantics-v1";
  text_runs?: TextRun[];
  text_rules?: TextRule[];
  redline_markdown?: string;
  active_text?: string;
  active_text_omitted_run_ids?: string[];
  active_text_policy?: "omit-proven-deletions-v1";
  /** Strict additive form/key-value semantics (P03-US06). */
  layout_forms_projected?: true;
  form_policy?: "p03-form-semantics-v1";
  form_group?: FormGroup;
  form_fields?: FormField[];
  form_labels?: FormLabel[];
  form_value_regions?: FormValueRegion[];
  form_controls?: FormControl[];
  form_key_value_pairs?: FormKeyValuePair[];
  /** Strict additive list/legal-clause hierarchy (P03-US07). */
  layout_outline_structure_projected?: true;
  outline_policy?: "p03-outline-structure-v1";
  outline_group?: OutlineGroup;
  outline_items?: OutlineItem[];
  outline_continuations?: OutlineContinuation[];
  /** Strict additive running-region projection (P03-US08). */
  layout_running_region_projected?: true;
  running_region_policy?: "p03-running-regions-page-identity-v1";
  running_region?: RunningRegionDescriptor;
  [key: string]: unknown;
}

export interface PageResult {
  page_index: number;
  page_number: number | string;
  page_label: string;
  page_width: number;
  page_height: number;
  unit: "pt" | string;
  success: boolean;
  items: DocumentContentItem[];
  detected_images?: DetectedImage[];
  warnings: string[];
  /** Present only for a committed P03-US08 projection. */
  page_identity?: PageIdentity;
  [key: string]: unknown;
}

export interface DocumentMetadata {
  filename: string;
  mime_type: string;
  sha256: string;
  page_count: number;
  image_count?: number;
  [key: string]: unknown;
}

export interface ProcessingMetadata {
  engine: string;
  ocr_engine: string;
  ocr_languages: string[];
  duration_ms: number;
  native_text_engine?: string;
  table_engines?: string[];
  local_processing?: boolean;
  running_regions?: RunningRegionsProcessingSummary;
  [key: string]: unknown;
}

export type PagePresentationView = "body" | "full";

export type RunningRegionRole =
  | "header"
  | "footer"
  | "navigation_top"
  | "navigation_bottom";

export type RunningRegionCanonicalScope = "header" | "footer";

export type RunningRegionSourceMethod =
  | "trusted_layout_role"
  | "cross_page_repetition"
  | "boundary_navigation"
  | "printed_label_boundary"
  | "effective_boundary_cluster"
  | "extracted_source_contribution";

export type RunningRegionConcernCode =
  | "running_region_source_evidence_unavailable"
  | "running_region_source_limit"
  | "running_region_candidate_limit"
  | "running_region_geometry_ambiguous"
  | "running_region_repetition_ambiguous"
  | "running_region_navigation_ambiguous"
  | "running_region_ownership_conflict"
  | "page_identity_embedded_label_invalid"
  | "page_identity_detected_label_ambiguous"
  | "page_identity_source_conflict"
  | "page_identity_display_unsafe"
  | "running_region_canonical_custody_invalid"
  | "running_region_projection_failed_closed"
  | "running_region_concerns_truncated";

export interface RunningRegionBoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
  unit: "pt";
}

export type RunningRegionConfidence =
  | {
      scope: "deterministic_rule" | "source_metadata";
      score: number;
      unavailable_reason: null;
    }
  | {
      scope: "unavailable";
      score: null;
      unavailable_reason:
        | "page_identity_source_unavailable"
        | "page_identity_display_fallback_physical";
    };

export interface PageIdentityEvidenceSource {
  method:
    | "native_printed_label"
    | "embedded_pdf_label"
    | "legacy_display_fallback"
    | "physical_page_index";
  reader: "pdfplumber" | "pypdfium2" | "configured_predecessor";
  page_index: number;
  public_item_id: string | null;
  public_path: Array<string | number>;
  element_id: string | null;
  bbox_id: string | null;
  evidence_ids: string[];
  source_object_ids: string[];
}

export interface PageIdentity {
  schema_version: "1.0";
  policy_id: "p03-running-regions-page-identity-v1";
  page_id: string;
  physical_page_index: number;
  embedded_label: string | null;
  detected_printed_label: string | null;
  visible_text: string | null;
  display_label: string;
  display_source:
    | "detected_printed_label"
    | "embedded_label"
    | "legacy_display_fallback"
    | "physical";
  evidence_bbox: RunningRegionBoundingBox | null;
  evidence_source: PageIdentityEvidenceSource;
  confidence: RunningRegionConfidence;
  concern_codes: RunningRegionConcernCode[];
}

export interface RunningRegionDescriptor {
  id: string;
  page_id: string;
  physical_page_index: number;
  role: RunningRegionRole;
  canonical_scope: RunningRegionCanonicalScope;
  source_public_item_id: string;
  source_public_path: Array<string | number>;
  source_element_id: string;
  predecessor_type: string;
  predecessor_item_sha256: string;
  bbox_id: string;
  bbox: RunningRegionBoundingBox;
  evidence_ids: string[];
  source_object_ids: string[];
  source_method: RunningRegionSourceMethod;
  repetition_group_id: string | null;
  repetition_page_indexes: number[];
  confidence: RunningRegionConfidence;
  concern_codes: RunningRegionConcernCode[];
  canonical_block_id: string;
}

export type RunningRegionsProcessingStatus =
  | "projected"
  | "unavailable"
  | "not_applicable"
  | "failed_closed";

export interface RunningRegionsProcessingSummary {
  policy_id: "p03-running-regions-page-identity-v1";
  status: RunningRegionsProcessingStatus;
  reason:
    | "running_region_source_evidence_unavailable"
    | "running_region_source_limit"
    | "running_region_input_not_applicable"
    | "running_region_projection_failed_closed"
    | null;
  source_page_count: number;
  identity_count: number;
  detected_label_count: number;
  embedded_label_count: number;
  legacy_fallback_count: number;
  candidate_count: number;
  comparison_count: number;
  running_region_count: number;
  header_count: number;
  footer_count: number;
  top_navigation_count: number;
  bottom_navigation_count: number;
  concern_count: number;
  extraction_ms: number;
  projection_ms: number;
  total_ms: number;
}

export interface RunningRegionConcern {
  code: RunningRegionConcernCode;
  source_ref: "document" | `page:${number}`;
  count: number;
  cap: number;
  exception_class: string | null;
}

export interface RunningRegionNonProjectingConcern {
  code: RunningRegionConcernCode;
}

export type CanonicalBlockScope = "body" | "header" | "footer";

export type CanonicalExclusionReason =
  | "already_claimed"
  | "alternate_representation"
  | "caption_precedes_subordinate_ocr"
  | "empty_contribution"
  | "evidence_only_relationship"
  | "overlapping_visual_table"
  | "rejected_caption"
  | "rejected_ocr"
  | "unapproved_caption"
  | "unapproved_ocr";

export type CanonicalOmissionReason =
  | "alternate_representation"
  | "consumed_by_relationship"
  | "empty_content"
  | "empty_visual"
  | "overlapping_visual_table"
  | "source_contradicted_primary_ocr"
  | "unsupported_primary_ocr";

export interface CanonicalExcludedContribution {
  element_id: string;
  reason: CanonicalExclusionReason;
  relationship_ids: string[];
}

export interface CanonicalBlock {
  id: string;
  page_id: string;
  primary_element_id: string;
  primary_element_type: string;
  scope: CanonicalBlockScope;
  markdown: string;
  text: string;
  contributing_element_ids: string[];
  relationship_ids: string[];
  excluded_contributions: CanonicalExcludedContribution[];
  omission_reason?: CanonicalOmissionReason | null;
  suppressed_by_element_id?: string | null;
}

export interface CanonicalView {
  block_ids: string[];
  markdown: string;
  text: string;
}

export interface CanonicalPage {
  page_id: string;
  page_index: number;
  page_number: number | string;
  page_label: string;
  blocks: CanonicalBlock[];
  full: CanonicalView;
  body: CanonicalView;
  header: CanonicalView;
  footer: CanonicalView;
  /** Recursively equal to the public page identity when P03-US08 projected. */
  page_identity?: PageIdentity;
}

export interface CanonicalPresentation {
  schema_version: "1.0";
  source_ir_version: "1.0";
  policy_id: "canonical-presentation-v1";
  pages: CanonicalPage[];
  full: CanonicalView;
  body: CanonicalView;
  header: CanonicalView;
  footer: CanonicalView;
}

export interface ParseResult {
  schema_version: string;
  document: DocumentMetadata;
  pages: PageResult[];
  processing: ProcessingMetadata;
  warnings: string[];
  canonical_presentation?: CanonicalPresentation;
  running_region_concerns?: Array<
    RunningRegionConcern | RunningRegionNonProjectingConcern
  >;
  [key: string]: unknown;
}

export interface ApiErrorPayload {
  code: string;
  message: string;
  details: Record<string, unknown>;
  [key: string]: unknown;
}

export interface ApiErrorResponse {
  error: ApiErrorPayload;
  [key: string]: unknown;
}

export type ParseResponseFor<Format extends ParseOutputFormat> =
  Format extends "json" ? ParseResult : string;

export type DocumentApiErrorKind =
  | "validation"
  | "timeout"
  | "network"
  | "server"
  | "empty"
  | "cancelled"
  | "configuration";

export interface SerializedOutput {
  content: string;
  contentType: "application/json" | "text/markdown";
  extension: "json" | "md";
}
