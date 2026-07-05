import {
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type ReactNode,
} from "react";
import { useNotify } from "ra-core";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Switch } from "@/components/ui/switch";
import {
  BotMessageSquare,
  CheckCircle2,
  Download,
  FileText,
  Loader2,
  Upload,
} from "lucide-react";
import { importPersona } from "@/lib/vfic/knowledgeService";
import {
  LEAD_STAGES,
  type LeadScoreValue,
  type LeadStageValue,
  type PersonaFollowupRule,
  type PersonaFollowupRules,
} from "../types";
import {
  composePersonaMarkdown,
  defaultPersonaFollowupRules,
  parsePersonaMarkdown,
  PERSONA_SECTIONS,
  PERSONA_TEMPLATE,
  type PersonaSectionValues,
} from "./personaMarkdown";

const PERSONA_TEMPLATE_FILENAME = "mau-agent-vfic.md";

const FOLLOWUP_SCORE_LABELS: Record<LeadScoreValue, string> = {
  hot: "Hot",
  warm: "Warm",
  not_interested: "Cold",
};

const FOLLOWUP_SCORE_ORDER: LeadScoreValue[] = [
  "hot",
  "warm",
  "not_interested",
];

const normalizeFollowupRules = (
  rules?: Partial<PersonaFollowupRules> | null,
): PersonaFollowupRules => {
  const defaults = defaultPersonaFollowupRules();
  return {
    hot: { ...defaults.hot, ...(rules?.hot ?? {}) },
    warm: { ...defaults.warm, ...(rules?.warm ?? {}) },
    not_interested: {
      ...defaults.not_interested,
      ...(rules?.not_interested ?? {}),
    },
  };
};

const parseCadenceInput = (value: string): number[] =>
  value
    .split(/[,\s]+/)
    .map((part) => Number.parseInt(part.trim(), 10))
    .filter((value) => Number.isFinite(value) && value > 0);

export interface PersonaValues {
  name: string;
  body_md: string;
  notes: string;
  followup_rules?: PersonaFollowupRules;
}

interface PersonaFormProps {
  initial: PersonaValues;
  submitLabel: string;
  onSubmit: (values: PersonaValues) => Promise<void>;
  onImported?: () => void;
  extraActions?: ReactNode;
}

const PersonaForm = ({
  initial,
  submitLabel,
  onSubmit,
  onImported,
  extraActions,
}: PersonaFormProps) => {
  const notify = useNotify();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState(initial.name);
  const [sectionValues, setSectionValues] = useState<PersonaSectionValues>(
    () => parsePersonaMarkdown(initial.body_md).sections,
  );
  const [extraMarkdown, setExtraMarkdown] = useState(
    () => parsePersonaMarkdown(initial.body_md).extraMarkdown,
  );
  const [notes, setNotes] = useState(initial.notes ?? "");
  const [followupRules, setFollowupRules] = useState<PersonaFollowupRules>(() =>
    normalizeFollowupRules(initial.followup_rules),
  );
  const [submitting, setSubmitting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [nameError, setNameError] = useState<string | null>(null);
  const nameInputRef = useRef<HTMLInputElement>(null);
  const bodyMd = useMemo(
    () => composePersonaMarkdown(sectionValues, extraMarkdown),
    [extraMarkdown, sectionValues],
  );

  const updateSectionValue = (index: number, value: string) => {
    setSectionValues((current) =>
      current.map((section, sectionIndex) =>
        sectionIndex === index ? value : section,
      ),
    );
  };

  const submit = async () => {
    if (submitting) return;
    if (!name.trim()) {
      setNameError("Vui lòng nhập tên Agent.");
      nameInputRef.current?.focus();
      return;
    }
    setNameError(null);
    setSubmitting(true);
    try {
      await onSubmit({
        name,
        body_md: bodyMd,
        notes,
        followup_rules: followupRules,
      });
    } finally {
      setSubmitting(false);
    }
  };

  const downloadTemplate = () => {
    const blob = new Blob([PERSONA_TEMPLATE], {
      type: "text/markdown;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = PERSONA_TEMPLATE_FILENAME;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  const onPersonaFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;

    const fileName = file.name.toLowerCase();
    if (!fileName.endsWith(".md") && !fileName.endsWith(".txt")) {
      notify("Vui lòng tải lên file .md hoặc .txt.", { type: "warning" });
      return;
    }

    setImporting(true);
    try {
      const persona = await importPersona(file);
      const parsed = parsePersonaMarkdown(persona.body_md);
      // Populate form with imported data
      setName(persona.name);
      setSectionValues(parsed.sections);
      setExtraMarkdown(parsed.extraMarkdown);
      if (persona.notes != null) setNotes(persona.notes);
      if (persona.followup_rules) {
        setFollowupRules(normalizeFollowupRules(persona.followup_rules));
      }
      notify(
        `Đã nhập Agent "${persona.name}" thành công. Hãy rà soát trước khi lưu.`,
        { type: "success" },
      );
      onImported?.();
    } catch (e: unknown) {
      const message =
        (e as Error)?.message ??
        "Không nhập được file Agent. Vui lòng thử lại.";
      // Extract friendly message from API error if possible
      notify(message, { type: "error" });
    } finally {
      setImporting(false);
    }
  };

  const completedSectionCount = sectionValues.filter((section) =>
    section.trim(),
  ).length;
  const contentLength = [...sectionValues, extraMarkdown]
    .join("\n")
    .trim().length;

  const updateFollowupRule = (
    score: LeadScoreValue,
    patch: Partial<PersonaFollowupRule>,
  ) => {
    setFollowupRules((current) => ({
      ...current,
      [score]: {
        ...current[score],
        ...patch,
      },
    }));
  };

  const toggleFollowupStage = (
    score: LeadScoreValue,
    stage: LeadStageValue,
    checked: boolean,
  ) => {
    const current = followupRules[score].eligible_stages;
    const next = checked
      ? Array.from(new Set([...current, stage]))
      : current.filter((value) => value !== stage);
    updateFollowupRule(score, {
      eligible_stages: next.length > 0 ? next : ["NEW"],
    });
  };

  return (
    <div className="persona-edit-surface">
      <form
        className="persona-edit-form"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <header className="persona-edit-formbar">
          <div className="persona-edit-formbar-title">
            <BotMessageSquare className="size-4 text-primary" />
            <div>
              <strong>Cấu hình Agent</strong>
              <span>Viết prompt, follow-up và phạm vi vận hành.</span>
            </div>
          </div>
          <div className="persona-edit-formbar-metrics">
            <Badge variant="secondary" className="gap-1.5">
              <FileText className="size-3" />
              {completedSectionCount}/7 phần
            </Badge>
            <Badge variant="outline" className="gap-1.5">
              <FileText className="size-3" />
              {contentLength.toLocaleString("vi-VN")} ký tự
            </Badge>
            <Badge
              variant={name.trim() ? "secondary" : "outline"}
              className="gap-1.5"
            >
              <CheckCircle2 className="size-3" />
              {name.trim() ? "Có tên Agent" : "Chưa đặt tên"}
            </Badge>
          </div>
        </header>

        <section className="persona-edit-identity">
          <div className="persona-edit-name-field">
            <Label htmlFor="persona-name" className="text-sm font-semibold">
              Tên Agent{" "}
              <span aria-hidden="true" className="text-destructive">
                *
              </span>
            </Label>
            <Input
              id="persona-name"
              ref={nameInputRef}
              value={name}
              aria-invalid={nameError ? true : undefined}
              onChange={(e) => {
                setName(e.target.value);
                if (nameError) setNameError(null);
              }}
              placeholder="VD: Trợ lý tuyển dụng LG Display"
              className="h-11 text-base sm:text-sm lg:max-w-xl"
            />
            {nameError ? (
              <p role="alert" className="text-xs font-medium text-destructive">
                {nameError}
              </p>
            ) : null}
          </div>
        </section>

        <section
          className="persona-edit-import-strip"
          aria-label="Nhập file cấu hình Agent"
        >
          <div className="persona-edit-import-copy">
            <span className="persona-edit-import-icon" aria-hidden="true">
              <Upload className="size-4" />
            </span>
            <div>
              <strong>Nhập file cấu hình</strong>
              <p>Dùng file .md hoặc .txt để điền nhanh prompt trước khi sửa.</p>
            </div>
          </div>
          <div className="persona-edit-import-actions">
            <Button type="button" variant="outline" onClick={downloadTemplate}>
              <Download className="size-4" />
              Tải mẫu
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={importing}
              onClick={() => fileInputRef.current?.click()}
            >
              {importing ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Upload className="size-4" />
              )}
              {importing ? "Đang nhập..." : "Nhập file"}
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".md,.txt,text/markdown,text/plain"
              className="hidden"
              onChange={onPersonaFileChange}
            />
          </div>
        </section>

        <div className="persona-edit-grid">
          <main className="persona-edit-main">
            <section className="persona-edit-section-heading">
              <div>
                <span>Nội dung Agent</span>
                <h2>Prompt làm việc</h2>
              </div>
              <p>
                Mỗi phần là một khối hướng dẫn riêng. Giữ câu chữ ngắn, rõ,
                kiểm soát được và dễ rà soát.
              </p>
            </section>

            <div className="persona-edit-section-list">
              {PERSONA_SECTIONS.map((section, index) => {
                const value = sectionValues[index] ?? "";
                const completed = value.trim().length > 0;

                return (
                  <section
                    key={section.title}
                    className="persona-edit-prompt-block"
                  >
                    <div className="persona-edit-prompt-head">
                      <div className="min-w-0">
                        <span>Phần {index + 1}</span>
                        <Label
                          htmlFor={`persona-section-${index}`}
                          className="persona-edit-prompt-title"
                        >
                          {section.title.replace(/^\d+\.\s*/, "")}
                        </Label>
                      </div>
                      <Badge
                        variant={completed ? "secondary" : "outline"}
                        className="shrink-0"
                      >
                        {completed ? "Đã điền" : "Trống"}
                      </Badge>
                    </div>
                    <Textarea
                      id={`persona-section-${index}`}
                      value={value}
                      onChange={(event) =>
                        updateSectionValue(index, event.target.value)
                      }
                      placeholder={section.hint}
                      rows={index === 2 || index === 3 ? 12 : 7}
                      className="persona-edit-textarea"
                    />
                  </section>
                );
              })}

              {extraMarkdown && (
                <section className="persona-edit-prompt-block">
                  <div className="persona-edit-prompt-head">
                    <div>
                      <span>Bổ sung</span>
                      <Label className="persona-edit-prompt-title">
                        Nội dung ngoài mẫu
                      </Label>
                    </div>
                  </div>
                  <Textarea
                    value={extraMarkdown}
                    onChange={(event) => setExtraMarkdown(event.target.value)}
                    rows={6}
                    className="persona-edit-textarea is-mono"
                  />
                </section>
              )}
            </div>
          </main>

          <aside className="persona-edit-rail">
            <section className="persona-edit-rail-card">
              <div className="persona-edit-rail-title">
                <BotMessageSquare className="size-4 text-primary" />
                Tự động follow-up
              </div>
              <p>Cấu hình theo mức ưu tiên của ứng viên.</p>
              <div className="persona-followup-editor-list">
                {FOLLOWUP_SCORE_ORDER.map((score) => {
                  const rule = followupRules[score];
                  return (
                    <div
                      key={score}
                      className="persona-followup-editor-card"
                    >
                      <div className="persona-followup-editor-head">
                        <div>
                          <strong>{FOLLOWUP_SCORE_LABELS[score]}</strong>
                          <span>Tính từ tin nhắn cuối của ứng viên</span>
                        </div>
                        <Switch
                          checked={rule.enabled}
                          onCheckedChange={(enabled) =>
                            updateFollowupRule(score, { enabled })
                          }
                          aria-label={`Bật follow-up ${FOLLOWUP_SCORE_LABELS[score]}`}
                        />
                      </div>

                      <div className="persona-followup-field">
                        <Label
                          htmlFor={`followup-cadence-${score}`}
                          className="persona-followup-label"
                        >
                          Mốc giờ
                        </Label>
                        <Input
                          id={`followup-cadence-${score}`}
                          value={rule.cadence_hours.join(" ")}
                          onChange={(event) =>
                            updateFollowupRule(score, {
                              cadence_hours: parseCadenceInput(
                                event.target.value,
                              ),
                            })
                          }
                          placeholder="VD: 10 22 46"
                          className="h-9 font-mono text-sm"
                        />
                      </div>

                      <div className="persona-followup-field">
                        <div className="persona-followup-label">
                          Nhóm áp dụng
                        </div>
                        <div className="persona-followup-stage-list">
                          {LEAD_STAGES.map((stage) => (
                            <label
                              key={stage.value}
                              className="persona-followup-stage"
                            >
                              <Checkbox
                                checked={rule.eligible_stages.includes(
                                  stage.value,
                                )}
                                onCheckedChange={(checked) =>
                                  toggleFollowupStage(
                                    score,
                                    stage.value,
                                    checked === true,
                                  )
                                }
                              />
                              <span>{stage.label}</span>
                            </label>
                          ))}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>

            <section className="persona-edit-rail-card">
              <div className="persona-edit-rail-title">
                <FileText className="size-4" />
                Ghi chú riêng tư
              </div>
              <Label htmlFor="persona-notes" className="text-sm font-semibold">
                Chỉ dùng nội bộ
              </Label>
              <Textarea
                id="persona-notes"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={4}
                className="persona-edit-notes"
              />
            </section>
          </aside>
        </div>

        <footer className="persona-edit-savebar">
          {extraActions}
          <Button type="submit" className="sm:min-w-32" disabled={submitting}>
            {submitting ? (
              <>
                <Loader2 className="size-4 animate-spin" />
                Đang lưu...
              </>
            ) : (
              submitLabel
            )}
          </Button>
        </footer>
      </form>
    </div>
  );
};

export { PersonaForm };
