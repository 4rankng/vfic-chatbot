import { describe, expect, it } from "vitest";

import editorStyles from "../conversations/inbox/mobile-persona-editor.css?raw";
import responsiveStyles from "../conversations/inbox/personas-responsive.css?raw";
import studioStyles from "../conversations/inbox/personas-studio.css?raw";
import assignmentsSource from "./PersonaAssignments.tsx?raw";
import editSource from "./PersonaEdit.tsx?raw";
import formSource from "./PersonaForm.tsx?raw";
import listSource from "./PersonaList.tsx?raw";

describe("Agent workspace layout regressions", () => {
  it("keeps the Agent overview flat with one clear edit action", () => {
    expect(listSource).not.toContain("tt-card");
    expect(listSource).not.toContain("Sửa prompt");
    expect(listSource).not.toContain("Đang xem");
    expect(listSource.match(/onEdit\(persona\)/g) ?? []).toHaveLength(1);
    expect(studioStyles).toMatch(
      /\.persona-studio-layout\s*\{[\s\S]*border:\s*0;[\s\S]*border-radius:\s*0;/,
    );
  });

  it("uses comfortable Agent overview controls", () => {
    expect(studioStyles).toMatch(
      /\.persona-page-shell \.persona-agent-picker \.persona-studio-command\s*\{[\s\S]*min-height:\s*44px/,
    );
    expect(studioStyles).toMatch(
      /\.persona-page-shell \.persona-agent-picker \.persona-create-action\s*\{[\s\S]*min-height:\s*44px\s*!important;[\s\S]*height:\s*44px\s*!important/,
    );
    expect(studioStyles).toMatch(
      /\.persona-page-shell \.persona-overview-edit-action\s*\{[\s\S]*min-height:\s*44px;[\s\S]*height:\s*44px/,
    );
  });

  it("uses compact controls when the Agent directory is embedded in settings", () => {
    expect(responsiveStyles).toMatch(
      /@media \(min-width: 761px\)[\s\S]*\.settings-embedded-resource \.persona-studio-layout\s*\{[\s\S]*grid-template-columns:\s*minmax\(208px, 224px\) minmax\(0, 1fr\)/,
    );
    expect(responsiveStyles).toMatch(
      /\.settings-embedded-resource[\s\S]*\.persona-agent-picker[\s\S]*\.persona-create-action\s*\{[\s\S]*width:\s*auto;[\s\S]*height:\s*34px\s*!important/,
    );
    expect(responsiveStyles).toMatch(
      /\.settings-embedded-resource \.persona-studio-section\s*\{[\s\S]*padding:\s*14px 16px/,
    );
  });

  it("keeps editor metrics and secondary sections on one flat plane", () => {
    expect(editorStyles).toMatch(
      /\.persona-editor-status-strip\s*\{[\s\S]*border:\s*0;[\s\S]*border-radius:\s*0;[\s\S]*background:\s*transparent/,
    );
    expect(editorStyles).toMatch(
      /\.persona-edit-rail-card\s*\{[\s\S]*border:\s*0;[\s\S]*border-radius:\s*0;[\s\S]*background:\s*transparent/,
    );
    expect(editSource.match(/Đang bật/g) ?? []).toHaveLength(1);
  });

  it("keeps long-form actions and follow-up controls easy to operate", () => {
    expect(editorStyles).toMatch(
      /\.inbox-bg-container \.app\.persona-app \.persona-center-panel\s*\{[\s\S]*overflow-y:\s*auto/,
    );
    expect(editorStyles).toMatch(
      /@media \(max-width: 760px\)[\s\S]*\.inbox-bg-container \.app\.persona-app \.persona-workspace-content\s*\{[\s\S]*overflow-y:\s*visible/,
    );
    expect(editorStyles).toMatch(
      /@media \(max-width: 760px\)[\s\S]*\.inbox-bg-container \.app\.persona-app \.persona-center-panel\s*\{[\s\S]*overflow-y:\s*visible/,
    );
    expect(editorStyles).toMatch(
      /\.persona-edit-surface\s*\{[\s\S]*overflow:\s*visible/,
    );
    expect(editorStyles).toMatch(
      /\.persona-edit-savebar\s*\{[\s\S]*position:\s*sticky;[\s\S]*bottom:\s*0;/,
    );
    expect(editorStyles).toMatch(
      /\.persona-followup-stage\s*\{[\s\S]*min-height:\s*44px/,
    );
    expect(editorStyles).toMatch(
      /\.persona-followup-switch-target\s*\{[\s\S]*width:\s*44px;[\s\S]*height:\s*44px/,
    );
    expect(editorStyles).toMatch(
      /\.persona-followup-editor-card \[data-slot="input"\],[\s\S]*min-height:\s*44px;[\s\S]*height:\s*44px/,
    );
    expect(formSource.match(/aria-busy=\{/g) ?? []).toHaveLength(2);
    expect(assignmentsSource).toContain("aria-busy={feedback.pending}");
  });

  it("keeps empty prompt guidance inside the opened editor", () => {
    expect(formSource).toContain("placeholder={section.hint}");
    expect(formSource).not.toContain(": section.hint}");
  });
});
