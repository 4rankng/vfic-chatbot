import { execFile } from "node:child_process";
import path from "node:path";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

const execFileAsync = promisify(execFile);
const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default async function globalTeardown(): Promise<void> {
  // Visual-only runs never start the backend and never create an e2e database,
  // so there is nothing to drop.
  if (process.env.VFIC_VISUAL_ONLY) {
    return;
  }
  const python =
    process.env.VFIC_BACKEND_PYTHON ??
    path.resolve(__dirname, "../../backend/.venv/bin/python");
  const harness = path.resolve(__dirname, "../../backend/tests/e2e_harness.py");
  await execFileAsync(python, [harness, "drop"], {
    env: process.env,
    timeout: 30_000,
  });
}
