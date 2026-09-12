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
import { useNotify } from "ra-core";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
  onToggle: (id: string, checked: boolean | "indeterminate") => void;
};

const FacebookProjectCheckboxList = ({
  projects,
  selected,
  onToggle,
}: FacebookProjectCheckboxListProps) => (
  <ul className="settings-facebook-project-list">
    {projects.map((project) => (
      <li key={project.id}>
        <label>
          <Checkbox
            checked={selected.includes(project.id)}
            onCheckedChange={(checked) => onToggle(project.id, checked)}
          />
          <span>{project.name}</span>
        </label>
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

  const toggle = (id: string, checked: boolean | "indeterminate") => {
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
          variant="ghost"
          size="sm"
          className="settings-facebook-project-save"
          onClick={() => onCommit(draft)}
          disabled={saving || !dirty}
          aria-busy={saving}
        >
          {saving ? "Đang lưu…" : "Lưu dự án"}
        </Button>
      </div>
      <FacebookProjectCheckboxList
        projects={projects}
        selected={draft}
        onToggle={toggle}
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
  const { data: pageProjects } = useQuery({
    queryKey: ["facebook-page-projects", account.page_id],
    queryFn: () => facebookIntegrationGateway.loadPageProjects(account.page_id),
    staleTime: 30_000,
  });
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
          <span
            className={`settings-facebook-page-status ${
              account.status === "ACTIVE" ? "is-active" : "is-pending"
            }`}
          >
            {PAGE_STATUS_LABELS[account.status]}
          </span>
        </div>
        <FacebookPageProjectsEditor
          assignedProjectIds={assignedProjectIds}
          projects={projects}
          saving={saveAssignments.isPending}
          onCommit={(ids) => saveAssignments.mutate(ids)}
        />
        <div className="settings-facebook-page-actions">
          <button
            type="button"
            className="settings-test-button settings-danger-action tt-btn-touch"
            onClick={() => disconnect.mutate()}
            disabled={disconnect.isPending}
            aria-busy={disconnect.isPending}
          >
            {disconnect.isPending ? "Đang ngắt…" : "Ngắt kết nối"}
          </button>
        </div>
      </div>
    </li>
  );
};

export { FacebookPageCard, FacebookProjectCheckboxList };
