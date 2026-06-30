import { lazy, Suspense } from "react";

const KnowledgeIngestPanel = lazy(() =>
  import("./KnowledgeIngestPanel").then((m) => ({
    default: m.KnowledgeIngestPanel,
  })),
);

export const Dashboard = () => (
  <Suspense fallback={null}>
    <KnowledgeIngestPanel variant="desktop" />
  </Suspense>
);
