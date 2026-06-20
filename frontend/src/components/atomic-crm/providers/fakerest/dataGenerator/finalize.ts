import type { Db } from "./types";

export const finalize = (db: Db) => {
  // set contact status according to the latest note
  db.contact_notes
    .sort(
      (a, b) =>
        new Date(a.date ?? 0).valueOf() - new Date(b.date ?? 0).valueOf(),
    )
    .forEach((note) => {
      const contact = db.contacts[note.contact_id as number];
      if (contact && note.status) {
        contact.status = note.status as "cold" | "warm" | "hot";
      }
    });
};
