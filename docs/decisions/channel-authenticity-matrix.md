# Channel webhook authenticity matrix

This decision fixes the transport contract for the single-tenant webhook
surfaces. Provider authenticity and HTTP acknowledgement policy remain owned by
the API transport. Each surface must apply its recorded verification policy
before normalized events cross into conversation/messaging behavior.

No webhook log may contain a secret, signature, provider identifier, message
content, or other candidate data. The routes log only bounded classifications
and request byte counts.

## Contract matrix

| Surface | Authenticity and authority lookup | HTTP / acknowledgement | Permitted side effects | Dedup and commit point | Enqueue failure | Batch failure and provider retry |
|---|---|---|---|---|---|---|
| Zalo Bot `POST /webhooks/zalo/chatbot` | Parse JSON, resolve the DB-first shared secret, and compare `X-Bot-Api-Secret-Token` in constant time. A mismatch stops before runtime authority. Missing configuration outside development returns `503`; development retains its unsigned convenience path. Runtime installation authority is resolved only after transport verification. | Invalid JSON `400`; mismatch `401`; verification unavailable `503`; authenticated `start_failed` `503`; other authenticated outcomes `200`. | Authenticated events may deduplicate, ensure the conversation, persist inbound state, apply bot eligibility guards, acquire a lease, emit Bot typing, and enqueue. Rejected events do none of these. | The eight-second dedup claim commits first. Inbound message/conversation state then commits before eligibility, lease acquisition, typing, enqueue, and ACK. | Boolean `False` releases the lease and maps to `start_failed` / `503`. An unexpected exception follows the route's normal `500` handling; it is distinct from the bounded boolean contract. | One event per request. Zalo retries the explicit `503` backpressure response; authenticated duplicates, locks, and human-starved outcomes are acknowledged `200`. |
| Zalo OA `POST /webhooks/zalo/oa` | The unsigned empty `{}` registration probe performs no settings or authority lookup. Real events currently have no enforceable transport signature: the stored `oa_secret_key` is the OA access-token secret, not a dedicated webhook-signing key, and previously false-rejected production traffic. The manual verify endpoint is diagnostic only until Zalo supplies and production verifies distinct signing material. | Probe `200 verified`; invalid JSON `400`; `start_failed` `503`; other normalized outcomes `200`. Signature headers do not change the response today. | Real OA events may apply text, receipt, lifecycle, click, profile-enrichment, and bot-turn behavior after normalization and runtime-authority lookup. Logs remain content-free. | Text events use the Zalo dedup and commit order above. OA receipts/lifecycle events have no message-dedup claim and retain their operation-specific commits. | Text enqueue `False` releases the lease and returns `503`. Profile enrichment remains best-effort and cannot change the ACK. | One OA event per request. Backpressure is retryable through `503`. Transport authenticity enforcement is deferred until dedicated signing material is empirically verified; network/rate controls remain the compensating boundary. |
| Messenger `GET /webhooks/facebook` | Resolve the DB-first verification token and compare it in constant time. No runtime installation lookup. | Exact subscription challenge `200`; wrong token/mode `403`; unavailable token outside development `503`. | No conversation or messaging mutation. | None. | None. | Subscription handshake only. |
| Messenger `POST /webhooks/facebook` | Resolve the DB-first app secret and verify raw-body HMAC before JSON parsing or writes. After verification, resolve the one active Page; each normalized event must match its account key. Runtime authority is resolved only for accepted text processing. | Invalid signature, malformed authenticated JSON, inactive Page, Page mismatch, per-event failure, and enqueue failure are all acknowledged `200`; a completed batch returns `200 processed`. | Invalid signatures have no business side effects. Authenticated receipts are applied best-effort before text events. Accepted text events may persist and enqueue. | Neutral dedup is scoped by provider, account, external user, and external message. The claim commits first; inbound state commits before enqueue. | Both a raised enqueue exception and boolean `False` release the lease. The route absorbs the per-event failure and finishes the batch with `200`. | Events are processed sequentially and one failure does not stop later events. Meta retries non-2xx deliveries, so POST failures are ACK-and-absorbed and durable unanswered inbound recovery remains responsible for later work. |

## Ordering invariant for Zalo OA

For every real OA event the transport order is:

1. Read and parse the raw request.
2. Preserve the exact unsigned-empty-object registration exception.
3. Do not treat the access-token secret as webhook-signing material.
4. Resolve runtime authority and invoke webhook business handling.
5. Preserve the established result-to-HTTP mapping.

This is an explicit temporary risk decision, not a claim that OA events are
cryptographically authenticated. Enabling enforcement requires a distinct,
verified signing secret and captured-event validation before changing production
acknowledgement behavior.
