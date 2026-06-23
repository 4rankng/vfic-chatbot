import { ArrowLeft } from "lucide-react";
import { useCreatePath, useResourceContext } from "ra-core";
import { Link } from "react-router";

import { cn } from "@/lib/utils";

export const LeadBreadcrumb = ({
  className,
  rootLabel = "Ứng viên",
}: {
  className?: string;
  rootLabel?: string;
}) => {
  const resource = useResourceContext();
  const createPath = useCreatePath();
  const listPath = resource ? createPath({ resource, type: "list" }) : "/leads";
  return (
    <nav
      aria-label="Đường dẫn"
      className={cn(
        "flex items-center gap-1.5 text-sm text-muted-foreground",
        className,
      )}
    >
      <Link
        to={listPath}
        className="inline-flex items-center gap-1 rounded-md px-2 py-1 transition-colors hover:bg-muted hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" />
        <span>{rootLabel}</span>
      </Link>
    </nav>
  );
};
