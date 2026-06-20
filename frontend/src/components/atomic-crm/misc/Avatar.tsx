// Compatibility shim. The original Avatar component lived in `contacts/Avatar`,
// but that folder was deleted during the Contact→Lead rename. Provide a small
// placeholder so the misc/ContactOption renderer compiles.
import {
  AvatarFallback,
  AvatarImage,
  Avatar as ShadcnAvatar,
} from "@/components/ui/avatar";
import { useRecordContext } from "ra-core";

import type { Contact } from "../types";

export const Avatar = (props: {
  record?: Contact;
  width?: 20 | 25 | 40;
  height?: 20 | 25 | 40;
  title?: string;
}) => {
  const ctx = useRecordContext<Contact>();
  const r = props.record ?? ctx;
  if (!r?.first_name && !r?.last_name) return null;
  const size = props.width ?? props.height ?? 40;
  const sizeClass =
    size === 20 ? "w-5 h-5" : size === 25 ? "w-6 h-6" : "w-10 h-10";
  return (
    <ShadcnAvatar className={sizeClass} title={props.title}>
      <AvatarImage src={r.avatar?.src ?? undefined} />
      <AvatarFallback className="text-[10px]">
        {(r.first_name?.charAt(0) ?? "").toUpperCase()}
        {(r.last_name?.charAt(0) ?? "").toUpperCase()}
      </AvatarFallback>
    </ShadcnAvatar>
  );
};
