import { describe, expect, it } from "vitest";

import { parseTranscriptUtterances } from "./transcript-utterances";

describe("parseTranscriptUtterances", () => {
  it("parses the diarized S1/S2 format into alternating sides", () => {
    const utterances = parseTranscriptUtterances(
      "S1: Alo ạ?\nS2: Chị cho em hỏi giá dịch vụ.",
    );

    expect(utterances).toEqual([
      { speaker: "S1", side: "left", text: "Alo ạ?" },
      { speaker: "S2", side: "right", text: "Chị cho em hỏi giá dịch vụ." },
    ]);
  });

  it("continues an utterance across unlabeled ASR chunk lines", () => {
    const utterances = parseTranscriptUtterances(
      "S1: Dạ em nghe ạ.\nvà bên em đang tuyển.\nS2: Cho em hỏi.",
    );

    expect(utterances.map((utterance) => utterance.text)).toEqual([
      "Dạ em nghe ạ.\nvà bên em đang tuyển.",
      "Cho em hỏi.",
    ]);
  });

  it("keeps the plain-text ASR fallback as one unlabeled left utterance", () => {
    const utterances = parseTranscriptUtterances("alo cho em hỏi giá ạ");

    expect(utterances).toEqual([
      { speaker: "", side: "left", text: "alo cho em hỏi giá ạ" },
    ]);
  });

  it("maps speakers past two by parity (S3 left, S4 right)", () => {
    const utterances = parseTranscriptUtterances("S3: một\nS4: hai\nS1: ba");

    expect(utterances.map((utterance) => utterance.side)).toEqual([
      "left",
      "right",
      "left",
    ]);
  });

  it("returns nothing for an empty transcript", () => {
    expect(parseTranscriptUtterances("")).toEqual([]);
  });
});
