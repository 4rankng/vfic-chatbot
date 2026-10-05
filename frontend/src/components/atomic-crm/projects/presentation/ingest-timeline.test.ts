import { describe, expect, it } from "vitest";

import type { ProjectKnowledgeCategory } from "../domain/project-knowledge-policy";
import {
  buildIngestTimeline,
  type IngestTimelineInput,
} from "./ingest-timeline";

const base: IngestTimelineInput = {
  readingFile: false,
  creatingDraft: false,
  draftFailed: false,
  draftId: null,
  hasBrief: false,
  ingest: { phase: "idle" },
};

const states = (input: IngestTimelineInput) =>
  Object.fromEntries(
    buildIngestTimeline(input).map((checkpoint) => [
      checkpoint.key,
      [checkpoint.state, checkpoint.detail ?? ""],
    ]),
  );

describe("buildIngestTimeline", () => {
  it("keeps every checkpoint pending before a pick", () => {
    const timeline = buildIngestTimeline(base);
    expect(timeline.map((checkpoint) => checkpoint.state)).toEqual([
      "pending",
      "pending",
      "pending",
      "pending",
    ]);
  });

  it("marks the browser read active while the strip parses the pick", () => {
    const [file] = buildIngestTimeline({
      ...base,
      readingFile: true,
    });
    expect(file.state).toBe("active");
  });

  it("shows draft creation as its own checkpoint", () => {
    const timeline = states({
      ...base,
      creatingDraft: true,
      ingest: { phase: "idle" },
    });
    expect(timeline.draft[0]).toBe("active");
    expect(timeline.draft[1]).toContain("bản nháp");
    expect(timeline.analyze[0]).toBe("pending");
  });

  it("reports the upload window and the extraction counts", () => {
    const uploading = states({
      ...base,
      draftId: "7",
      hasBrief: true,
      ingest: {
        phase: "running",
        current: null,
        activated: [],
        total: 0,
        items: [],
      },
    });
    expect(uploading.analyze).toEqual(["active", "Đang tải tệp lên hệ thống…"]);

    const extracting = states({
      ...base,
      draftId: "7",
      hasBrief: true,
      ingest: {
        phase: "running",
        current: null,
        activated: [],
        total: 0,
        items: [],
        sections: { completed: 4, total: 9 },
      },
    });
    expect(extracting.analyze).toEqual([
      "active",
      "Đang đọc cấu trúc tệp (4/9 đoạn)…",
    ]);
  });

  it("reports the current category and confirmed count during classification", () => {
    const current = states({
      ...base,
      draftId: "7",
      hasBrief: true,
      ingest: {
        phase: "running",
        current: "jobs",
        activated: ["overview"],
        total: 3,
        items: [
          { key: "overview", status: "active" },
          { key: "jobs", status: "processing" },
          { key: "compensation", status: "queued" },
        ],
      },
    });
    expect(current.classify).toEqual([
      "active",
      "Đang nạp «Vị trí tuyển dụng» (2/3)…",
    ]);
    expect(current.analyze[0]).toBe("done");
  });

  it("appends the finish checkpoint with the cutover note", () => {
    const timeline = buildIngestTimeline({
      ...base,
      draftId: "7",
      hasBrief: true,
      ingest: {
        phase: "done",
        activated: ["overview", "jobs"] as ProjectKnowledgeCategory[],
        requiresCutover: true,
      },
    });
    const finish = timeline.at(-1);
    expect(finish?.state).toBe("done");
    expect(finish?.detail).toContain("chuyển đổi");
    expect(
      timeline.slice(0, -1).every((checkpoint) => checkpoint.state === "done"),
    ).toBe(true);
  });

  it("fails the classification checkpoint when a category is refused", () => {
    const timeline = states({
      ...base,
      draftId: "7",
      hasBrief: true,
      ingest: {
        phase: "failed",
        failed: "jobs",
        message: "nội dung không hợp lệ",
        activated: ["overview"],
      },
    });
    expect(timeline.classify[0]).toBe("failed");
    expect(timeline.analyze[0]).toBe("done");
    expect(timeline.finish[0]).toBe("pending");
  });

  it("fails the analysis checkpoint when the backend refuses the file", () => {
    const timeline = states({
      ...base,
      draftId: "7",
      hasBrief: true,
      ingest: {
        phase: "failed",
        failed: null,
        message: "Không thể nạp tệp.",
        activated: [],
      },
    });
    expect(timeline.analyze[0]).toBe("failed");
    expect(timeline.classify[0]).toBe("pending");
    expect(timeline.draft[0]).toBe("done");
  });

  it("fails the draft checkpoint when draft creation itself threw", () => {
    const timeline = states({ ...base, draftFailed: true });
    expect(timeline.draft[0]).toBe("failed");
    expect(timeline.analyze[0]).toBe("pending");
  });
});
