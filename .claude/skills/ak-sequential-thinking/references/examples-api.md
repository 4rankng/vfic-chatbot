# Example: API Design with Sequential Thinking

Use these illustrative domain records selectively. Report observable evidence, assumptions, alternatives and decisions; do not expose a private thought transcript or reproduce the numbering as a required protocol. Example facts are hypothetical, not evidence about the current project.
**Problem**: Design authentication API for multi-tenant SaaS.

## Incomplete proposal
"Use JWT with OAuth2. Add tenant ID to claims. Implement refresh tokens."
(Misses edge cases, scaling, security)

## Evidence and decision record

```
Record 1: Requirements

Multi-tenant SaaS authentication needs:
- Tenant isolation (prevent cross-tenant access)
- Scalability (thousands of tenants)
- Security (industry standards)

Uncertainty: Session vs token? Stateful vs stateless?
Next: Evaluate approaches

Record 2: Approach evaluation (adjusted)

Comparing session vs JWT:
- Session: Server state, easy revocation, harder scaling
- JWT: Stateless, scales well, complex revocation

Multi-tenancy complicates sessions (which DB?).
JWT better for distributed systems.
Next: JWT structure

Record 3: JWT payload design

JWT includes: User ID, Tenant ID, Permissions, Expiration

Uncertainty: Where verify tenant? Gateway vs service?
Next: Token refresh

Record 4 [REVISION of record 3]: Security fix

Original: Tenant ID in JWT claims.
Issue: Claims visible (base64), could read tenant IDs.

Corrected:
- Keep tenant ID (needed for routing)
- Add gateway verification
- Log access attempts

Impact: Need gateway security layer

Record 5: Refresh strategy (adjusted)

Access: 15 min
Refresh: 7 days, rotate on use

Storage:
- Access: Client memory
- Refresh: HttpOnly cookie + DB revocation

Enables revocation + stateless benefits.

Record 6: Gateway flow

1. Verify JWT signature
2. Extract tenant ID
3. Verify user belongs to tenant (cache + DB)
4. Forward with verified context

Addresses record 4 security concern.

Record 7 [FINAL]: Complete solution

- JWT with refresh rotation
- Tenant ID + gateway verification
- 15-min access, 7-day refresh
- HttpOnly cookies + revocation DB
- Gateway enforces isolation

Confidence: High
Assumptions: Distributed, centralized gateway
Trade-offs: Slight latency vs security
```

## Key Outcomes

1. **Revision caught security issue**: Tenant ID visibility
2. **Dynamic adjustment**: 5→7 thoughts as complexity emerged
3. **Comprehensive**: Authentication, authorization, multi-tenancy, revocation
