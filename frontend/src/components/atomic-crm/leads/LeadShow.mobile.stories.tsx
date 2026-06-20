import type { Meta } from "@storybook/react-vite";

import { LeadShow } from "./LeadShow";

import { StoryWrapper, buildLead } from "@/test/StoryWrapper";

const meta = {
  title: "Atomic CRM/Leads/Lead Show/Mobile",
  parameters: {
    layout: "fullscreen",
  },
  globals: {
    viewport: { value: "mobile1", isRotated: false },
  },
} satisfies Meta;

export default meta;

const successLeads = [
  buildLead({
    id: 106,
    name: "Nguyen Van A",
    phone: "+84 901 234 567",
    desired_job: "Senior Frontend Developer",
    expected_salary: "1500 USD",
    lead_score: 85,
    lead_stage: "QUALIFIED",
    zalo_id: "zalo-12345",
  }),
];

export const MobileSuccess = () => (
  <StoryWrapper data={{ leads: successLeads }}>
    <LeadShow id={106} resource="leads" />
  </StoryWrapper>
);
