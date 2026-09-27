/** Operator-facing copy for persisted status timestamps and probe failures. */

export const formatRelativeEpoch = (epoch: number | null): string => {
  if (!epoch) return "";
  const diffSeconds = Math.max(0, Math.round(Date.now() / 1000 - epoch));
  if (diffSeconds < 60) return "vừa xong";
  if (diffSeconds < 3600) return `${Math.floor(diffSeconds / 60)} phút trước`;
  if (diffSeconds < 86400) return `${Math.floor(diffSeconds / 3600)} giờ trước`;
  return `${Math.floor(diffSeconds / 86400)} ngày trước`;
};

// Provider probes surface upstream transport errors verbatim (HTTP status plus
// a raw JSON body). An operator console should state the consequence, not the
// wire format; the untouched text stays available as the element's tooltip.
export const describeProviderTestError = (raw: string): string => {
  const text = raw.trim();
  if (!text) return "Kiểm tra thất bại";
  if (/\b429\b|rate.?limit|quota/i.test(text)) return "Hết hạn mức (429)";
  if (/\b401\b|\b403\b|unauthor|invalid.?api.?key|forbidden/i.test(text)) {
    return "Token bị từ chối (401)";
  }
  if (/\b404\b|not.?found|unknown.?model/i.test(text)) {
    return "Sai model hoặc Base URL (404)";
  }
  if (/timeout|timed.?out|ETIMEDOUT|ECONNRESET/i.test(text)) {
    return "Hết thời gian chờ";
  }
  if (/\b5\d{2}\b|internal.?server/i.test(text)) {
    return "Lỗi phía nhà cung cấp";
  }
  if (/ENOTFOUND|ECONNREFUSED|getaddrinfo|network/i.test(text)) {
    return "Không kết nối được";
  }
  // Unrecognised failure: keep the operator's own words, minus any JSON tail.
  const headline = text.split(/[:{]/)[0].trim();
  return headline.length > 0 && headline.length <= 80 ? headline : text;
};
