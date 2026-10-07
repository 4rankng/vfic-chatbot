import { useState } from "react";

import { Button } from "@/components/base/buttons/button";
import { TextArea } from "@/components/base/textarea/textarea";

import { pastedTextFile } from "../infrastructure/project-text-file";

type Props = {
  busy?: boolean;
  /** The confirm action's label; each surface names its own intent. */
  confirmLabel?: string;
  onSubmit: (file: File) => void;
  onClose: () => void;
};

/** Inline paste area of the brief-ingest surfaces: a textarea plus the
 *  confirm/cancel row. The trigger button belongs to each surface — they
 *  label and place it differently (menu action, heading row). */
export const PasteTextArea = ({
  busy = false,
  confirmLabel = "Nạp văn bản",
  onSubmit,
  onClose,
}: Props) => {
  const [text, setText] = useState("");
  return (
    <div className="grid gap-2">
      <TextArea
        aria-label="Văn bản kiến thức dán vào"
        placeholder="Dán nội dung kiến thức của dự án tại đây…"
        rows={6}
        isDisabled={busy}
        value={text}
        onChange={setText}
      />
      <div className="flex items-center gap-2">
        <Button
          type="button"
          color="primary"
          size="sm"
          className="uu-scope"
          isDisabled={!text.trim() || busy}
          isLoading={busy}
          showTextWhileLoading
          onClick={() => onSubmit(pastedTextFile(text))}
        >
          {confirmLabel}
        </Button>
        <Button
          type="button"
          color="secondary"
          size="sm"
          className="uu-scope"
          onClick={onClose}
        >
          Hủy
        </Button>
      </div>
    </div>
  );
};
