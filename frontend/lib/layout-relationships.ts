import type {
  CanonicalBlock,
  CanonicalPage,
  DocumentContentItem,
  LayoutRelationship,
  NoteItemType,
  NoteRelationshipType,
  PageResult,
} from "./types.ts";
import { primaryItemText } from "./primary-item-text.ts";

export interface CanonicalCaptionLink {
  caption: DocumentContentItem;
  owner: DocumentContentItem;
  relationship: LayoutRelationship;
}

interface PageCaptionGraph {
  itemsById: Map<string, DocumentContentItem>;
  relationshipClaims: Map<string, string>;
  relationshipsById: Map<string, PageRelationshipRecord>;
}

export interface CanonicalNoteLink {
  note: DocumentContentItem;
  owner: DocumentContentItem;
  relationship: LayoutRelationship;
  noteType: NoteItemType;
  relationshipType: NoteRelationshipType;
}

interface NoteContract {
  noteType: NoteItemType;
  relationshipType: NoteRelationshipType;
  ownerField: "source_note_of" | "footnote_of";
  ownerBacklinkField: "source_note_ids" | "footnote_ids";
  conflictingOwnerField: "source_note_of" | "footnote_of";
}

interface PageRelationshipRecord {
  declaringItemId: string;
  relationship: LayoutRelationship;
}

const NOTE_CONTRACTS: Record<NoteItemType, NoteContract> = {
  source_note: {
    noteType: "source_note",
    relationshipType: "source_note_of",
    ownerField: "source_note_of",
    ownerBacklinkField: "source_note_ids",
    conflictingOwnerField: "footnote_of",
  },
  footnote: {
    noteType: "footnote",
    relationshipType: "footnote_of",
    ownerField: "footnote_of",
    ownerBacklinkField: "footnote_ids",
    conflictingOwnerField: "source_note_of",
  },
};

const NOTE_OWNER_TYPES = new Set(["table", "chart", "diagram", "image"]);
const MAX_TABLE_CANDIDATE_ROWS = 4_096;
const MAX_TABLE_CANDIDATE_COLUMNS = 256;
const MAX_TABLE_CANDIDATE_CELLS = 65_536;
const MAX_CAPTIONED_TABLE_COMPOSITE_CODE_UNITS = 16 * 1024 * 1024;

function tableItemText(item: DocumentContentItem): string {
  if (!Array.isArray(item.rows)) return "";
  return item.rows
    .map((row) => row.join("\t").replace(/\t+$/u, ""))
    .join("\n")
    .trim();
}

function boundedCompositePart(value: unknown): string | null {
  return typeof value === "string" &&
    value.length > 0 &&
    value.length <= MAX_CAPTIONED_TABLE_COMPOSITE_CODE_UNITS
    ? value
    : null;
}

function captionItemMarkdown(item: DocumentContentItem): string | null {
  const markdown = boundedCompositePart(item.md);
  return markdown ?? boundedCompositePart(primaryItemText(item));
}

function matchesCaptionedTableComposite(
  block: CanonicalBlock,
  caption: DocumentContentItem,
  owner: DocumentContentItem,
): boolean {
  const captionText = boundedCompositePart(primaryItemText(caption));
  const ownerText = boundedCompositePart(tableItemText(owner));
  const captionMarkdown = captionItemMarkdown(caption);
  const ownerMarkdown = boundedCompositePart(owner.md);
  if (!captionText || !ownerText || !captionMarkdown || !ownerMarkdown) {
    return false;
  }
  const textComposite = `${captionText}\n\n${ownerText}`;
  const markdownComposite = `${captionMarkdown}\n\n${ownerMarkdown}`;
  return (
    textComposite.length <= MAX_CAPTIONED_TABLE_COMPOSITE_CODE_UNITS &&
    markdownComposite.length <= MAX_CAPTIONED_TABLE_COMPOSITE_CODE_UNITS &&
    block.text === textComposite &&
    block.markdown === markdownComposite
  );
}

export function isEligibleUnresolvedTableCandidate(
  item: DocumentContentItem,
): boolean {
  if (item.type.toLowerCase() !== "table_candidate") return false;

  const gate =
    typeof item.table_candidate_gate === "object" &&
    item.table_candidate_gate !== null &&
    !Array.isArray(item.table_candidate_gate)
      ? (item.table_candidate_gate as Record<string, unknown>)
      : null;
  const featureScores =
    typeof gate?.feature_scores === "object" &&
    gate.feature_scores !== null &&
    !Array.isArray(gate.feature_scores)
      ? (gate.feature_scores as Record<string, unknown>)
      : null;
  const tableSupport = featureScores?.table_support;
  const cellCoverage = featureScores?.cell_coverage;
  const reasons = item.table_candidate_gate_reasons;
  const gateSources = item.table_candidate_gate_sources;
  const ownerIds = gate?.owner_item_ids;
  const rows = item.rows;
  const rowCount = item.row_count;
  const columnCount = item.column_count;
  if (
    gate?.outcome !== "unresolved" ||
    !Array.isArray(ownerIds) ||
    ownerIds.length !== 0 ||
    !Array.isArray(reasons) ||
    reasons.length !== 1 ||
    reasons[0] !== "upstream_reconciliation_unresolved" ||
    !Array.isArray(gateSources) ||
    gateSources.length !== 0 ||
    typeof tableSupport !== "number" ||
    !Number.isFinite(tableSupport) ||
    tableSupport < 0.62 ||
    tableSupport > 1 ||
    typeof cellCoverage !== "number" ||
    !Number.isFinite(cellCoverage) ||
    cellCoverage < 0.75 ||
    cellCoverage > 1 ||
    !Array.isArray(rows) ||
    typeof rowCount !== "number" ||
    !Number.isInteger(rowCount) ||
    rowCount !== rows.length ||
    rowCount < 2 ||
    rowCount > MAX_TABLE_CANDIDATE_ROWS ||
    typeof columnCount !== "number" ||
    !Number.isInteger(columnCount) ||
    columnCount < 2 ||
    columnCount > MAX_TABLE_CANDIDATE_COLUMNS ||
    rowCount * columnCount > MAX_TABLE_CANDIDATE_CELLS ||
    !rows.every(
      (row) =>
        Array.isArray(row) &&
        row.length === columnCount &&
        row.every((cell) => typeof cell === "string"),
    )
  ) {
    return false;
  }
  return true;
}

function isCanonicalNoteOwner(item: DocumentContentItem): boolean {
  if (NOTE_OWNER_TYPES.has(item.type.toLowerCase())) return true;
  return isEligibleUnresolvedTableCandidate(item);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function readStrictPageCaptionGraph(page: PageResult): PageCaptionGraph | null {
  const itemsById = new Map<string, DocumentContentItem>();
  const relationshipClaims = new Map<string, string>();
  const relationshipsById = new Map<string, PageRelationshipRecord>();
  for (const item of page.items) {
    if (
      item === null ||
      typeof item !== "object" ||
      !isNonEmptyString(item.id) ||
      !isNonEmptyString(item.type) ||
      itemsById.has(item.id)
    ) {
      return null;
    }
    itemsById.set(item.id, item);

    if (item.relationship_id !== undefined) {
      if (
        !isNonEmptyString(item.relationship_id) ||
        relationshipClaims.has(item.relationship_id)
      ) {
        return null;
      }
      relationshipClaims.set(item.relationship_id, item.id);
    }

    if (item.caption_ids !== undefined) {
      if (
        !Array.isArray(item.caption_ids) ||
        item.caption_ids.some((id) => !isNonEmptyString(id)) ||
        new Set(item.caption_ids).size !== item.caption_ids.length
      ) {
        return null;
      }
    }
    if (
      item.relationships !== undefined &&
      !Array.isArray(item.relationships)
    ) {
      return null;
    }
    for (const relationship of item.relationships ?? []) {
      if (
        relationship === null ||
        typeof relationship !== "object" ||
        !isNonEmptyString(relationship.id) ||
        !isNonEmptyString(relationship.type) ||
        !isNonEmptyString(relationship.source_id) ||
        !isNonEmptyString(relationship.target_id) ||
        relationshipsById.has(relationship.id)
      ) {
        return null;
      }
      relationshipsById.set(relationship.id, {
        declaringItemId: item.id,
        relationship,
      });
    }
  }
  return { itemsById, relationshipClaims, relationshipsById };
}

/**
 * Resolve a caption that canonical custody consumed into a table owner block.
 *
 * The canonical block and public item IDs intentionally occupy different ID
 * domains. The consumed-block audit plus the unique public caption_of graph is
 * the only accepted bridge. Any competing claim, descriptor, backlink, or
 * consumed caption fails closed so canonical text remains the fallback.
 */
export function resolveCanonicalCaptionedTableLink(
  block: CanonicalBlock,
  canonicalPage: CanonicalPage,
  page: PageResult,
): CanonicalCaptionLink | null {
  const blockType = block.primary_element_type.toLowerCase();
  if (
    (blockType !== "table" && blockType !== "table_candidate") ||
    block.omission_reason != null ||
    !Array.isArray(block.relationship_ids) ||
    block.relationship_ids.some((id) => !isNonEmptyString(id)) ||
    new Set(block.relationship_ids).size !== block.relationship_ids.length
  ) {
    return null;
  }

  const consumedCaptionBlocks = canonicalPage.blocks.filter(
    (candidate) =>
      candidate.primary_element_type.toLowerCase() === "caption" &&
      candidate.omission_reason === "consumed_by_relationship" &&
      candidate.suppressed_by_element_id === block.primary_element_id,
  );
  if (consumedCaptionBlocks.length !== 1) return null;
  const consumedCaptionBlock = consumedCaptionBlocks[0];
  if (
    block.contributing_element_ids.filter(
      (id) => id === consumedCaptionBlock.primary_element_id,
    ).length !== 1 ||
    !Array.isArray(consumedCaptionBlock.relationship_ids) ||
    consumedCaptionBlock.relationship_ids.some((id) => !isNonEmptyString(id)) ||
    new Set(consumedCaptionBlock.relationship_ids).size !==
      consumedCaptionBlock.relationship_ids.length
  ) {
    return null;
  }

  const assertingRelationshipIds = new Set(
    consumedCaptionBlock.excluded_contributions
      .filter(
        (exclusion) =>
          exclusion.element_id === block.primary_element_id &&
          exclusion.reason === "already_claimed",
      )
      .flatMap((exclusion) => exclusion.relationship_ids),
  );
  const bridgeIds = consumedCaptionBlock.relationship_ids.filter(
    (id) =>
      block.relationship_ids.includes(id) && assertingRelationshipIds.has(id),
  );
  if (bridgeIds.length !== 1) return null;

  const graph = readStrictPageCaptionGraph(page);
  if (!graph) return null;
  const links: CanonicalCaptionLink[] = [];
  for (const caption of page.items) {
    if (
      caption.type.toLowerCase() !== "caption" ||
      !isNonEmptyString(caption.relationship_id) ||
      caption.relationship_type !== "caption_of" ||
      !isNonEmptyString(caption.caption_of)
    ) {
      continue;
    }
    const owner = graph.itemsById.get(caption.caption_of);
    const relationshipRecord = graph.relationshipsById.get(
      caption.relationship_id,
    );
    if (
      !owner ||
      owner.type.toLowerCase() !== blockType ||
      (blockType === "table_candidate" &&
        !isEligibleUnresolvedTableCandidate(owner)) ||
      graph.relationshipClaims.get(caption.relationship_id) !== caption.id ||
      !relationshipRecord ||
      relationshipRecord.declaringItemId !== owner.id ||
      !matchesCaptionedTableComposite(block, caption, owner)
    ) {
      continue;
    }
    const pageBacklinkCount = page.items.reduce(
      (count, item) =>
        count +
        (item.caption_ids ?? []).filter((id) => id === caption.id).length,
      0,
    );
    const relationship = relationshipRecord.relationship;
    if (
      !Array.isArray(owner.caption_ids) ||
      owner.caption_ids.filter((id) => id === caption.id).length !== 1 ||
      pageBacklinkCount !== 1 ||
      relationship.type !== "caption_of" ||
      relationship.source_id !== caption.id ||
      relationship.target_id !== owner.id
    ) {
      continue;
    }
    links.push({ caption, owner, relationship });
  }
  return links.length === 1 ? links[0] : null;
}

/**
 * Resolve a canonical caption through its public relationship assertion.
 *
 * Canonical primary element IDs belong to the internal IR and intentionally
 * differ from public compatibility item IDs. The retained relationship ID and
 * its typed public endpoints are the contract-defined bridge between them.
 * Missing, duplicate, or inconsistent endpoints fail closed.
 */
export function resolveCanonicalCaptionLink(
  block: CanonicalBlock,
  page: PageResult,
): CanonicalCaptionLink | null {
  if (block.primary_element_type.toLowerCase() !== "caption") return null;
  if (!Array.isArray(block.relationship_ids)) return null;

  const itemsById = new Map<string, DocumentContentItem>();
  const pageRelationships: LayoutRelationship[] = [];
  for (const item of page.items) {
    if (itemsById.has(item.id)) return null;
    itemsById.set(item.id, item);
    if (
      item.relationships !== undefined &&
      !Array.isArray(item.relationships)
    ) {
      return null;
    }
    for (const relationship of item.relationships ?? []) {
      if (
        relationship === null ||
        typeof relationship !== "object"
      ) {
        return null;
      }
      pageRelationships.push(relationship);
    }
  }

  const blockRelationshipIds = new Set(block.relationship_ids);
  if (blockRelationshipIds.size !== block.relationship_ids.length) return null;
  const links: CanonicalCaptionLink[] = [];
  for (const caption of page.items) {
    if (
      caption.type.toLowerCase() !== "caption" ||
      typeof caption.relationship_id !== "string" ||
      caption.relationship_type !== "caption_of" ||
      typeof caption.caption_of !== "string" ||
      !blockRelationshipIds.has(caption.relationship_id)
    ) {
      continue;
    }

    const owner = itemsById.get(caption.caption_of);
    if (!owner) continue;
    const relationshipsWithId = pageRelationships.filter(
      (relationship) => relationship.id === caption.relationship_id,
    );
    if (!Array.isArray(owner.caption_ids)) continue;
    const captionBacklinkCount = owner.caption_ids.filter(
      (captionId) => captionId === caption.id,
    ).length;
    if (
      relationshipsWithId.length !== 1 ||
      captionBacklinkCount !== 1
    ) {
      continue;
    }
    const [relationship] = relationshipsWithId;
    if (
      relationship.type !== "caption_of" ||
      relationship.source_id !== caption.id ||
      relationship.target_id !== owner.id
    ) {
      continue;
    }

    links.push({
      caption,
      owner,
      relationship,
    });
  }

  return links.length === 1 ? links[0] : null;
}

/**
 * Resolve a canonical source note or footnote through the complete public
 * page graph.
 *
 * A canonical primary element ID is an internal-IR identifier, so the retained
 * relationship ID is the bridge back to the public note and owner. The bridge
 * is intentionally fail-closed: every page item and relationship descriptor
 * must have a unique, structurally valid ID before any note metadata is
 * exposed to the renderer.
 */
export function resolveCanonicalNoteLink(
  block: CanonicalBlock,
  page: PageResult,
): CanonicalNoteLink | null {
  const blockNoteType = block.primary_element_type;
  if (blockNoteType !== "source_note" && blockNoteType !== "footnote") {
    return null;
  }
  const contract = NOTE_CONTRACTS[blockNoteType];
  if (
    !Array.isArray(block.relationship_ids) ||
    block.relationship_ids.some((id) => !isNonEmptyString(id))
  ) {
    return null;
  }

  const blockRelationshipIds = new Set(block.relationship_ids);
  if (blockRelationshipIds.size !== block.relationship_ids.length) return null;

  const itemsById = new Map<string, DocumentContentItem>();
  const relationshipsById = new Map<string, PageRelationshipRecord>();
  const claimedRelationshipIds = new Set<string>();
  for (const item of page.items) {
    if (
      item === null ||
      typeof item !== "object" ||
      !isNonEmptyString(item.id) ||
      !isNonEmptyString(item.type) ||
      itemsById.has(item.id)
    ) {
      return null;
    }
    itemsById.set(item.id, item);

    if (item.relationship_id !== undefined) {
      if (
        !isNonEmptyString(item.relationship_id) ||
        claimedRelationshipIds.has(item.relationship_id)
      ) {
        return null;
      }
      claimedRelationshipIds.add(item.relationship_id);
    }

    for (const backlinkField of [
      "source_note_ids",
      "footnote_ids",
    ] as const) {
      const backlinks = item[backlinkField];
      if (
        backlinks !== undefined &&
        (
          !Array.isArray(backlinks) ||
          backlinks.some((id) => !isNonEmptyString(id))
        )
      ) {
        return null;
      }
    }

    if (
      item.relationships !== undefined &&
      !Array.isArray(item.relationships)
    ) {
      return null;
    }
    for (const relationship of item.relationships ?? []) {
      if (
        relationship === null ||
        typeof relationship !== "object" ||
        !isNonEmptyString(relationship.id) ||
        !isNonEmptyString(relationship.type) ||
        !isNonEmptyString(relationship.source_id) ||
        !isNonEmptyString(relationship.target_id) ||
        relationshipsById.has(relationship.id)
      ) {
        return null;
      }
      relationshipsById.set(relationship.id, {
        declaringItemId: item.id,
        relationship,
      });
    }
  }

  const links: CanonicalNoteLink[] = [];
  for (const note of page.items) {
    const ownerId = note[contract.ownerField];
    if (
      note.type !== contract.noteType ||
      !isNonEmptyString(note.relationship_id) ||
      note.relationship_type !== contract.relationshipType ||
      !isNonEmptyString(ownerId) ||
      note[contract.conflictingOwnerField] !== undefined ||
      !blockRelationshipIds.has(note.relationship_id)
    ) {
      continue;
    }

    const owner = itemsById.get(ownerId);
    const relationshipRecord = relationshipsById.get(note.relationship_id);
    if (
      !owner ||
      !isCanonicalNoteOwner(owner) ||
      owner.layout_source_notes_projected !== true ||
      !relationshipRecord ||
      relationshipRecord.declaringItemId !== owner.id
    ) {
      continue;
    }

    const relationship = relationshipRecord.relationship;
    const backlinks = owner[contract.ownerBacklinkField];
    const pageBacklinkCount = page.items.reduce((count, item) => {
      const sourceNoteCount = (item.source_note_ids ?? []).filter(
        (id) => id === note.id,
      ).length;
      const footnoteCount = (item.footnote_ids ?? []).filter(
        (id) => id === note.id,
      ).length;
      return count + sourceNoteCount + footnoteCount;
    }, 0);
    if (
      !Array.isArray(backlinks) ||
      backlinks.filter((id) => id === note.id).length !== 1 ||
      pageBacklinkCount !== 1 ||
      relationship.type !== contract.relationshipType ||
      relationship.source_id !== note.id ||
      relationship.target_id !== owner.id
    ) {
      continue;
    }

    links.push({
      note,
      owner,
      relationship,
      noteType: contract.noteType,
      relationshipType: contract.relationshipType,
    });
  }

  return links.length === 1 ? links[0] : null;
}
