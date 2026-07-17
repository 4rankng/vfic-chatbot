# Knowledge Base workflow

Each Agent is attached to exactly one standalone Knowledge Base (KB). A KB may be shared by multiple Agents and remains after an Agent is removed.

- **RAG KB:** contains one or more Projects. Each Project represents a factory/project and retains its existing files, versions, companies, and jobs. RAG catalog, FAQ, document retrieval, and active-job lookup are scoped to the active Agent's RAG KB. Its detail view lists Projects, factory names and aliases, document counts, and active-job counts; an administrator can attach an unassigned Project there.
- **Direct-context KB:** contains exactly one `.txt` or `.md` file. The file is supplied in full with bounded recent conversation history in one model call. It never uses the ingestion pipeline, FAQ bypass, active-job lookup, embeddings, retrieval, or tools.

Administrators create KBs under **Cài đặt → Knowledge Base**, then select one when creating or editing an Agent. Projects must select a RAG KB. Direct KB configuration shows the active model capacity; save is rejected if the text cannot fit safely.

For RAG knowledge, every administrator upload (including pasted text) creates a new KB release scoped to the selected Project. The release enters offline ingestion and is not used by the agent until it is READY and an administrator publishes it. Publishing makes that Project release active.

Knowledge ingestion is fixed to the recruitment workflow. The product does not expose generic ingestion templates, industry starter packs, template assignment, structured-fact, or ingest-run review APIs. A release contains text sources, chunks, embeddings, and source provenance; it never creates or changes live job vacancy, salary, or status data.

The one-time production mapping is operational data, not application configuration: rename the existing global Agent to `default`, create RAG KB `vfic`, and attach legacy Project `lg-display` through the parameterized bootstrap endpoint. Perform that only as part of an approved production release with a fresh backup.
