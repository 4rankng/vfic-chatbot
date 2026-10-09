/**
 * Multi-Page connected-Page card (plan 260908-1341 Phase 3; D3 — editor on the
 * Messenger settings page).
 *
 * Rendered one-per-ACTIVE-Page inside FacebookMessengerIntegrationPage. The
 * card owns everything Page-scoped: it loads its own Project assignments,
 * commits its own assignment set (replace-all PUT) and disconnects itself.
 * Keyed everywhere by the full, unmasked `account.page_id`. The Messenger
 * channel test stays group-level (webhook subscription is app-level).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNotify, useTranslate } from "ra-core";
import { Badge } from "@/components/base/badges/badges";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import type { Project } from "../types";
import { facebookIntegrationGateway, type FacebookAccountStatus } from "./api";

const PAGE_STATUS_LABELS: Readonly<
  Record<FacebookAccountStatus["status"], string>
> = {
  ACTIVE: "Đang hoạt động",
  INACTIVE: "Chờ kích hoạt",
};

// Shared Project checkbox list. Pure UI: the connector card uses it inside its
// assignment editor; the Page-picker uses it to collect the assignment set
// committed atomically with activation (D1).
type FacebookProjectCheckboxListProps = {
  projects: Project[];
  selected: string[];
  onToggle: (id: string, checked: boolean) => void;
  disabled?: boolean;
};

const FacebookProjectCheckboxList = ({
  projects,
  selected,
  onToggle,
  disabled = false,
}: FacebookProjectCheckboxListProps) => (
  <ul className="settings-facebook-project-list">
    {projects.map((project) => (
      <li key={project.id}>
        {/*
          `validationBehavior="aria"` keeps native validation from pre-empting
          the console's own validation in a react-admin form, and `uu-scope`
          re-binds the four utility names both systems define. The checkbox
          renders its own label, so the option name travels as `label` instead
          of a sibling `<span>`.
        */}
        <Checkbox
          className="uu-scope"
          label={project.name}
          isSelected={selected.includes(project.id)}
          isDisabled={disabled}
          onChange={(isSelected) => onToggle(project.id, isSelected)}
          validationBehavior="aria"
        />
      </li>
    ))}
  </ul>
);

// Per-Page Project assignment editor. Draft selection is local; "Lưu dự án"
// commits the set for that Page only (replace-all PUT). The draft re-seeds
// only when the server's assignment list semantically changes, so a refetch
// returning the same list never clobbers an in-flight edit.
type FacebookPageProjectsEditorProps = {
  assignedProjectIds: string[];
  projects: Project[];
  saving: boolean;
  onCommit: (projectIds: string[]) => void;
};

const FacebookPageProjectsEditor = ({
  assignedProjectIds,
  projects,
  saving,
  onCommit,
}: FacebookPageProjectsEditorProps) => {
  const translate = useTranslate();
  const [draft, setDraft] = useState<string[]>(assignedProjectIds);
  const lastServerKeyRef = useRef(assignedProjectIds.join(","));
  useEffect(() => {
    const serverKey = assignedProjectIds.join(",");
    if (lastServerKeyRef.current === serverKey) return;
    lastServerKeyRef.current = serverKey;
    setDraft(assignedProjectIds);
  }, [assignedProjectIds]);

  const dirty = useMemo(
    () =>
      draft.length !== assignedProjectIds.length ||
      draft.some((id) => !assignedProjectIds.includes(id)),
    [draft, assignedProjectIds],
  );

  const toggle = (id: string, checked: boolean) => {
    setDraft((current) =>
      checked
        ? [...current, id]
        : current.filter((existing) => existing !== id),
    );
  };

  return (
    <div className="settings-facebook-page-projects">
      <div className="settings-field-label-row">
        <span className="settings-field-label">Dự án được gán</span>
        <Button
          type="button"
          color="tertiary"
          size="sm"
          className="settings-facebook-project-save"
          onClick={() => onCommit(draft)}
          isDisabled={saving || !dirty}
          aria-busy={saving}
        >
          {saving
            ? translate("crm.common.saving")
            : translate("crm.common.save_project")}
        </Button>
      </div>
      <FacebookProjectCheckboxList
        projects={projects}
        selected={draft}
        onToggle={toggle}
        disabled={saving}
      />
      {draft.length === 0 ? (
        <span className="settings-field-hint">
          Trang chưa gán dự án nào — trợ lý sẽ không đề xuất dự án qua Trang
          này.
        </span>
      ) : null}
    </div>
  );
};

// One connected Page card. Mutations live here so busy states are card-scoped;
// assignment data comes from the per-Page GET (contract, not status accounts).
type FacebookPageCardProps = {
  account: FacebookAccountStatus;
  projects: Project[];
};

const FacebookPageCard = ({ account, projects }: FacebookPageCardProps) => {
  const queryClient = useQueryClient();
  const notify = useNotify();

  // This Page's Project assignments (per-Page GET from the contract).
  const assignmentsQuery = useQuery({
    queryKey: ["facebook-page-projects", account.page_id],
    queryFn: () => facebookIntegrationGateway.loadPageProjects(account.page_id),
    staleTime: 30_000,
  });
  const pageProjects = assignmentsQuery.data;
  const assignedProjectIds = useMemo(
    () =>
      (pageProjects?.assignments ?? []).map(
        (assignment) => assignment.project_id,
      ),
    [pageProjects],
  );

  // Replace-all assignment save for this Page.
  const saveAssignments = useMutation({
    mutationFn: (projectIds: string[]) =>
      facebookIntegrationGateway.setPageProjects(account.page_id, projectIds),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["facebook-page-projects", account.page_id],
      });
      notify("Đã cập nhật dự án cho Trang.", { type: "success" });
    },
    onError: () =>
      notify("Không thể lưu dự án cho Trang. Vui lòng thử lại.", {
        type: "error",
      }),
  });

  // Disconnect THIS Page (marks inactive; history + assignments preserved — D6).
  const disconnect = useMutation({
    mutationFn: () =>
      facebookIntegrationGateway.disconnectPage(account.page_id),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["facebook-integration-status"],
      });
    },
    onError: () => notify("Ngắt kết nối Trang thất bại.", { type: "error" }),
  });

  // Owner pause switch (2026-10-08): the Page stays connected and keeps
  // receiving candidate messages, but the bot sends nothing on it.
  const setPause = useMutation({
    mutationFn: (paused: boolean) =>
      facebookIntegrationGateway.setBotPause(account.page_id, paused),
    onSuccess: (_, paused) => {
      queryClient.invalidateQueries({
        queryKey: ["facebook-integration-status"],
      });
      notify(
        paused
          ? "Đã tạm dừng bot trên Trang. Tin nhắn vẫn được nhận."
          : "Đã bật lại bot trên Trang.",
        { type: "success" },
      );
    },
    onError: () =>
      notify("Không thể đổi trạng thái bot. Vui lòng thử lại.", {
        type: "error",
      }),
  });
  const botPaused = account.bot_paused === true;

  return (
    <li className="settings-facebook-page-item">
      <div className="settings-facebook-page-card">
        <div className="settings-facebook-page-card-heading">
          <div className="settings-facebook-page-card-title">
            <strong>{account.label}</strong>
            <span className="settings-field-hint">
              (…{account.page_id_suffix})
            </span>
          </div>
          <div className="flex items-center gap-2">
            {botPaused ? (
              <Badge
                type="pill-color"
                size="sm"
                color="warning"
                className="uu-scope"
              >
                Bot tạm dừng
              </Badge>
            ) : null}
            <Badge
              type="pill-color"
              size="sm"
              color={account.status === "ACTIVE" ? "success" : "warning"}
              className="uu-scope"
            >
              {PAGE_STATUS_LABELS[account.status]}
            </Badge>
          </div>
        </div>
        {assignmentsQuery.isPending ? (
          <p role="status" className="settings-field-hint">
            Đang tải dự án đã gán…
          </p>
        ) : assignmentsQuery.isError || !pageProjects ? (
          <div
            role="alert"
            className="flex flex-wrap items-center justify-between gap-3"
          >
            <p className="settings-field-hint">
              Chưa tải được dự án đã gán cho Trang.
            </p>
            <Button
              className="uu-scope"
              color="secondary"
              size="sm"
              onClick={() => void assignmentsQuery.refetch()}
            >
              Thử lại
            </Button>
          </div>
        ) : (
          <FacebookPageProjectsEditor
            assignedProjectIds={assignedProjectIds}
            projects={projects}
            saving={saveAssignments.isPending}
            onCommit={(ids) => saveAssignments.mutate(ids)}
          />
        )}
        {botPaused ? (
          <p className="settings-field-hint">
            Bot đang tạm dừng: tin nhắn ứng viên vẫn được nhận và lưu, nhưng bot
            không tự trả lời — trả lời thủ công hoặc bấm «Chạy lại bot».
          </p>
        ) : null}
        <div className="settings-facebook-page-actions">
          {account.status === "ACTIVE" ? (
            <Button
              type="button"
              color="tertiary"
              className="uu-scope settings-test-button tt-btn-touch"
              onClick={() => setPause.mutate(!botPaused)}
              isDisabled={setPause.isPending}
              aria-busy={setPause.isPending}
            >
              {setPause.isPending
                ? "Đang lưu…"
                : botPaused
                  ? "Chạy lại bot"
                  : "Tạm dừng bot"}
            </Button>
          ) : null}
          <Button
            type="button"
            color="secondary"
            className="uu-scope settings-test-button settings-danger-action tt-btn-touch"
            onClick={() => disconnect.mutate()}
            isDisabled={disconnect.isPending}
            aria-busy={disconnect.isPending}
          >
            {disconnect.isPending ? "Đang ngắt…" : "Ngắt kết nối"}
          </Button>
        </div>
      </div>
    </li>
  );
};

export { FacebookPageCard, FacebookProjectCheckboxList };
