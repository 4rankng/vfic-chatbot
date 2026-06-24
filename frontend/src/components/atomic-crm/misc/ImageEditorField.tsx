import { useTranslate } from "ra-core";
import { lazy, Suspense, useState } from "react";
import { useFormContext } from "react-hook-form";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";

// Heavy deps (react-cropper, react-dropzone, cropper.css) are isolated in
// ImageEditorDialog and loaded via React.lazy only when the dialog opens.
const ImageEditorDialog = lazy(() =>
  import("./ImageEditorDialog").then((m) => ({ default: m.ImageEditorDialog })),
);

const ImageEditorField = (props: ImageEditorFieldProps) => {
  const translate = useTranslate();
  const { getValues } = useFormContext();
  const source = getValues(props.source);
  const imageUrl = source?.src;
  const [isDialogOpen, setIsDialogOpen] = useState(false);

  const { type = "image", emptyText, linkPosition = "none" } = props;

  const commonProps = {
    src: imageUrl,
    onClick: () => setIsDialogOpen(true),
    style: { cursor: "pointer" },
    className: `${props.className || ""}`,
  };

  const width = props.width || (type === "avatar" ? 50 : 200);
  const height = props.height || (type === "avatar" ? 50 : 200);

  return (
    <>
      <div
        className={`flex ${
          linkPosition === "right" ? "flex-row" : "flex-col"
        } items-center ${linkPosition === "right" ? "gap-2" : "gap-1"}`}
      >
        <div
          className={`rounded ${props.backgroundImageColor ? "p-4" : "p-0"}`}
          style={{
            backgroundColor: props.backgroundImageColor || "transparent",
          }}
        >
          {props.type === "avatar" ? (
            <Avatar
              {...commonProps}
              className={`cursor-pointer`}
              style={{ width, height }}
            >
              <AvatarImage src={imageUrl} />
              <AvatarFallback>{emptyText}</AvatarFallback>
            </Avatar>
          ) : (
            <img
              {...commonProps}
              className="cursor-pointer object-cover"
              style={{ width, height }}
              alt={translate("crm.image_editor.editable_content", {
                _: "Editable content",
              })}
            />
          )}
        </div>
        {linkPosition !== "none" && (
          <button
            type="button"
            onClick={() => setIsDialogOpen(true)}
            className="text-xs underline hover:no-underline cursor-pointer text-center"
          >
            {translate("crm.image_editor.change")}
          </button>
        )}
      </div>
      {isDialogOpen && (
        <Suspense fallback={null}>
          <ImageEditorDialog
            open={isDialogOpen}
            onClose={() => setIsDialogOpen(false)}
            {...props}
          />
        </Suspense>
      )}
    </>
  );
};

export default ImageEditorField;

export interface ImageEditorFieldProps {
  source: string;
  width?: number;
  height?: number;
  type?: "avatar" | "image";
  onSave?: any;
  linkPosition?: "right" | "bottom" | "none";
  backgroundImageColor?: string;
  className?: string;
  emptyText?: string;
}

export interface ImageEditorDialogProps extends ImageEditorFieldProps {
  open: boolean;
  onClose: () => void;
}
