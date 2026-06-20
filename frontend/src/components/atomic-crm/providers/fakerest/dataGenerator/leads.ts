import { random } from "faker/locale/en_US";

import type { Lead } from "../../../types";
import type { Db } from "./types";
import { randomDate } from "./utils";

const LEAD_STAGES = [
  "NEW",
  "QUALIFIED",
  "CONTACTED",
  "INTERVIEWING",
  "OFFERED",
  "HIRED",
  "REJECTED",
];

const JOB_TITLES = [
  "Senior Frontend Developer",
  "Backend Engineer",
  "Full-stack Developer",
  "DevOps Engineer",
  "Mobile Developer (iOS)",
  "Mobile Developer (Android)",
  "QA Engineer",
  "Data Engineer",
  "Product Designer",
  "Tech Lead",
  "Engineering Manager",
  "Data Scientist",
  "Machine Learning Engineer",
  "Site Reliability Engineer",
];

const SALARY_RANGES = [
  "800 USD",
  "1000 USD",
  "1200 USD",
  "1500 USD",
  "1800 USD",
  "2000 USD",
  "2500 USD",
  "3000 USD",
  "3500 USD",
];

const VIETNAMESE_FIRST_NAMES = [
  "Nguyen Van",
  "Tran Thi",
  "Le Van",
  "Pham Thi",
  "Hoang Van",
  "Vu Thi",
  "Dang Van",
  "Bui Thi",
  "Do Van",
  "Ngo Thi",
];

const VIETNAMESE_LAST_NAMES = [
  "An",
  "Binh",
  "Cuong",
  "Dat",
  "Em",
  "Phong",
  "Giang",
  "Hieu",
  "Khanh",
  "Long",
  "Minh",
  "Nam",
  "Quan",
  "Son",
  "Tuan",
  "Vy",
];

export const generateLeads = (_db: Db, size = 500): Lead[] => {
  const leads: Lead[] = [];

  for (let i = 0; i < size; i++) {
    const firstName = random.arrayElement(VIETNAMESE_FIRST_NAMES);
    const lastName = random.arrayElement(VIETNAMESE_LAST_NAMES);
    const fullName = `${firstName} ${lastName}`;
    const stage = random.arrayElement(LEAD_STAGES);
    const createdAt = randomDate(
      new Date(Date.now() - 1000 * 60 * 60 * 24 * 90),
      new Date(),
    );
    const updatedAt = randomDate(new Date(createdAt), new Date());

    leads.push({
      id: i + 1,
      zalo_id: `zalo-${random.number({ min: 100000, max: 999999 })}`,
      name: fullName,
      phone: `+84 ${random.number({ min: 90, max: 99 })} ${random.number({
        min: 100,
        max: 999,
      })} ${random.number({ min: 100, max: 999 })}`,
      desired_job: random.arrayElement(JOB_TITLES),
      expected_salary: random.arrayElement(SALARY_RANGES),
      lead_score: random.number({ min: 0, max: 100 }),
      lead_stage: stage,
      created_at: createdAt.toISOString(),
      updated_at: updatedAt.toISOString(),
    });
  }

  return leads;
};