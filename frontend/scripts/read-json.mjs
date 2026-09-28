import fs from "node:fs";

/**
 * Parse a JSON file, failing loudly and legibly.
 *
 * The registry scripts are gates: malformed input must stop them. But a bare
 * `JSON.parse(fs.readFileSync(...))` reports a `SyntaxError` from inside the
 * parser with no hint of which file produced it, which is exactly the moment an
 * operator needs the filename. This keeps the failure (same throw, same non-zero
 * exit) and adds the path and the cause.
 */
export const readJson = (file) => {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch (error) {
    throw new Error(`${file} is not valid JSON: ${error.message}`, {
      cause: error,
    });
  }
};
