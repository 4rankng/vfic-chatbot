/**
 * Pure derivation of which src the LeadAvatar should actually render.
 * Returns null when there is no src OR the image previously failed to load,
 * so the icon fallback branch (derived from this value) becomes visible.
 * Exported for unit testing of the fallback state machine.
 */
export function resolveAvatarSrc(
  src: string | null | undefined,
  imgFailed: boolean,
): string | null {
  return src && !imgFailed ? src : null;
}
