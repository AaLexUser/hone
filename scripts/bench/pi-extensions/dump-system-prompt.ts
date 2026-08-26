/**
 * Dump the fully assembled system prompt to a file so runs can prove which
 * instructions (AGENTS.md etc.) actually reached the model.
 *
 * Target file resolution:
 *   1. PI_SYSTEM_PROMPT_FILE env var (absolute path)
 *   2. /logs/agent/system-prompt.txt  (harbor sandboxes: collected with the trial)
 *   3. .system-prompt.txt in the cwd   (local fallback)
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import * as fs from "node:fs";
import * as path from "node:path";

export default function (pi: ExtensionAPI) {
  pi.on("before_agent_start", async (event: any) => {
    const env = process.env.PI_SYSTEM_PROMPT_FILE;
    let target: string;
    if (env) {
      target = env;
    } else if (fs.existsSync("/logs/agent")) {
      target = "/logs/agent/system-prompt.txt";
    } else {
      target = path.join(process.cwd(), ".system-prompt.txt");
    }
    try {
      fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.writeFileSync(target, event.systemPrompt ?? "", "utf8");
    } catch {
      /* best-effort; never break the session */
    }
  });
}
