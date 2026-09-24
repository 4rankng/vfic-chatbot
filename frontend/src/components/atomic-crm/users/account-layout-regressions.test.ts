import { describe, expect, it } from "vitest";

import featureStyles from "../conversations/inbox/features.css?raw";
import responsiveStyles from "../conversations/inbox/personas-responsive.css?raw";
import profileSource from "../settings/ProfilePage.tsx?raw";
import userCreateSource from "./UserCreate.tsx?raw";
import userEditSource from "./UserEdit.tsx?raw";
import userStyles from "./users.css?raw";

describe("account layout regressions", () => {
  it("keeps account forms on one flat content plane", () => {
    expect(userEditSource).not.toContain("@/components/ui/card");
    expect(profileSource).not.toContain("@/components/ui/card");
    expect(userStyles).toMatch(
      /\.user-account-form\s*\{[\s\S]*border-block:\s*1px solid var\(--tt-border\)[\s\S]*background:\s*transparent/,
    );
  });

  it("uses responsive fields and comfortable account actions", () => {
    expect(userStyles).toMatch(
      /\.user-account-field-grid\s*\{[\s\S]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/,
    );
    expect(userStyles).toMatch(
      /@media \(max-width: 760px\)[\s\S]*\.user-account-field-grid\s*\{[\s\S]*grid-template-columns:\s*minmax\(0, 1fr\)/,
    );
    expect(userStyles).toMatch(
      /\.user-account-form-actions \[data-slot="button"\],[\s\S]*height:\s*44px !important/,
    );
  });

  it("keeps profile settings flat, responsive, and non-gradient", () => {
    expect(profileSource).toContain('className="profile-section');
    expect(featureStyles).toMatch(
      /\.profile-command-header\s*\{[\s\S]*border-radius:\s*0[\s\S]*background:\s*transparent/,
    );
    expect(responsiveStyles).toMatch(
      /\.profile-field-grid\s*\{[\s\S]*grid-template-columns:\s*minmax\(0, 1fr\)/,
    );
  });

  it("shows progress while account changes are submitted", () => {
    expect(userCreateSource).toContain("Đang tạo");
    expect(profileSource).toContain("isSaving");
  });

  it("validates required account details before sending data", () => {
    expect(userCreateSource).toContain('required("Vui lòng nhập thông tin.")');
    expect(userCreateSource).toContain('email("Email chưa đúng định dạng.")');
    expect(userCreateSource).toContain(
      "validate={[REQUIRED_FIELD, VALID_EMAIL]}",
    );
    expect(userEditSource).toContain("validate={REQUIRED_FIELD}");
  });
});
