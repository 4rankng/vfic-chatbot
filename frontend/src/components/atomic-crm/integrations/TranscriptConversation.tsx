import { Copy } from "lucide-react";

import {
  copyCredentialFieldValue,
  type CredentialFieldNotify,
} from "./credentialClipboard";
import { parseTranscriptUtterances } from "./transcript-utterances";

/**
 * The transcript as a two-speaker chat (settings-mobile consult §4): S1 left
 * on gray-100, S2 right on brand-50, one bubble per utterance with the
 * speaker label above it and a copy action below. Used by both the mobile
 * bottom sheet and the desktop panel under the table — one content surface.
 *
 * Each bubble carries `aria-label="Speaker: … . …"` so a screen reader hears
 * speaker and content as one utterance; the visible text stays readable for
 * everyone else. Contrast is near-black ink on two near-white fills.
 *
 * Per-utterance timestamps are not rendered: the stored transcript has none
 * (see transcript-utterances.ts), and inventing times would misinform.
 */
export const TranscriptConversation = ({
  transcript,
  notify,
}: {
  transcript: string;
  notify: CredentialFieldNotify;
}) => {
  const utterances = parseTranscriptUtterances(transcript);

  return (
    <ol className="transcript-conversation" aria-label="Nội dung bản ghi">
      {utterances.map((utterance, index) => {
        const who = utterance.speaker || "cuộc gọi";
        return (
          <li
            key={`${utterance.speaker}-${index}`}
            className={`transcript-turn is-${utterance.side}`}
          >
            {utterance.speaker ? (
              <span className="transcript-speaker text-neutral-700">
                {utterance.speaker}
              </span>
            ) : null}
            <div
              role="group"
              aria-label={`Speaker: ${who}. ${utterance.text}`}
              className={
                utterance.side === "left"
                  ? "transcript-bubble transcript-bubble--left bg-neutral-100"
                  : "transcript-bubble transcript-bubble--right bg-brand-50"
              }
            >
              <p className="transcript-text">{utterance.text}</p>
            </div>
            <button
              type="button"
              className="transcript-copy"
              aria-label={`Sao chép nội dung của ${who}`}
              onClick={() =>
                void copyCredentialFieldValue(
                  "nội dung",
                  utterance.text,
                  notify,
                )
              }
            >
              <Copy aria-hidden="true" className="size-4" />
            </button>
          </li>
        );
      })}
    </ol>
  );
};
