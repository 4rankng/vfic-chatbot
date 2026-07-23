import type { FileDownloadPort } from "../application/knowledge-port";

const saveObject = (filename: string, content: Blob): void => {
  const url = URL.createObjectURL(content);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
};

export const browserFileDownloadAdapter: FileDownloadPort = Object.freeze({
  saveText: (filename, content, mediaType) =>
    saveObject(filename, new Blob([content], { type: mediaType })),
  saveBinary: (filename, bytes, mediaType) =>
    saveObject(filename, new Blob([bytes], { type: mediaType })),
});
