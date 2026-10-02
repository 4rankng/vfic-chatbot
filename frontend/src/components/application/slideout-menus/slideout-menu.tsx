import {
  type ComponentPropsWithRef,
  type ReactNode,
  type RefAttributes,
} from "react";
import type {
  DialogProps as AriaDialogProps,
  ModalOverlayProps as AriaModalOverlayProps,
  ModalRenderProps as AriaModalRenderProps,
} from "react-aria-components";
import {
  Dialog as AriaDialog,
  DialogTrigger as AriaDialogTrigger,
  Modal as AriaModal,
  ModalOverlay as AriaModalOverlay,
} from "react-aria-components";
import { CloseButton } from "@/components/base/buttons/close-button";
import { cx } from "@/utils/cx";

interface ModalOverlayProps
  extends AriaModalOverlayProps,
    RefAttributes<HTMLDivElement> {}

export const ModalOverlay = (props: ModalOverlayProps) => {
  return (
    <AriaModalOverlay
      isDismissable={props.isDismissable ?? true}
      {...props}
      className={(state) =>
        cx(
          // Above the inbox page chrome (mobile-layout.css stacks list toggle,
          // scrim and chat header at z-60..70): a lower overlay lets those
          // elements paint through the open drawer.
          "fixed inset-0 z-[80] flex min-h-dvh w-full items-center justify-end bg-overlay/70 pl-6 outline-hidden ease-linear md:pl-10",
          state.isEntering && "duration-300 animate-in fade-in",
          state.isExiting && "duration-500 animate-out fade-out",
          typeof props.className === "function"
            ? props.className(state)
            : props.className,
        )
      }
    />
  );
};
ModalOverlay.displayName = "ModalOverlay";

interface ModalProps
  extends AriaModalOverlayProps,
    RefAttributes<HTMLDivElement> {}

export const Modal = (props: ModalProps) => (
  <AriaModal
    {...props}
    className={(state) =>
      cx(
        "inset-y-0 right-0 h-full w-full max-w-100 shadow-xl transition",
        state.isEntering && "duration-300 animate-in slide-in-from-right",
        state.isExiting && "duration-500 animate-out slide-out-to-right",
        typeof props.className === "function"
          ? props.className(state)
          : props.className,
      )
    }
  />
);
Modal.displayName = "Modal";

interface DialogProps extends AriaDialogProps, RefAttributes<HTMLElement> {}

export const Dialog = (props: DialogProps) => (
  <AriaDialog
    role="dialog"
    aria-label="Slideout menu"
    {...props}
    className={cx(
      "relative flex size-full flex-col items-start gap-6 overflow-y-auto bg-primary ring-1 ring-secondary_alt outline-hidden",
      props.className,
    )}
  />
);
Dialog.displayName = "Dialog";

interface SlideoutMenuProps
  extends Omit<AriaModalOverlayProps, "children">,
    RefAttributes<HTMLDivElement> {
  children:
    | ReactNode
    | ((children: AriaModalRenderProps & { close: () => void }) => ReactNode);
  /**
   * Classes for the sliding panel itself (the `Modal`).
   *
   * The panel — not the inner `Dialog` — is what carries the width: it is the
   * element anchored to the viewport edge and the one the slide-in animation
   * transforms. Sizing the `Dialog` instead left the panel's box wider than the
   * visible surface, so the scrim showed through in a strip beside the drawer
   * and the animation moved a mostly-invisible box. `className` styles the
   * scrim; this styles the panel. `SettingsChrome.tsx` composes the two
   * primitives directly to get the same split.
   */
  panelClassName?: string;
  dialogClassName?: string;
}

const Menu = ({
  children,
  dialogClassName,
  panelClassName,
  ...props
}: SlideoutMenuProps) => {
  return (
    <ModalOverlay {...props}>
      <Modal className={panelClassName}>
        {(state) => (
          <Dialog className={dialogClassName}>
            {({ close }) => {
              return typeof children === "function"
                ? children({ ...state, close })
                : children;
            }}
          </Dialog>
        )}
      </Modal>
    </ModalOverlay>
  );
};
Menu.displayName = "SlideoutMenu";

const Content = ({ role = "main", ...props }: ComponentPropsWithRef<"div">) => {
  return (
    <div
      role={role}
      {...props}
      className={cx(
        "flex size-full flex-col gap-6 overflow-y-auto overscroll-auto px-4 md:px-6",
        props.className,
      )}
    />
  );
};
Content.displayName = "SlideoutContent";

interface SlideoutHeaderProps extends ComponentPropsWithRef<"header"> {
  onClose?: () => void;
}

const Header = ({
  className,
  children,
  onClose,
  ...props
}: SlideoutHeaderProps) => {
  return (
    <header
      {...props}
      className={cx("relative z-1 w-full px-4 pt-6 md:px-6", className)}
    >
      {children}
      <CloseButton
        size="sm"
        className="absolute top-3 right-3 shrink-0"
        onClick={onClose}
      />
    </header>
  );
};
Header.displayName = "SlideoutHeader";

const Footer = (props: ComponentPropsWithRef<"footer">) => {
  return (
    <footer
      {...props}
      className={cx(
        "w-full p-4 shadow-[inset_0px_1px_0px_0px] shadow-border-secondary md:px-6",
        props.className,
      )}
    />
  );
};
Footer.displayName = "SlideoutFooter";

const SlideoutMenu = Menu as typeof Menu & {
  Trigger: typeof AriaDialogTrigger;
  Content: typeof Content;
  Header: typeof Header;
  Footer: typeof Footer;
};
SlideoutMenu.displayName = "SlideoutMenu";

SlideoutMenu.Trigger = AriaDialogTrigger;
SlideoutMenu.Content = Content;
SlideoutMenu.Header = Header;
SlideoutMenu.Footer = Footer;

export { SlideoutMenu };
