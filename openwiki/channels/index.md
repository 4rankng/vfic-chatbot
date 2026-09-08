# Files

- [Facebook Messenger adapter](facebook-messenger.md) - HMAC-SHA256 webhook signature, OAUTH flow that issues the page-scoped token used for outbound dispatch, the 24-hour Standard Window policy, and the channels/port isolation that keeps the rest of the app provider-neutral.
- [Zalo Bot Platform and Official Account adapters](zalo-adapters.md) - The two webhook endpoints, their signature schemes, ingress normalization, dispatch path, and the rule that Zalo adapters are intentionally thin so the rest of the app stays channel-neutral.
