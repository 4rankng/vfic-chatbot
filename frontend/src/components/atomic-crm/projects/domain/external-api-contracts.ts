// Wire + form contracts for the per-project external API integration
// (`/api/v1/knowledge/projects/{id}/external-api`).
//
// The admin supplies three things: the origin, the auth material, and the
// vendor's own integration guide. The key is write-only — the read type carries
// only its status projection — and the guide is the specification the agent
// reads to decide which path to call.

export type ExternalApiKeyStatus = Readonly<{
  configured: boolean;
  /** ``"<n> ký tự"`` when configured, ``null`` otherwise. Never the value. */
  preview: string | null;
}>;

export type ExternalApiView = Readonly<{
  enabled: boolean;
  base_url: string;
  auth_header: string;
  auth_scheme: string;
  guide: string;
  api_key: ExternalApiKeyStatus;
}>;

/**
 * PUT body. ``api_key`` is tri-state: omitted keeps the stored secret, ``""``
 * clears it, any other value replaces it.
 */
export type ExternalApiUpdatePayload = Readonly<{
  enabled: boolean;
  base_url: string;
  auth_header: string;
  auth_scheme: string;
  guide: string;
  api_key?: string;
}>;

/** The admin's editable draft; ``api_key`` is always blank until typed. */
export type ExternalApiFormState = Readonly<{
  enabled: boolean;
  base_url: string;
  auth_header: string;
  auth_scheme: string;
  guide: string;
  api_key: string;
  /** Set by the explicit "Xóa khóa" action; distinguishes clear from keep. */
  clear_api_key: boolean;
}>;
