import {
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type ReactNode,
} from "react";
import { useGetList, useNotify } from "ra-core";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  BotMessageSquare,
  ChevronDown,
  Download,
  FileText,
  Upload,
} from "lucide-react";
import { importPersona } from "./personaService";
import {
  LEAD_STAGES,
  type LeadScoreValue,
  type LeadStageValue,
  type PersonaFollowupRule,
  type KnowledgeBase,
  type PersonaFollowupRules,
} from "../types";
import {
  composePersonaMarkdown,
  parsePersonaMarkdown,
  PERSONA_SECTIONS,
  PERSONA_TEMPLATE,
  type PersonaSectionValues,
} from "./personaMarkdown";
import {
  FOLLOWUP_SCORE_ORDER,
  normalizePersonaFollowupRules,
  parseFollowupCadenceHours,
} from "./domain/followupRules";

const PERSONA_TEMPLATE_FILENAME = "mau-agent-vfic.md";

const FOLLOWUP_SCORE_LABELS: Record<LeadScoreValue, string> = {
  hot: "Hot",
  warm: "Warm",
  not_interested: "Cold",
};

export interface PersonaValues {
  name: string;
  body_md: string;
  notes: string;
  knowledge_base_id: string;
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
  const [knowledgeBaseId, setKnowledgeBaseId] = useState(
    initial.knowledge_base_id,
  );
  const [followupRules, setFollowupRules] = useState<PersonaFollowupRules>(() =>
    normalizePersonaFollowupRules(initial.followup_rules),
  );
  const [submitting, setSubmitting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [nameError, setNameError] = useState<string | null>(null);
  const [knowledgeBaseError, setKnowledgeBaseError] = useState<string | null>(
    null,
  );
  const { data: knowledgeBases = [], isPending: knowledgeBasesPending } =
    useGetList<KnowledgeBase>("knowledge_bases", {
      pagination: { page: 1, perPage: 100 },
      sort: { field: "name", order: "ASC" },
      filter: {},
    });
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
    if (!knowledgeBaseId) {
      setKnowledgeBaseError("Vui lòng chọn Knowledge Base cho Agent.");
      return;
    }
    setNameError(null);
    setKnowledgeBaseError(null);
    setSubmitting(true);
    try {
      await onSubmit({
        name,
        body_md: bodyMd,
        notes,
        knowledge_base_id: knowledgeBaseId,
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

    if (!knowledgeBaseId) {
      setKnowledgeBaseError("Chọn Knowledge Base trước khi nhập file Agent.");
      return;
    }

    const fileName = file.name.toLowerCase();
    if (!fileName.endsWith(".md") && !fileName.endsWith(".txt")) {
      notify("Vui lòng tải lên file .md hoặc .txt.", { type: "warning" });
      return;
    }

    setImporting(true);
    try {
      const persona = await importPersona(file, knowledgeBaseId);
      const parsed = parsePersonaMarkdown(persona.body_md);
      // Populate form with imported data
      setName(persona.name);
      setSectionValues(parsed.sections);
      setExtraMarkdown(parsed.extraMarkdown);
      if (persona.notes != null) setNotes(persona.notes);
      if (persona.followup_rules) {
        setFollowupRules(normalizePersonaFollowupRules(persona.followup_rules));
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
        <section className="persona-edit-identity">
          <div className="persona-edit-name-field">
            <Label htmlFor="persona-name" className="text-label font-semibold">
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
              className="h-11 text-control lg:max-w-xl"
            />
            {nameError ? (
              <p
                role="alert"
                className="text-helper font-medium text-destructive"
              >
                {nameError}
              </p>
            ) : null}
          </div>
          <div className="persona-edit-name-field">
            <Label
              htmlFor="persona-knowledge-base"
              className="text-label font-semibold"
            >
              Knowledge Base{" "}
              <span aria-hidden="true" className="text-destructive">
                *
              </span>
            </Label>
            <Select
              value={knowledgeBaseId}
              onValueChange={(value) => {
                setKnowledgeBaseId(value);
                setKnowledgeBaseError(null);
              }}
              disabled={knowledgeBasesPending || knowledgeBases.length === 0}
            >
              <SelectTrigger
                id="persona-knowledge-base"
                className="h-11 text-control lg:max-w-xl"
              >
                <SelectValue placeholder="Chọn Knowledge Base" />
              </SelectTrigger>
              <SelectContent>
                {knowledgeBases.map((knowledgeBase) => (
                  <SelectItem key={knowledgeBase.id} value={knowledgeBase.id}>
                    {knowledgeBase.name} ·{" "}
                    {knowledgeBase.mode === "RAG"
                      ? "RAG"
                      : "Ngữ cảnh trực tiếp"}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {knowledgeBaseError ? (
              <p
                role="alert"
                className="text-helper font-medium text-destructive"
              >
                {knowledgeBaseError}
              </p>
            ) : knowledgeBases.length === 0 && !knowledgeBasesPending ? (
              <p className="text-helper text-muted-foreground">
                Tạo Knowledge Base trước khi tạo Agent.
              </p>
            ) : null}
          </div>
        </section>

        <details
          className="persona-edit-import-strip"
          aria-label="Nhập file cấu hình Agent"
        >
          <summary>
            <div className="persona-edit-import-copy">
              <span className="persona-edit-import-icon" aria-hidden="true">
                <Upload className="size-4" />
              </span>
              <div>
                <strong>Nhập từ file</strong>
                <p>Markdown hoặc văn bản thuần.</p>
              </div>
            </div>
            <ChevronDown className="size-4" aria-hidden="true" />
          </summary>
          <div className="persona-edit-import-actions">
            <Button
              type="button"
              variant="outline"
              className="tt-btn-touch"
              onClick={downloadTemplate}
            >
              <Download className="size-4" />
              Tải mẫu
            </Button>
            <Button
              type="button"
              variant="outline"
              className="tt-btn-touch"
              disabled={importing || !knowledgeBaseId}
              aria-busy={importing}
              onClick={() => fileInputRef.current?.click()}
            >
              {importing ? (
                <span
                  className="tt-loading tt-loading-spinner tt-loading-sm"
                  aria-hidden="true"
                />
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
        </details>

        <div className="persona-edit-grid">
          <div className="persona-edit-main">
            <section className="persona-edit-section-heading">
              <div>
                <span>Nội dung</span>
                <h2>Prompt Agent</h2>
              </div>
              <p>
                {completedSectionCount}/7 phần ·{" "}
                {contentLength.toLocaleString("vi-VN")} ký tự
              </p>
            </section>

            <div className="persona-edit-section-list">
              {PERSONA_SECTIONS.map((section, index) => {
                const value = sectionValues[index] ?? "";
                const completed = value.trim().length > 0;

                return (
                  <details
                    key={section.title}
                    className="persona-edit-prompt-block"
                  >
                    <summary className="persona-edit-prompt-head">
                      <div className="persona-edit-prompt-copy">
                        <span>Phần {index + 1}</span>
                        <strong
                          id={`persona-section-title-${index}`}
                          className="persona-edit-prompt-title"
                        >
                          {section.title.replace(/^\d+\.\s*/, "")}
                        </strong>
                        <small>
                          {completed
                            ? value.trim().replace(/\s+/g, " ")
                            : section.hint}
                        </small>
                      </div>
                      <span className="persona-edit-prompt-state">
                        <Badge
                          variant={completed ? "secondary" : "outline"}
                          className="shrink-0"
                        >
                          {completed ? "Đã điền" : "Trống"}
                        </Badge>
                        <ChevronDown className="size-4" aria-hidden="true" />
                      </span>
                    </summary>
                    <div className="persona-edit-prompt-content">
                      <Textarea
                        id={`persona-section-${index}`}
                        aria-labelledby={`persona-section-title-${index}`}
                        value={value}
                        onChange={(event) =>
                          updateSectionValue(index, event.target.value)
                        }
                        placeholder={section.hint}
                        rows={index === 2 || index === 3 ? 12 : 7}
                        className="persona-edit-textarea"
                      />
                    </div>
                  </details>
                );
              })}

              {extraMarkdown && (
                <details className="persona-edit-prompt-block">
                  <summary className="persona-edit-prompt-head">
                    <div className="persona-edit-prompt-copy">
                      <span>Bổ sung</span>
                      <strong className="persona-edit-prompt-title">
                        Nội dung ngoài mẫu
                      </strong>
                      <small>{extraMarkdown.trim().replace(/\s+/g, " ")}</small>
                    </div>
                    <span className="persona-edit-prompt-state">
                      <Badge variant="secondary">Đã điền</Badge>
                      <ChevronDown className="size-4" aria-hidden="true" />
                    </span>
                  </summary>
                  <div className="persona-edit-prompt-content">
                    <Label htmlFor="persona-extra-markdown" className="sr-only">
                      Nội dung ngoài mẫu
                    </Label>
                    <Textarea
                      id="persona-extra-markdown"
                      value={extraMarkdown}
                      onChange={(event) => setExtraMarkdown(event.target.value)}
                      rows={6}
                      className="persona-edit-textarea is-mono"
                    />
                  </div>
                </details>
              )}
            </div>
          </div>

          <aside className="persona-edit-rail">
            <section className="persona-edit-rail-card">
              <div className="persona-edit-rail-title">
                <BotMessageSquare className="size-4 text-primary" />
                Follow-up
              </div>
              <p>Lịch nhắc theo mức ưu tiên.</p>
              <div className="persona-followup-editor-list">
                {FOLLOWUP_SCORE_ORDER.map((score) => {
                  const rule = followupRules[score];
                  return (
                    <div key={score} className="persona-followup-editor-card">
                      <div className="persona-followup-editor-head">
                        <div>
                          <strong>{FOLLOWUP_SCORE_LABELS[score]}</strong>
                          <span>Tính từ tin nhắn cuối của ứng viên</span>
                        </div>
                        <label className="persona-followup-switch-target">
                          <Switch
                            checked={rule.enabled}
                            onCheckedChange={(enabled) =>
                              updateFollowupRule(score, { enabled })
                            }
                            aria-label={`Bật follow-up ${FOLLOWUP_SCORE_LABELS[score]}`}
                          />
                        </label>
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
                              cadence_hours: parseFollowupCadenceHours(
                                event.target.value,
                              ),
                            })
                          }
                          placeholder="VD: 10 22 46"
                          className="h-11 font-mono text-control"
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
              <Label
                htmlFor="persona-notes"
                className="persona-edit-rail-title"
              >
                <FileText className="size-4" />
                Ghi chú nội bộ
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
          <Button
            type="submit"
            className="tt-btn-touch sm:min-w-32"
            disabled={submitting}
            aria-busy={submitting}
          >
            {submitting ? (
              <>
                <span
                  className="tt-loading tt-loading-spinner tt-loading-sm"
                  aria-hidden="true"
                />
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
