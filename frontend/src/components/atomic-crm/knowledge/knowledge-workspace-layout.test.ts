import { describe, expect, it } from "vitest";

import featureStyles from "../conversations/inbox/features.css?raw";
import responsiveStyles from "../conversations/inbox/personas-responsive.css?raw";
import editSource from "./KnowledgeSourceEdit.tsx?raw";
import showSource from "./KnowledgeSourceShow.tsx?raw";

describe("knowledge source workspace layout", () => {
  it("keeps source navigation beside selected content on desktop", () => {
    expect(featureStyles).toMatch(
      /\.knowledge-source-workspace\s*\{[^}]*display:\s*grid[^}]*grid-template-columns:\s*minmax\(280px, 340px\) minmax\(0, 1fr\)/,
    );
    expect(featureStyles).toMatch(
      /\.knowledge-source-navigation\s*\{[^}]*border-right:\s*1px solid var\(--border\)/,
    );
    expect(featureStyles).toMatch(
      /\.knowledge-source-detail \.knowledge-detail-panel\s*\{[^}]*border-top:\s*0/,
    );
  });

  it("stacks the selected content below the source list on phones", () => {
    expect(responsiveStyles).toMatch(
      /@media \(max-width: 760px\)[\s\S]*?\.knowledge-source-workspace\s*\{[^}]*display:\s*block/,
    );
    expect(responsiveStyles).toMatch(
      /\.knowledge-source-navigation\s*\{[^}]*border-right:\s*0[^}]*border-bottom:\s*1px solid var\(--border\)/,
    );
    expect(responsiveStyles).toMatch(
      /\.knowledge-source-detail \.knowledge-detail-panel\s*\{[^}]*min-height:\s*auto[^}]*padding:\s*16px 0 0/,
    );
  });

  it("keeps every source and pagination control at least 44px tall", () => {
    expect(featureStyles).toMatch(
      /\.knowledge-page-shell \.knowledge-source-navigation button,[\s\S]*?height:\s*44px !important/,
    );
    expect(featureStyles).toMatch(
      /\.knowledge-page-shell \.knowledge-source-pagination a\s*\{[^}]*min-width:\s*44px/,
    );
  });

  it("keeps dedicated source subpages flat and task-focused", () => {
    expect(editSource).not.toContain("@/components/ui/card");
    expect(showSource).not.toContain("@/components/ui/card");
    expect(showSource).toContain("KnowledgeDetailPanel");
    expect(featureStyles).toMatch(
      /\.knowledge-source-edit-form\s*\{[^}]*border-block:\s*1px solid var\(--border\)/,
    );
    expect(featureStyles).toMatch(
      /\.knowledge-source-edit-fields\s*\{[^}]*grid-template-columns:\s*152px minmax\(0, 1fr\)/,
    );
    expect(responsiveStyles).toMatch(
      /@media \(max-width: 760px\)[\s\S]*?\.knowledge-source-edit-fields\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/,
    );
  });
});
