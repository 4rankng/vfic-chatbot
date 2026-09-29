import {
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type ReactNode,
} from "react";
import { useGetList, useNotify, useTranslate } from "ra-core";
import { Badge } from "@/components/base/badges/badges";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { InputBase } from "@/components/base/input/input";
import { Label } from "@/components/base/input/label";
import { TextAreaBase } from "@/components/base/textarea/textarea";
import { Toggle } from "@/components/base/toggle/toggle";
import { Select as UntitledSelect } from "@/components/base/select/select";
import type { SelectItemType } from "@/components/base/select/select-shared";
import {
  BotMessageSquare,
  ChevronDown,
  Download,
  FileText,
  LoaderCircle,
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
} from "./domain/personaMarkdown";
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
  const translate = useTranslate();
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
  // Same visible copy the Radix select rendered: name, then the access mode.
  const knowledgeBaseItems: SelectItemType[] = knowledgeBases.map(
    (knowledgeBase) => ({
      id: knowledgeBase.id,
      label: `${knowledgeBase.name} · ${
        knowledgeBase.mode === "RAG" ? "RAG" : "Ngữ cảnh trực tiếp"
      }`,
    }),
  );
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
            <InputBase
              id="persona-name"
              data-slot="input"
              ref={nameInputRef}
              value={name}
              aria-invalid={nameError ? true : undefined}
              onChange={(event) => {
                setName(event.target.value);
                if (nameError) setNameError(null);
              }}
              wrapperClassName="uu-scope h-11 lg:max-w-xl"
              inputClassName="text-control"
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
            {/* Untitled UI v8 `ComboBox` (React Aria) instead of the Radix
                select: the knowledge-base list is dynamic and unbounded, so the
                field earns the type-ahead a plain select cannot give it. The
                Radix select is replaced, not nested inside it.

                `validationBehavior="aria"` is required, not cosmetic: React
                Aria's default `native` behaviour sets the `required` attribute
                on the input, the browser then blocks the form's submit before
                this component's own validation runs, and no Vietnamese error
                message ever renders. This form validates in JavaScript, like
                every other react-admin form in the console.

                `uu-scope` is required because the control is built on the same
                input surface as `base/input`, which paints `bg-primary` -- one
                of the four names the console and the library both define. */}
            <UntitledSelect.ComboBox
              className="uu-scope lg:max-w-xl"
              label="Knowledge Base"
              placeholder="Chọn Knowledge Base"
              items={knowledgeBaseItems}
              selectedKey={knowledgeBaseId || null}
              onSelectionChange={(key) => {
                setKnowledgeBaseId(key === null ? "" : String(key));
                setKnowledgeBaseError(null);
              }}
              validationBehavior="aria"
              isRequired
              isDisabled={knowledgeBasesPending || knowledgeBases.length === 0}
              isInvalid={Boolean(knowledgeBaseError)}
            >
              {(item: SelectItemType) => (
                <UntitledSelect.Item id={item.id} label={item.label} />
              )}
            </UntitledSelect.ComboBox>
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
              color="secondary"
              size="md"
              data-slot="button"
              className="tt-btn-touch uu-scope"
              onClick={downloadTemplate}
              iconLeading={Download}
            >
              Tải mẫu
            </Button>
            <Button
              type="button"
              color="secondary"
              size="md"
              data-slot="button"
              className="tt-btn-touch uu-scope"
              isDisabled={importing || !knowledgeBaseId}
              aria-busy={importing}
              onClick={() => fileInputRef.current?.click()}
              iconLeading={
                importing ? (
                  <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" />
                ) : (
                  <Upload className="size-4" />
                )
              }
            >
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
                        {completed ? (
                          <small>{value.trim().replace(/\s+/g, " ")}</small>
                        ) : null}
                      </div>
                      <span className="persona-edit-prompt-state">
                        <Badge
                          type="pill-color"
                          size="md"
                          color={completed ? "success" : "gray"}
                          className="shrink-0"
                        >
                          {completed ? "Đã điền" : "Trống"}
                        </Badge>
                        <ChevronDown className="size-4" aria-hidden="true" />
                      </span>
                    </summary>
                    <div className="persona-edit-prompt-content">
                      <TextAreaBase
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
                      <Badge type="pill-color" size="md" color="success">
                        Đã điền
                      </Badge>
                      <ChevronDown className="size-4" aria-hidden="true" />
                    </span>
                  </summary>
                  <div className="persona-edit-prompt-content">
                    <Label htmlFor="persona-extra-markdown" className="sr-only">
                      Nội dung ngoài mẫu
                    </Label>
                    <TextAreaBase
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
              <p>{translate("personas.followup_schedule_hint")}</p>
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
                          <Toggle
                            isSelected={rule.enabled}
                            onChange={(enabled) =>
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
                        <InputBase
                          id={`followup-cadence-${score}`}
                          data-slot="input"
                          value={rule.cadence_hours.join(" ")}
                          onChange={(event) =>
                            updateFollowupRule(score, {
                              cadence_hours: parseFollowupCadenceHours(
                                event.target.value,
                              ),
                            })
                          }
                          placeholder="VD: 10 22 46"
                          wrapperClassName="uu-scope h-11"
                          inputClassName="font-mono text-control"
                        />
                      </div>

                      <div className="persona-followup-field">
                        <div className="persona-followup-label">
                          Nhóm áp dụng
                        </div>
                        <div className="persona-followup-stage-list">
                          {LEAD_STAGES.map((stage) => (
                            <Checkbox
                              key={stage.value}
                              className="persona-followup-stage uu-scope [&_p]:min-w-0 [&_p]:truncate"
                              size="sm"
                              label={stage.label}
                              isSelected={rule.eligible_stages.includes(
                                stage.value,
                              )}
                              onChange={(checked) =>
                                toggleFollowupStage(
                                  score,
                                  stage.value,
                                  checked,
                                )
                              }
                            />
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
              <TextAreaBase
                id="persona-notes"
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
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
            data-slot="button"
            className="tt-btn-touch uu-scope sm:min-w-32"
            isDisabled={submitting}
            aria-busy={submitting}
            iconLeading={
              submitting ? (
                <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" />
              ) : undefined
            }
          >
            {submitting ? translate("crm.common.saving") : submitLabel}
          </Button>
        </footer>
      </form>
    </div>
  );
};

export { PersonaForm };
