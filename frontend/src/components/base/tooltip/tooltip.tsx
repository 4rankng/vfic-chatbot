import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import type {
  ButtonProps as AriaButtonProps,
  TooltipProps as AriaTooltipProps,
  TooltipTriggerComponentProps as AriaTooltipTriggerComponentProps,
} from "react-aria-components";
import {
  Button as AriaButton,
  OverlayArrow as AriaOverlayArrow,
  Tooltip as AriaTooltip,
  TooltipTrigger as AriaTooltipTrigger,
} from "react-aria-components";
import { cx } from "@/utils/cx";

/** Touch has no hover-out, so a tapped tooltip would pin itself over the row
 * content until the next tap (CHAT-19: the Users "Sửa …" pill covered the
 * status chip of its own row). On coarse pointers the tooltip stays readable
 * for a short window and then closes itself; the trigger keeps its aria-label
 * so the name is reachable either way. */
const TOUCH_AUTO_CLOSE_MS = 2000;

export interface TooltipProps
  extends AriaTooltipTriggerComponentProps,
    Omit<AriaTooltipProps, "children"> {
  /**
   * The title of the tooltip.
   */
  title: ReactNode;
  /**
   * The description of the tooltip.
   */
  description?: ReactNode;
  /**
   * Whether to show the arrow on the tooltip.
   *
   * @default false
   */
  arrow?: boolean;
  /**
   * Delay in milliseconds before the tooltip is shown.
   *
   * @default 300
   */
  delay?: number;
}

export const Tooltip = ({
  title,
  description,
  children,
  arrow = false,
  delay = 300,
  closeDelay = 0,
  trigger,
  isDisabled,
  isOpen,
  defaultOpen,
  offset = 6,
  crossOffset,
  placement = "top",
  onOpenChange,
  ...tooltipProps
}: TooltipProps) => {
  const isTopOrBottomLeft = [
    "top left",
    "top end",
    "bottom left",
    "bottom end",
  ].includes(placement);
  const isTopOrBottomRight = [
    "top right",
    "top start",
    "bottom right",
    "bottom start",
  ].includes(placement);
  // Set negative cross offset for left and right placement to visually balance the tooltip.
  const calculatedCrossOffset = isTopOrBottomLeft
    ? -12
    : isTopOrBottomRight
      ? 12
      : 0;

  // Controlled open state so touch can close the pill on a timer (see
  // TOUCH_AUTO_CLOSE_MS). A caller-provided `isOpen` stays caller-owned.
  const [open, setOpen] = useState(defaultOpen ?? false);
  const autoCloseTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => clearTimeout(autoCloseTimer.current), []);
  const handleOpenChange = (nextOpen: boolean) => {
    onOpenChange?.(nextOpen);
    if (isOpen === undefined) setOpen(nextOpen);
    clearTimeout(autoCloseTimer.current);
    autoCloseTimer.current = undefined;
    if (nextOpen && isOpen === undefined && window.matchMedia("(pointer: coarse)").matches) {
      autoCloseTimer.current = window.setTimeout(() => {
        setOpen(false);
        onOpenChange?.(false);
      }, TOUCH_AUTO_CLOSE_MS);
    }
  };

  return (
    <AriaTooltipTrigger
      {...{
        trigger,
        delay,
        closeDelay,
        isDisabled,
        isOpen: isOpen ?? open,
        defaultOpen,
        onOpenChange: handleOpenChange,
      }}
    >
      {children}

      <AriaTooltip
        {...tooltipProps}
        offset={offset}
        placement={placement}
        crossOffset={crossOffset ?? calculatedCrossOffset}
        className={({ isEntering, isExiting }) =>
          cx(
            isEntering && "ease-out animate-in",
            isExiting && "ease-in animate-out",
          )
        }
      >
        {({ isEntering, isExiting }) => (
          <div
            className={cx(
              "z-50 flex max-w-xs origin-(--trigger-anchor-point) flex-col items-start gap-1 rounded-lg bg-primary-solid px-3 shadow-lg will-change-transform",
              description ? "py-3" : "py-2",

              isEntering &&
                "ease-out animate-in fade-in zoom-in-95 in-placement-left:slide-in-from-right-0.5 in-placement-right:slide-in-from-left-0.5 in-placement-top:slide-in-from-bottom-0.5 in-placement-bottom:slide-in-from-top-0.5",
              isExiting &&
                "ease-in animate-out fade-out zoom-out-95 in-placement-left:slide-out-to-right-0.5 in-placement-right:slide-out-to-left-0.5 in-placement-top:slide-out-to-bottom-0.5 in-placement-bottom:slide-out-to-top-0.5",
            )}
          >
            <span className="text-xs font-semibold text-white">{title}</span>

            {description && (
              <span className="text-xs font-medium text-tooltip-supporting-text">
                {description}
              </span>
            )}

            {arrow && (
              <AriaOverlayArrow>
                <svg
                  viewBox="0 0 100 100"
                  className="size-2.5 fill-bg-primary-solid in-placement-left:-rotate-90 in-placement-right:rotate-90 in-placement-top:rotate-0 in-placement-bottom:rotate-180"
                >
                  <path d="M0,0 L35.858,35.858 Q50,50 64.142,35.858 L100,0 Z" />
                </svg>
              </AriaOverlayArrow>
            )}
          </div>
        )}
      </AriaTooltip>
    </AriaTooltipTrigger>
  );
};

type TooltipTriggerProps = AriaButtonProps;

export const TooltipTrigger = ({
  children,
  className,
  ...buttonProps
}: TooltipTriggerProps) => {
  return (
    <AriaButton
      {...buttonProps}
      className={(values) =>
        cx(
          "h-max w-max outline-hidden",
          typeof className === "function" ? className(values) : className,
        )
      }
    >
      {children}
    </AriaButton>
  );
};
