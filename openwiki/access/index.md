# Files

- [Admin-managed integration credentials (encryption at rest)](integrations-credentials.md) - Where Zalo, MiniMax, OpenRouter and Facebook Messenger credentials are stored, how AES-GCM + AAD context binding protects them, and how the graph layer resolves them per turn.
- [JWT auth, RBAC, and capability registry](rbac-and-capabilities.md) - How authentication (JWT access + rotated refresh, argon2 hashing), authorization (admin / recruiter), and the code-reviewed capability registry form the access control surface — and how the frontend mirrors it.
