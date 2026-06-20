import { datatype, lorem, random } from "faker/locale/en_US";
import type { Identifier } from "ra-core";

import type { Db } from "./types";
import { randomDate } from "./utils";

export const generateDealNotes = (db: Db) => {
  return Array.from(Array(300).keys()).map((id) => {
    const deal = random.arrayElement(db.deals);
    return {
      id,
      deal_id: deal.id,
      text: lorem.paragraphs(datatype.number({ min: 1, max: 4 })),
      date: randomDate(
        new Date(db.deals[deal.id as number].created_at ?? Date.now()),
      ).toISOString(),
      sales_id: (deal.sales_id ?? 0) as Identifier,
    };
  });
};
