---
type: system
title: JWT auth, RBAC, and capability registry
description: How authentication (JWT access + rotated refresh, argon2 hashing), authorization (admin / recruiter), and the code-reviewed capability registry form the access control surface — and how the frontend mirrors it.
tags: [auth, jwt, rbac, capabilities, argon2, parity, recruiter, admin]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-08T09:17:45.993Z
---

TingHire splits access control into three layers: **authentication**
(are you a known user with a valid token), **authorization** (which role do
you have and which routes may you call), and **capabilities** (what is the
closed-world set of product capabilities the kernel knows how to run). Each
layer is owned by a separate boundary so a misconfigured gate fails closed
without requiring the next layer to compensate.

## Authentication

JWT replaces Supabase Auth. `backend/app/core/security.py` issues and
verifies tokens; `backend/app/identity/application/authentication.py` wires
the application-level authenticator.

### Token shape

| Claim | Type | Notes |
|---|---|---|
| `sub` | str (user UUID) | Subject — the user's id |
| `type` | `"access"` \| `"refresh"` | One of the two token kinds |
| `ver` | int | User version — bumped on disable/delete so a rotated token cannot outlive the user |
| `iat`, `exp` | datetime (runtime) | Standard timestamps; the app only reads `ver`, not `iat`/`exp`, to avoid pinning jose's decoded types |

Settings (`backend/app/core/config.py`) define:

- `access_token_expire_minutes` (default `60`)
- `refresh_token_expire_days` (default `14`)
- `jwt_algorithm`, `jwt_secret`

`Settings.model_post_init` refuses to boot when `app_env != "development"`
and `jwt_secret` still equals the committed dev default — production must
set a real secret so admin JWTs cannot be forged from the public default.

### Crypto off the event loop

`passlib` (argon2) and `jose` (JWT) are CPU-bound and blocking. The async
helpers `hash_password` / `verify_password` / `_encode` / `decode_token` wrap
the sync primitives with `asyncio.to_thread` so a login burst cannot stall
the event loop and freeze in-flight webhooks or SSE streams. Sync
`*_sync` variants exist for the create-admin / migrate scripts; the async
app must never call them from an `async def`.

### Routes and rate limits

`backend/app/api/auth.py` exposes:

- `POST /api/v1/auth/login` — argon2 verify, returns TokenResponse.
- `POST /api/v1/auth/forgot-password` — issues a password-reset OTP via
  Resend (silently fails when `RESEND_API_KEY` is unset, see
  `app/main.py` startup warning).
- `POST /api/v1/auth/reset-password` — consumes the OTP.
- `POST /api/v1/auth/refresh` — rotates refresh tokens and rejects them if
  the user has since been disabled/deleted (ver check).
- `POST /api/v1/auth/change-password` — verifies the current password first.
- `GET /api/v1/auth/me` — current-user projection.

`backend/app/identity/infrastructure/rate_limits.py` applies Redis-backed
rate limits per route:

| Route | IP limit | Keyed limit |
|---|---|---|
| `/auth/login` | 10 / 60s | — |
| `/auth/forgot-password` | 5 / 300s | 3 / 900s per email |
| `/auth/reset-password` | 10 / 300s | 10 / 900s per email |
| `/auth/refresh` | 20 / 60s | — |

The defaults reflect the cost of argon2 verify (~50-200ms per attempt): a
credential-stuffing burst cannot pin the FastAPI workers.

## Authorization

Two roles live in `backend/app/identity/domain/role.py`:

| Role | Vietnamese | Scope |
|---|---|---|
| `admin` | _Quản trị_ | Full access. Manages users, integration credentials, all projects / personas / knowledge. |
| `recruiter` | _Tuyển dụng_ | Default role. Owns conversations, leads, follow-ups, knowledge curation. Cannot manage users or integration secrets. |

### Dependency gates

`backend/app/api/auth_dependencies.py` exposes the FastAPI dependencies:

```text
get_current_user     # validates Bearer JWT, loads the user
require_admin        # role == "admin"
require_recruiter    # role in {"admin", "recruiter"}
```

Both are implemented as thin wrappers over framework-free policy helpers in
`backend/app/access/application/roles.py`:

```python
def require_admin_access(principal):
    assert_admin_role(role_name(principal.role))
    return principal

def require_recruiter_access(principal):
    assert_recruiter_role(role_name(principal.role))
    return principal
```

The actual role check is `assert_admin_role` / `assert_recruiter_role` in
`backend/app/access/domain/policies.py`. `assert_recruiter_role` accepts
both `admin` and `recruiter` — admins implicitly pass every recruiter gate.
`require_admin` returns 403 for non-admins. The check raises
`AccessDeniedError`, which the dependency translates to `HTTP 403`.

The framework-free split (domain vs application) keeps RBAC testable
without spinning up FastAPI and lets the same policies be re-used by
other transports.

### Installation gate

`backend/app/api/installation_dependencies.py` gates every non-auth route
on the installation state — the first request after a fresh deploy must
walk the installation flow (admin bootstrap, admin-managed secrets,
default persona, etc.) before any other route is reachable. The dependency
runs after `get_current_user` so the same JWT can later be used post-install.

## Capability registry

The capability registry is the closed-world index of every product
capability the kernel knows how to run. It is not a plug-in system; it is a
code-reviewed set of declarations and a parity artifact.

### Contracts

`backend/app/capabilities/contracts.py` defines:

- `CapabilityDefinition` — `capability_id`, `dependencies`, `authority_class`
  (`"capability"` or `"channel"`), `api_routes`, `frontend_resources`,
  `dashboard_owner`, `conversation_slots`, `adapter_descriptor`.
- `IndustryPackDefinition` — `key`, `version`, `capability_ids`, `kernel_abi`,
  `compatible_operational_data`, `workflow_ids`, `terminology_keys`,
  `runtime_ready`.
- `ResolvedPack` — the pack, the selected capabilities, the
  `contract_hash`, and any `adapter_descriptors` whose capability selected
  them.
- `CapabilityAdapter` — a marker protocol for source-owned delegation
  adapters. Adapters are not exported in the contract JSON (they are
  resolved at runtime, not declared to consumers).

### Recruitment pack

`backend/app/capabilities/recruitment/definition.py` declares the
recruitment pack:

- `conversation` — base conversation lifecycle. api_route
  `/api/v1/conversations`, frontend resource `conversations`.
- `knowledge` — depends on `conversation`. api_route
  `/api/v1/knowledge`, frontend resources `knowledge_sources`,
  `projects`, `personas`.
- `candidate_intake` — depends on `conversation`. api_route
  `/api/v1/leads`, conversation slots `row`, `filters`, `context`,
  `actions`, has `DESCRIPTOR`.
- `job_advisory` — depends on `candidate_intake` + `knowledge`. api_route
  `/api/v1/jobs`, owns the dashboard.
- `channel.zalo` — depends on `conversation`. authority_class `"channel"`,
  frontend resource `settings`.

### Validation and resolution

`CapabilityRegistry` (`backend/app/capabilities/registry.py`):

- Rejects duplicate capability ids and duplicate routes/resources/slots
  inside one capability.
- Validates the dependency graph: every `dependencies` entry must itself
  be in the same pack.
- On `resolve(pack_key, pack_version, capability_ids, pack_contract_hash)`,
  it checks `PACK_CONTRACT_SCHEMA_VERSION`, `SUPPORTED_KERNEL_ABI`, the
  pack version, and the supplied `pack_contract_hash`. A mismatch raises
  `ValueError` — this is the runtime guard that prevents stale callers
  from binding to a pack whose contract has moved.

### Parity artifact

`backend/app/capabilities/recruitment_v1_contract.json` is the **shipped
non-executable contract** for the recruitment pack:

- Contains the `schema_version`, `contract_hash`, pack metadata, and each
  capability's static fields (no executable code, no adapter descriptors).
- The test `test_shipped_pack_export_is_canonical_non_executable_contract`
  asserts the exported dict equals the JSON byte-for-byte, the
  `contract_hash` is
  `2a7c602a2e222d14686fca6d86e12da34b0e2ce8ee6b4af32a95af7bd58622d9`, and
  no `"import"` / `"factory"` strings leak into the artifact.
- The companion test `test_recruitment_descriptor_is_source_owned_resolved_and_not_exported`
  asserts the adapter is reachable through `registry.resolve()` but never
  appears in `export_pack_contract()` — adapters are runtime-only.

Any change to a capability's static fields changes the contract hash, so a
downstream caller carrying a stale hash fails closed.

## Frontend parity

`frontend/src/components/atomic-crm/providers/commons/canAccess.ts`
mirrors the backend gate as a UX-layer filter:

```ts
const RECRUITER_RESOURCES = new Set(["conversations", "projects"]);

export const canAccess(role, params, availableResources) {
  if (role === "admin") return true;
  return RECRUITER_RESOURCES.has(params.resource);
}
```

Recruiters see `conversations` and `projects`; every other resource
(`users`, `bot_runs`, `knowledge_sources`, `personas`, …) is admin-only.
The comment in `canAccess.ts` is explicit: **"Real enforcement is the
FastAPI backend (`app/api/dependencies.py`); this is the UX layer."** The
console never relies on the client gate to keep secrets off-screen — every
admin-only API path returns 403 if the JWT does not carry the admin role.

## Layered guarantees

| Concern | Layer | Failure mode |
|---|---|---|
| Identity | `get_current_user` (JWT + `ver` check) | 401 if token missing, expired, or user disabled/deleted |
| Role | `require_admin` / `require_recruiter` | 403 if role insufficient |
| Installation | `installation_dependencies.require_installation` | Redirects to install flow until the install bootstrap completes |
| Public contract | `CapabilityRegistry.resolve` | `ValueError` on schema / kernel ABI / pack version / contract hash mismatch |
| UX gating | `canAccess(role, ...)` | Hides controls; cannot bypass server gates |

The four backend layers fail closed independently. The frontend mirror is a
UX hint, never a security boundary.
