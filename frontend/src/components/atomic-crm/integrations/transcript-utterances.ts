/**
 * The stored Cloudfone transcript format, parsed for the conversation view.
 *
 * `services/speech_to_text.py` renders MiniMax diarization as one
 * `S1: …` / `S2: …` line per segment (`_render_transcript`), and a plain-text
 * fallback with no labels at all. Nothing else — the stored string carries no
 * per-utterance timestamps, so the bubbles show none (a call-start time on
 * every bubble would misinform).
 *
 * Parsing rules:
 * - `S<n>: text` starts an utterance of speaker `S<n>`;
 * - following unlabeled lines continue the current utterance (chunked ASR
 *   splits long sentences across segments);
 * - a leading unlabeled block becomes its own unlabeled utterance (the
 *   plain-text fallback);
 * - side: odd speakers left, even speakers right (S1 left, S2 right — the
 *   consult's chat layout); unlabeled text reads as the left side.
 */

export type TranscriptUtterance = {
  /** "S1", "S2", … — empty when the ASR delivered plain text. */
  speaker: string;
  side: "left" | "right";
  text: string;
};

const UTTERANCE_START = /^(S\d+)\s*:\s*(.*)$/;

export const parseTranscriptUtterances = (
  transcript: string,
): TranscriptUtterance[] => {
  const utterances: TranscriptUtterance[] = [];

  for (const rawLine of transcript.split(/\r?\n/)) {
    const match = UTTERANCE_START.exec(rawLine);
    if (match) {
      const speaker = match[1] ?? "";
      const index = Number.parseInt(speaker.slice(1), 10);
      utterances.push({
        speaker,
        side: Number.isFinite(index) && index % 2 === 0 ? "right" : "left",
        text: match[2] ?? "",
      });
      continue;
    }

    const current = utterances[utterances.length - 1];
    if (current) {
      current.text = current.text ? `${current.text}\n${rawLine}` : rawLine;
    } else if (rawLine.trim() !== "") {
      utterances.push({ speaker: "", side: "left", text: rawLine });
    }
  }

  return utterances.filter(
    (utterance) => utterance.speaker !== "" || utterance.text.trim() !== "",
  );
};
