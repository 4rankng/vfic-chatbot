import { lazy, Suspense } from "react";

const KnowledgeIngestPanel = lazy(() =>
  import("./KnowledgeIngestPanel").then((m) => ({
    default: m.KnowledgeIngestPanel,
  })),
);

export const MobileDashboard = () => (
  <Suspense fallback={null}>
    <KnowledgeIngestPanel variant="mobile" />
  </Suspense>
);
