---
name: ak:mcp-builder
description: Build MCP servers for LLM-external service integration. Use for FastMCP (Python), MCP SDK (Node/TypeScript), tool design, API integration, resource providers.
user-invocable: true
when_to_use: "Invoke when building an MCP server or tool surface."
category: engineering
keywords: [MCP, server, tools, integration]
license: Complete terms in LICENSE.txt
argument-hint: "[service or API to integrate]"
metadata:
  author: agentkit
  version: "1.1.1"
---

# MCP server development

Define the user task and first tool contract before selecting infrastructure. Inspect the
project SDK/version and transport. Read only official protocol/API sections needed for that
tool: authentication, input/output schema, pagination, errors/retries and transport as relevant.
Do not require the full specification or every API endpoint before building one tool.

## Implement one complete tool

Choose the matching `reference/python-mcp-server.md` or `reference/node-mcp-server.md` and
relevant guidance from `reference/mcp-best-practices.md`. Implement a working path from
validated input through authorized API behavior to useful bounded output. Extract shared
helpers only after repeated logic or a real boundary warrants them.

Use accurate readOnly/destructive/idempotent/openWorld annotations, input constraints,
actionable errors and proper cancellation/timeouts. Match authentication and scopes to the
actual operation; annotations are not enforcement. Test invalid/auth/pagination/retry paths
where they apply. Detailed implementation guidance: `references/tool-implementation.md`.

## Verify and expand

Compile/import-check the server, drive it with an actual client or harness, and verify the
user task completes with correct output and effects. Use `references/evaluation-authoring.md`
and `reference/evaluation.md` for task-based evaluations, not only tool-schema checks.
Use bounded/harness-owned server processes; record and clean up those started for the task.
Add further tools only to fulfill the requested workflow. Report working contracts, observed
client outcomes and missing capabilities instead of claiming completion from registration.
