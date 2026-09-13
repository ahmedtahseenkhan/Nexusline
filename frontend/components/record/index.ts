/* The record page kit (record-page-spec §3). Import from here or from each file.
   API reference: scratchpad/redesign/record-page-spec.md, "Component API as built". */

export type {
  MetaItem,
  RecordIdentity,
  FactItem,
  RelatedGroup,
  TrailFilter,
  PrimaryCandidate,
  StatusRuleVerdict,
} from "@/components/record/types";

export { default as RecordHeader } from "@/components/record/RecordHeader";
export { default as Segs } from "@/components/record/Segs";
export { default as SummaryBand, BASIS_WORD } from "@/components/record/SummaryBand";
export { default as AppetiteScale } from "@/components/record/AppetiteScale";
export { default as OpenPoints } from "@/components/record/OpenPoints";
export {
  default as RecordSection,
  RecordSectionsProvider,
  useRecordSections,
  scrollToSection,
  type RecordSectionsApi,
  type RecordSectionItem,
} from "@/components/record/RecordSection";
export { default as SectionNav } from "@/components/record/SectionNav";
export { default as FactList, Fact, FactGrid, isUnsetValue } from "@/components/record/FactList";
export { default as RelatedGroups, relatedCount } from "@/components/record/RelatedGroups";
export { RelatedClusterProvider, useRelatedCluster } from "@/components/record/RelatedCluster";
export { default as Disclosure } from "@/components/record/Disclosure";
export { default as SignOffCard, type SignOffCardProps } from "@/components/record/SignOffCard";
export { default as RecordTrail } from "@/components/record/RecordTrail";
export { default as PrimaryAction, pickPrimary, primaryLabel } from "@/components/record/PrimaryAction";
export { default as StatusRuleChips, useStatusRuleVerdicts, ruleCondition } from "@/components/record/StatusRuleChips";
export {
  useRecordGovernanceData,
  RecordGovernanceContext,
  useRecordGovernance,
  toGovModel,
  govModelFromParts,
  GovernanceScope,
  type RecordGovernance,
  type AttestationStatusB1,
} from "@/components/record/RecordGovernance";
export { RecordSurfaceContext, useRecordSurface, type RecordSurface } from "@/components/record/RecordSurface";
export { WorkflowBadge } from "@/components/record/WorkflowBadge";
export { withBaseMoreItems, copyRecordLink, printRecord } from "@/components/record/actions";
export { actionWord, trailCategory } from "@/components/record/trailWords";
export { useRecordFmt, useRecordCtx, approvalMetaItem, approvalHintFor, reviewStatusMetaItem } from "@/components/record/ctx";

/* v1.1 shared pieces (record-page-spec "Component API as built", section G). */
export {
  default as RecordIssues,
  RecordIssuesSection,
  useRecordIssues,
  recordIssuesText,
  ISSUE_SEVERITIES,
  type RecordIssuesHandle,
  type RecordIssuesProps,
  type RecordIssuesSectionProps,
  type RecordIssuesStatus,
  type IssueRow,
  type IssueLinkKind,
} from "@/components/record/RecordIssues";
export {
  default as useResidualSuggestion,
  isNoteRequired,
  UNTESTED_CREDIT_NOTE_NEEDED,
  type ResidualSuggestionApi,
  type SuggestedResidualB12,
} from "@/components/record/useResidualSuggestion";
export { default as SuggestedClausesRow, type SuggestedClausesRowProps } from "@/components/record/SuggestedClausesRow";
export {
  default as AssetRiskReportButton,
  useAssetRiskReport,
  assetRiskReportItems,
  riskReportHint,
  type AssetRiskReport,
} from "@/components/record/AssetRiskReportButton";
export { default as LabelledSearch, useLabelledControls, rowAction, rowActionName, rowLabel } from "@/components/record/a11y";
export { orderMeta, isApprovalMeta, isStatusMeta, STATUS_META_KEYS, type OrderedMeta } from "@/components/record/metaOrder";
export { useRecordLead, repeatsLead, publishRecordLead } from "@/components/record/lead";
export { trailRowWords } from "@/components/record/trailWords";
