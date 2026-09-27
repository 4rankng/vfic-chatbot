---
id: FE-24
title: "Route semi_auto takeover and integration-button strings through the message catalog"
severity: low
area: frontend
labels: [frontend, i18n, consistency]
effort: S
status: done
column: QA_TESTED
opened: 2026-09-26
---

# FE-24 — Route semi_auto takeover and integration-button strings through the message catalog

**Severity:** low · **Area:** frontend · **Effort:** S · **Labels:** frontend, i18n, consistency

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

Components rebuilt in the sweep inconsistently straddle the two idioms: the same JSX expression calls translate('crm.common.*') on one branch and embeds an identical-purpose Vietnamese literal on the other; the conversation takeover flow added a semi_auto mode whose success/error strings bypass the catalog while its sibling modes use catalog keys; ProfilePage passes messageArgs._ overrides that shadow catalog entries it already defines.

## Evidence

- frontend/src/components/atomic-crm/conversations/presentation/use-conversation-actions.ts:66-80 — human/bot branches notify catalog keys (:67,:70) but the semi_auto branches notify literals 'Đã bật chế độ bán tự động'/'Không thể bật chế độ bán tự động' (:69,:78)
- frontend/src/components/atomic-crm/integrations/presentation/ZaloChannelSection.tsx:115-117 — ternary mixes translate('crm.common.testing') with literal 'Lưu & kiểm tra'; repeated at :188-190
- frontend/src/components/atomic-crm/integrations/presentation/JevSection.tsx:131-138 — footer mixes translate('crm.common.saving'/'crm.common.save_changes') with literal 'Token được mã hoá, không hiển thị lại.'; same in LlmProvidersSection.tsx:275-283
- frontend/src/components/atomic-crm/knowledge-base/KnowledgeBaseShow.tsx:396-399 — 'Lưu tệp' literal as the non-pending label while the pending label is translate('crm.common.saving'); same split in FacebookMessengerIntegrationPage.tsx:412-414 and FacebookMessengerPageCard.tsx:110-112
- frontend/src/components/atomic-crm/settings/ProfilePage.tsx:69-82 — notify('crm.profile.updated', { messageArgs: { _: 'Thông tin đã được cập nhật' } }) overrides the catalog copy with an inline string; likewise update_error at :79-82

## Impact

Copy for the same action lives in two places, so edits diverge (already happened with takeover.error), and the semi_auto notifications can never be reworded or localized without touching component code; reviewers can no longer treat 'uses the catalog' as an invariant on new UI.

## Suggested fix

Add conversations.takeover.semantic_auto_{success,error} (or equivalent) to the catalog and use them in use-conversation-actions.ts:69,78; add the integration button/footer strings to the catalog and replace the literals in ZaloChannelSection, JevSection, LlmProvidersSection, FacebookMessengerIntegrationPage, FacebookMessengerPageCard, KnowledgeBaseShow; drop the messageArgs._ overrides in ProfilePage so the catalog values win. Fix alongside FE-23 — same catalog file.

## Notes

Scoped to mixed-idiom sites; whole pages that hardcode Vietnamese by convention are the established pattern and not carded.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
