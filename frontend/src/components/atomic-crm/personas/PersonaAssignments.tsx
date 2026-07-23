import { useEffect, useMemo, useRef, useState } from "react";
import { useNotify, useRefresh } from "ra-core";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Globe2, RefreshCcw, Workflow } from "lucide-react";
import {
  ADAPTER_PROVIDERS,
  type AdapterPersonaAssignment,
  type AdapterProvider,
  type Persona,
} from "../types";
import {
  activatePersona,
  listPersonaAssignments,
  updatePersonaAssignment,
} from "@/lib/vfic/knowledgeService";

interface PersonaAssignmentsProps {
  persona: Persona;
}

type RowFeedback = {
  pending: boolean;
  success: string | null;
  error: string | null;
};

const EMPTY_ROW_FEEDBACK: RowFeedback = {
  pending: false,
  success: null,
  error: null,
};

const ADAPTER_LABELS: Record<AdapterProvider, string> = {
  zalo_bot: "Zalo Chatbot",
  zalo_oa: "Zalo OA",
  facebook_messenger: "Messenger",
};

const initialFeedbackState = (): Record<AdapterProvider, RowFeedback> => ({
  zalo_bot: { ...EMPTY_ROW_FEEDBACK },
  zalo_oa: { ...EMPTY_ROW_FEEDBACK },
  facebook_messenger: { ...EMPTY_ROW_FEEDBACK },
});

const normalizeAssignments = (
  assignments: AdapterPersonaAssignment[],
): AdapterPersonaAssignment[] =>
  ADAPTER_PROVIDERS.map((provider) => {
    const existing = assignments.find((item) => item.provider === provider);
    return (
      existing ?? {
        provider,
        label: ADAPTER_LABELS[provider],
        persona_id: null,
        effective_persona_id: null,
        is_default: false,
      }
    );
  });

const badgeClassName = (variant: "brand" | "good" | "neutral") => {
  if (variant === "brand") return "persona-studio-badge is-brand";
  if (variant === "good") return "persona-studio-badge is-good";
  return "persona-studio-badge";
};

const getAssignmentState = (
  assignment: AdapterPersonaAssignment,
  persona: Persona,
) => {
  if (assignment.persona_id === persona.id) {
    return {
      badge: "Gán riêng",
      badgeVariant: "brand" as const,
      summary: "Dùng Agent này.",
      actionLabel: "Trả về mặc định",
      nextPersonaId: null as string | null,
      actionDisabled: false,
    };
  }

  if (assignment.is_default && assignment.effective_persona_id === persona.id) {
    return {
      badge: "Theo mặc định",
      badgeVariant: "good" as const,
      summary: "Kế thừa từ mặc định.",
      actionLabel: "Đang mặc định",
      nextPersonaId: null as string | null,
      actionDisabled: true,
    };
  }

  return {
    badge: assignment.persona_id ? "Agent khác" : "Mặc định khác",
    badgeVariant: "neutral" as const,
    summary: assignment.persona_id
      ? "Đang dùng Agent khác."
      : "Kế thừa mặc định khác.",
    actionLabel: "Gán Agent này",
    nextPersonaId: persona.id,
    actionDisabled: false,
  };
};

export const PersonaAssignments = ({ persona }: PersonaAssignmentsProps) => {
  const notify = useNotify();
  const refresh = useRefresh();
  const [assignments, setAssignments] = useState<AdapterPersonaAssignment[]>(
    [],
  );
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [feedbackByProvider, setFeedbackByProvider] =
    useState<Record<AdapterProvider, RowFeedback>>(initialFeedbackState);
  const [activating, setActivating] = useState(false);
  const assignmentRequestId = useRef(0);

  const setProviderFeedback = (
    provider: AdapterProvider,
    patch: Partial<RowFeedback>,
  ) => {
    setFeedbackByProvider((current) => ({
      ...current,
      [provider]: {
        ...current[provider],
        ...patch,
      },
    }));
  };

  const loadAssignments = async (showLoading = false) => {
    const requestId = ++assignmentRequestId.current;
    if (showLoading) {
      setLoading(true);
    }
    setLoadError(null);
    try {
      const result = await listPersonaAssignments();
      if (requestId === assignmentRequestId.current) {
        setAssignments(normalizeAssignments(result.data));
        return true;
      }
      return null;
    } catch (error) {
      if (requestId === assignmentRequestId.current) {
        setLoadError(
          (error as Error).message ?? "Không tải được cấu hình adapter.",
        );
        return false;
      }
      return null;
    } finally {
      if (requestId === assignmentRequestId.current) {
        setLoading(false);
      }
    }
  };

  useEffect(() => {
    void loadAssignments(true);
  }, []);

  const usageSummary = useMemo(() => {
    const effectiveCount = assignments.filter(
      (assignment) => assignment.effective_persona_id === persona.id,
    ).length;
    const explicitCount = assignments.filter(
      (assignment) => assignment.persona_id === persona.id,
    ).length;
    return { effectiveCount, explicitCount };
  }, [assignments, persona.id]);

  const refreshProvider = async (provider: AdapterProvider) => {
    setProviderFeedback(provider, {
      pending: true,
      success: null,
      error: null,
    });
    const ok = await loadAssignments();
    if (ok == null) {
      setProviderFeedback(provider, { pending: false });
      return;
    }
    setProviderFeedback(provider, {
      pending: false,
      success: ok ? "Đã tải lại trạng thái adapter." : null,
      error: ok ? null : "Không tải lại được trạng thái adapter.",
    });
  };

  const saveAssignment = async (
    provider: AdapterProvider,
    personaId: string | null,
  ) => {
    setProviderFeedback(provider, {
      pending: true,
      success: null,
      error: null,
    });
    try {
      await updatePersonaAssignment(provider, personaId);
      const ok = await loadAssignments();
      if (ok == null) {
        setProviderFeedback(provider, { pending: false });
        return;
      }
      if (!ok) {
        throw new Error("Đã cập nhật nhưng không tải lại được trạng thái.");
      }
      refresh();
      const successMessage =
        personaId == null
          ? "Đã trả adapter về Agent mặc định."
          : "Đã gán Agent cho adapter.";
      setProviderFeedback(provider, {
        pending: false,
        success: successMessage,
        error: null,
      });
      notify(successMessage, { type: "success" });
    } catch (error) {
      const message =
        (error as Error).message ?? "Không cập nhật được cấu hình adapter.";
      setProviderFeedback(provider, {
        pending: false,
        success: null,
        error: message,
      });
      notify(message, { type: "error" });
    }
  };

  const setGlobalDefault = async () => {
    if (activating || persona.is_active) return;
    setActivating(true);
    try {
      await activatePersona(persona.id);
      await loadAssignments();
      refresh();
      notify("Đã đặt làm Agent mặc định toàn hệ thống.", { type: "success" });
    } catch (error) {
      notify((error as Error).message, { type: "error" });
    } finally {
      setActivating(false);
    }
  };

  return (
    <section className="persona-assignment-surface">
      <header className="persona-assignment-header">
        <div className="persona-assignment-header-row">
          <div>
            <h2 className="persona-assignment-title">
              <Workflow className="size-4 text-primary" />
              Adapter
            </h2>
            <p className="persona-assignment-description">
              Chọn Agent hiệu lực cho từng kênh.
            </p>
          </div>
          <div className="persona-assignment-actions">
            {persona.is_active ? (
              <Badge
                variant="outline"
                className="gap-1 border-primary/20 bg-primary/5 text-primary"
              >
                <Globe2 className="size-3.5" />
                Agent mặc định
              </Badge>
            ) : (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="tt-btn-touch"
                onClick={setGlobalDefault}
                disabled={activating}
              >
                {activating ? (
                  <span
                    className="tt-loading tt-loading-spinner tt-loading-sm"
                    aria-hidden="true"
                  />
                ) : (
                  <Globe2 className="size-4" />
                )}
                Đặt mặc định
              </Button>
            )}
          </div>
        </div>
      </header>

      <div className="persona-assignment-content">
        <div className="persona-assignment-summary">
          <div>Đang dùng</div>
          <strong>{usageSummary.effectiveCount}/3</strong>
          <p>
            {usageSummary.explicitCount} gán riêng ·{" "}
            {usageSummary.effectiveCount - usageSummary.explicitCount} kế thừa
          </p>
        </div>

        <div className="persona-assignment-table">
          <div className="persona-assignment-table-head">
            <span>Adapter</span>
            <span>3 kênh cố định</span>
          </div>

          <div className="persona-assignment-table-body">
            {loading ? (
              <div className="space-y-3 p-4">
                {ADAPTER_PROVIDERS.map((provider) => (
                  <Skeleton
                    key={provider}
                    className="h-[84px] w-full rounded-[10px]"
                  />
                ))}
              </div>
            ) : loadError ? (
              <div className="persona-assignment-empty-state" role="alert">
                <p>{loadError}</p>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => void loadAssignments(true)}
                >
                  <RefreshCcw className="size-4" />
                  Tải lại
                </Button>
              </div>
            ) : (
              assignments.map((assignment) => {
                const state = getAssignmentState(assignment, persona);
                const feedback = feedbackByProvider[assignment.provider];
                const missingAssignment = !assignment.effective_persona_id;

                return (
                  <section
                    key={assignment.provider}
                    className="persona-assignment-row persona-assignment-row-card"
                    role="group"
                    aria-label={assignment.label}
                  >
                    <div className="persona-assignment-row-copy">
                      <div className="persona-assignment-row-title">
                        <strong>{assignment.label}</strong>
                        <Badge
                          variant="outline"
                          className={badgeClassName(state.badgeVariant)}
                        >
                          {missingAssignment ? "Thiếu dữ liệu" : state.badge}
                        </Badge>
                      </div>
                      <p>
                        {missingAssignment
                          ? "Chưa nhận được Agent hiệu lực cho adapter này."
                          : state.summary}
                      </p>
                      <div
                        className="persona-assignment-row-feedback"
                        aria-live="polite"
                      >
                        {feedback.error ? (
                          <span className="is-error">{feedback.error}</span>
                        ) : null}
                        {!feedback.error && feedback.success ? (
                          <span className="is-success">{feedback.success}</span>
                        ) : null}
                      </div>
                    </div>

                    <div className="persona-assignment-row-actions">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="tt-btn-touch"
                        onClick={() =>
                          void refreshProvider(assignment.provider)
                        }
                        disabled={feedback.pending}
                        aria-label={`Tải lại trạng thái ${assignment.label}`}
                      >
                        {feedback.pending ? (
                          <span
                            className="tt-loading tt-loading-spinner tt-loading-sm"
                            aria-hidden="true"
                          />
                        ) : (
                          <RefreshCcw className="size-4" />
                        )}
                        Tải lại
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        className="tt-btn-touch"
                        onClick={() =>
                          !state.actionDisabled
                            ? void saveAssignment(
                                assignment.provider,
                                state.nextPersonaId,
                              )
                            : undefined
                        }
                        disabled={feedback.pending || state.actionDisabled}
                        aria-label={`${state.actionLabel} cho ${assignment.label}`}
                      >
                        {feedback.pending ? (
                          <span
                            className="tt-loading tt-loading-spinner tt-loading-sm"
                            aria-hidden="true"
                          />
                        ) : null}
                        {state.actionLabel}
                      </Button>
                    </div>
                  </section>
                );
              })
            )}
          </div>
        </div>
      </div>
    </section>
  );
};
