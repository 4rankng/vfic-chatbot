import type { Meta } from "@storybook/react-vite";

import { LeadShow } from "./LeadShow";

import { StoryWrapper, buildLead } from "@/test/StoryWrapper";

const meta = {
  title: "Atomic CRM/Leads/Lead Show",
  parameters: {
    layout: "fullscreen",
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
    lead_score: "warm",
    lead_stage: "QUALIFIED",
    zalo_id: "zalo-12345",
  }),
];

export const DesktopSuccess = () => (
  <StoryWrapper data={{ leads: successLeads }}>
    <LeadShow id={106} resource="leads" />
  </StoryWrapper>
);

export const DesktopHighScore = () => (
  <StoryWrapper
    data={{
      leads: [
        buildLead({
          id: 107,
          name: "Tran Thi B",
          phone: "+84 902 999 888",
          desired_job: "Backend Engineer",
          expected_salary: "2000 USD",
          lead_score: "hot",
          lead_stage: "APPLIED",
          zalo_id: "zalo-67890",
        }),
      ],
    }}
  >
    <LeadShow id={107} resource="leads" />
  </StoryWrapper>
);
