import { cx } from "@/utils/cx";

import { parseTranscriptUtterances } from "./transcript-utterances";

/**
 * The transcript as a two-speaker chat (cloudfone redesign consult 22/10 §2):
 * S1 left on gray-100 with a 4px top-left corner, S2 right on brand-50 with a
 * 4px top-right corner, 11px speaker labels above, 12px between turns and 6px
 * between same-speaker turns. Used by both the mobile bottom sheet and the
 * desktop panel under the table — one content surface.
 *
 * Each bubble carries `aria-label="Speaker: … . …"` so a screen reader hears
 * speaker and content as one utterance; the visible text stays readable for
 * everyone else. Contrast is near-black ink on two near-white fills.
 *
 * Copying lives in the surfaces' headers ("Sao chép toàn bộ bản ghi"), not on
 * every bubble — the consult's bubble row is label + text only. Per-utterance
 * timestamps are not rendered either: the stored transcript has none (see
 * transcript-utterances.ts), and inventing times would misinform.
 */
export const TranscriptConversation = ({
  transcript,
}: {
  transcript: string;
}) => {
  const utterances = parseTranscriptUtterances(transcript);

  return (
    <ol className="transcript-conversation" aria-label="Nội dung bản ghi">
      {utterances.map((utterance, index) => {
        const who = utterance.speaker || "cuộc gọi";
        const continued =
          index > 0 && utterances[index - 1]!.speaker === utterance.speaker;
        return (
          <li
            key={`${utterance.speaker}-${index}`}
            className={cx(
              "transcript-turn",
              `is-${utterance.side}`,
              continued && "is-continued",
            )}
          >
            {utterance.speaker ? (
              <span
                className={cx(
                  "transcript-speaker",
                  utterance.side === "left"
                    ? "text-neutral-500"
                    : "text-brand-600",
                )}
              >
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
          </li>
        );
      })}
    </ol>
  );
};
