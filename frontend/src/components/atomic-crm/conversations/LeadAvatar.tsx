/**
 * Candidate avatar that renders a Zalo profile image when available and falls
 * back to the UserRound icon otherwise.
 *
 * Used across the three candidate-avatar surfaces (inbox row, conversation
 * header, chat-thread message). The fallback mirrors the pre-avatar color/icon
 * treatment so existing visuals are preserved when no image is present or the
 * image fails to load (Zalo does not document avatar URL lifetime).
 *
 * The <img> uses fixed dimensions + object-fit:cover to avoid layout shift,
 * and decoding="async" + loading="lazy" (below-the-fold rows) so off-screen
 * avatars never block rendering. Image-load failure flips internal state so the
 * icon fallback becomes visible (mirrors Radix Avatar's behaviour).
 */
import * as React from "react";

import { UserRound } from "lucide-react";

import { resolveAvatarSrc } from "./domain/avatar-src";

export type LeadAvatarProps = {
  /** Remote Zalo avatar URL. When empty/null, the icon fallback is shown. */
  src?: string | null;
  /** Background color for the icon fallback (hex or css color). */
  bg?: string;
  /** Foreground color for the icon fallback. */
  ink?: string;
  /** Icon size in px (matches the surrounding surface's icon style). */
  iconSize?: number;
  /** Extra class for the wrapping span (e.g. message-avatar). */
  className?: string;
  /** Inline style overrides for the wrapping span. */
  style?: React.CSSProperties;
  /** Accessible label derived from the candidate name. */
  alt: string;
  /** Optional overlay children (e.g. unread badge) positioned relative. */
  children?: React.ReactNode;
};

export function LeadAvatar({
  src,
  bg,
  ink,
  iconSize = 16,
  className,
  style,
  alt,
  children,
}: LeadAvatarProps) {
  // Track load failure so the icon fallback becomes visible. Resetting `src`
  // to null re-renders the icon branch (visibility/position are derived from
  // `effectiveSrc`, not the original prop). This mirrors Radix Avatar and is
  // the standard pattern for the broken-image case Zalo's undocumented URL
  // lifetime makes likely.
  const [imgFailed, setImgFailed] = React.useState(false);
  const effectiveSrc = resolveAvatarSrc(src, imgFailed);

  // Merge caller-provided CSS vars (--avatar-bg/--avatar-ink) with inline color
  // so both calling conventions (header uses inline `background`/`color`; inbox
  // row uses CSS custom props) keep working. CSS custom properties require a
  // cast because they're not in the strict CSSProperties type.
  const spanStyle = {
    background: bg,
    color: ink,
    "--avatar-bg": bg,
    "--avatar-ink": ink,
    position: "relative",
    // The image retains its own inherited radius; overlays such as unread
    // indicators need room to sit beyond that circular crop.
    overflow: children ? "visible" : "hidden",
    ...style,
  } as React.CSSProperties;

  return (
    <span className={className} style={spanStyle}>
      {effectiveSrc ? (
        <img
          src={effectiveSrc}
          alt={alt}
          decoding="async"
          loading="lazy"
          onError={() => setImgFailed(true)}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            borderRadius: "inherit",
          }}
        />
      ) : null}
      {/* Icon sits behind the img; visible only when no image is present or it
          fails to load. When an image is showing, the icon is hidden so a
          transparent PNG doesn't bleed it through. */}
      <UserRound
        className="icon"
        aria-hidden
        style={{
          width: iconSize,
          height: iconSize,
          visibility: effectiveSrc ? "hidden" : "visible",
          position: effectiveSrc ? "absolute" : "static",
        }}
      />
      {children}
    </span>
  );
}
