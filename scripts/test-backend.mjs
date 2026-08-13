import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";

const candidates = process.platform === "win32"
  ? [".venv/Scripts/python.exe", "python.exe", "python"]
  : [".venv/bin/python", "python3", "python"];
const python = candidates.find((candidate) => candidate.includes("/") ? existsSync(candidate) : true);

if (!python) {
  console.error("Python was not found. Create .venv or install Python 3.11/3.12.");
  process.exit(1);
}

const result = spawnSync(
  python,
  ["-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
  { stdio: "inherit", shell: false },
);

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}
process.exit(result.status ?? 1);
