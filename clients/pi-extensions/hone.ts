/**
 * Hone client for Pi — publish traces, annotate them, stay in sync.
 *
 * Configuration is resolved in this order:
 *   1. session overrides set with /hone url … /hone token … (this Pi process)
 *   2. HONE_URL / HONE_TOKEN environment variables
 *   3. ~/.pi/agent/hone.json  ({ "url": "…", "token": "…" })
 *
 * The factory syncs AGENTS.md before Pi scans for context files, and every
 * session start (launch, /new, /resume, reload) reports the sync status.
 *
 * Commands:
 *   /hone                    status panel + configure menu (TUI)
 *   /hone status             connection + sync status, one notification
 *   /hone url <url>          override the service URL for this session
 *   /hone token <token>      override the token for this session
 *   /hone sync               re-sync AGENTS.md from the service now
 *   /feedback <text>         attach feedback to this session's trace
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import * as fs from "node:fs";
import * as path from "node:path";
import * as os from "node:os";

interface HoneCfg {
  url: string;
  token: string;
  /** false = sync AGENTS.md but not publish traces (batch-runner mode). */
  publish?: boolean;
}

type Source = "session" | "env" | "file" | "";

/** Overrides set through /hone in this Pi process. */
const sessionOverride: Partial<HoneCfg> = {};

function configPath(): string {
  return path.join(os.homedir(), ".pi", "agent", "hone.json");
}

function loadFileCfg(): HoneCfg | null {
  try {
    return { url: "", token: "", ...JSON.parse(fs.readFileSync(configPath(), "utf8")) };
  } catch {
    return null;
  }
}

/** Effective config + where each field came from, for the status display. */
function resolveCfg(): { cfg: HoneCfg; urlSource: Source; tokenSource: Source } {
  const file = loadFileCfg();
  const envUrl = process.env.HONE_URL ?? "";
  const envToken = process.env.HONE_TOKEN ?? "";
  const url = sessionOverride.url ?? envUrl ?? "";
  const urlSource: Source = sessionOverride.url ? "session" : envUrl ? "env" : file?.url ? "file" : "";
  const token = sessionOverride.token ?? envToken ?? file?.token ?? "";
  const tokenSource: Source = sessionOverride.token
    ? "session"
    : envToken
      ? "env"
      : file?.token
        ? "file"
        : "";
  return {
    cfg: { url: url || file?.url || "", token: token || file?.token || "" },
    urlSource: urlSource || (file?.url ? "file" : ""),
    tokenSource: tokenSource || (file?.token ? "file" : ""),
  };
}

function headers(cfg: HoneCfg, extra: Record<string, string> = {}): Record<string, string> {
  return { authorization: `Bearer ${cfg.token}`, ...extra };
}

interface Probe {
  ok: boolean;
  version?: string;
  currentId?: string;
  traces?: number;
  versions?: number;
  runs?: number;
  error?: string;
}

/** One round-trip health check against the service. */
async function probe(cfg: HoneCfg): Promise<Probe> {
  try {
    const res = await fetch(`${cfg.url}/agents.md`, { headers: headers(cfg) });
    if (res.status === 401) return { ok: false, error: "unauthorized — check the token (/hone token …)" };
    if (!res.ok) return { ok: false, error: `HTTP ${res.status}` };
    const version = res.headers.get("x-hone-version") ?? undefined;
    await res.text();
    let state: any = null;
    try {
      const s = await fetch(`${cfg.url}/api/state`, { headers: headers(cfg) });
      if (s.ok) state = await s.json();
    } catch {
      /* /agents.md answering is enough to call it connected */
    }
    return {
      ok: true,
      version,
      currentId: state?.currentId ?? version,
      traces: state?.traces?.length,
      versions: state?.versions?.length,
    };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}

let syncedVersion: string | null = null;

interface SyncResult {
  status: "synced" | "up-to-date" | "offline" | "unconfigured";
  version?: string;
  error?: string;
}

/** Pull GET /agents.md into the workspace so Pi's context scan picks it up. */
async function syncAgentsMd(cfg: HoneCfg): Promise<SyncResult> {
  if (!cfg.url) return { status: "unconfigured" };
  try {
    const res = await fetch(`${cfg.url}/agents.md`, { headers: headers(cfg) });
    if (!res.ok) return { status: "offline", error: `HTTP ${res.status}` };
    syncedVersion = res.headers.get("x-hone-version");
    const remote = await res.text();
    const target = path.join(process.cwd(), "AGENTS.md");
    let local: string | null = null;
    try {
      local = fs.readFileSync(target, "utf8");
    } catch {
      local = null;
    }
    if (local !== remote) {
      fs.writeFileSync(target, remote, "utf8");
      return { status: "synced", version: syncedVersion ?? undefined };
    }
    return { status: "up-to-date", version: syncedVersion ?? undefined };
  } catch (err) {
    return { status: "offline", error: err instanceof Error ? err.message : String(err) };
  }
}

/** Report a sync result so the user always knows where AGENTS.md came from. */
function announce(ctx: any, r: SyncResult, cfg: HoneCfg): void {
  const ui = ctx?.ui;
  if (!ui) return;
  const where = cfg.url.replace(/^https?:\/\//, "");
  try {
    if (r.status === "synced") {
      ui.setStatus?.("hone", `AGENTS.md synced ${r.version ? `@ ${r.version}` : ""}`);
      ui.notify(`hone: AGENTS.md synced from ${where}${r.version ? ` — version ${r.version} applied` : ""}`, "info");
    } else if (r.status === "up-to-date") {
      ui.setStatus?.("hone", `AGENTS.md up to date${r.version ? ` @ ${r.version}` : ""}`);
      ui.notify(`hone: AGENTS.md up to date${r.version ? ` (${r.version})` : ""} — local file matches the service`, "info");
    } else if (r.status === "offline") {
      ui.setStatus?.("hone", "offline — local AGENTS.md");
      ui.notify(`hone: service unreachable (${where}: ${r.error}) — keeping the local AGENTS.md`, "warning");
    } else {
      ui.setStatus?.("hone", "not configured");
      ui.notify("hone: no service configured — set one with /hone url <url> (or HONE_URL)", "warning");
    }
  } catch {
    /* UI not available in this mode */
  }
}

function sessionIdOf(file: string): string | null {
  try {
    const text = fs.readFileSync(file, "utf8");
    for (const line of text.split("\n")) {
      if (!line.trim()) continue;
      try {
        const entry = JSON.parse(line);
        if (entry.type === "session" && entry.id) return entry.id;
      } catch {
        /* skip */
      }
    }
  } catch {
    /* unreadable */
  }
  const m = path.basename(file).match(/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i);
  return m ? m[1] : null;
}

export default async function (pi: ExtensionAPI) {
  // Hosts such as t3code start throwaway `--no-session` processes to list
  // models and commands; syncing there would write AGENTS.md into their cwd.
  const ephemeral = process.argv.includes("--no-session");
  const boot = resolveCfg();
  if (boot.cfg.url && !ephemeral) await syncAgentsMd(boot.cfg);

  pi.on("session_start", async (_event, ctx) => {
    if (ephemeral) return;
    const { cfg } = resolveCfg();
    const r = await syncAgentsMd(cfg);
    announce(ctx, r, cfg);
  });

  pi.on("agent_settled", async (_event, ctx) => {
    const { cfg } = resolveCfg();
    if (!cfg.url) return;
    if (loadFileCfg()?.publish === false) return;
    try {
      const file = ctx.sessionManager?.getSessionFile?.();
      if (!file || !fs.existsSync(file)) return;
      const sessionId = sessionIdOf(file);
      if (!sessionId) return;
      const body = fs.readFileSync(file);
      const res = await fetch(`${cfg.url}/api/traces/${sessionId}`, {
        method: "PUT",
        headers: headers(cfg, {
          "content-type": "application/x-ndjson",
          ...(syncedVersion ? { "x-hone-version": syncedVersion } : {}),
        }),
        body,
      });
      // An RPC host such as t3code shows its own Hone status, so the notice would only add noise there.
      if (res.ok && ctx.ui?.notify && !process.argv.some((arg) => arg === "rpc" || arg === "--mode=rpc")) {
        const data = (await res.json().catch(() => null)) as { trace?: { id?: string } } | null;
        ctx.ui.notify(`hone: trace published${data?.trace?.id ? ` (${data.trace.id})` : ""}`, "info");
      }
    } catch {
      /* publishing is best-effort; the session file stays on disk */
    }
  });

  pi.registerCommand("feedback", {
    description: "Attach feedback to this session for the Hone optimizer",
    handler: async (args, ctx) => {
      const text = (args ?? "").trim();
      if (!text) {
        ctx.ui?.notify("usage: /feedback <what should change>", "warning");
        return;
      }
      const { cfg } = resolveCfg();
      try {
        const file = ctx.sessionManager?.getSessionFile?.();
        const sessionId = file ? sessionIdOf(file) : null;
        if (!sessionId) {
          ctx.ui?.notify("hone: no active session to annotate", "warning");
          return;
        }
        const res = await fetch(`${cfg.url}/api/traces/ses_${sessionId.replace(/-/g, "").slice(0, 8)}/feedback`, {
          method: "POST",
          headers: headers(cfg, { "content-type": "application/json" }),
          body: JSON.stringify({ text }),
        });
        if (res.ok) {
          ctx.ui?.notify(`hone: feedback recorded — "${text.slice(0, 60)}"`, "info");
        } else {
          ctx.ui?.notify(`hone: feedback failed (${res.status})`, "error");
        }
      } catch {
        ctx.ui?.notify("hone: service unreachable", "error");
      }
    },
  });

  /* ------------------------------------------------------------------ /hone */

  const statusLines = (p: Probe, r: SyncResult | null, sources: { urlSource: Source; tokenSource: Source }): string[] => {
    const { cfg } = resolveCfg();
    const dot = p.ok ? "●" : "○";
    const lines = [
      "Hone — AGENTS.md sync",
      `${dot} ${p.ok ? `connected  ${cfg.url}` : `unreachable ${cfg.url || "(no url set)"}`}`,
    ];
    if (!p.ok && p.error) lines.push(`  error: ${p.error}`);
    if (p.ok) {
      lines.push(`  version ${p.version ?? "?"} current · traces ${p.traces ?? "?"} · versions ${p.versions ?? "?"}`);
    }
    if (r) {
      const map: Record<SyncResult["status"], string> = {
        synced: `AGENTS.md synced${r.version ? ` @ ${r.version}` : ""}`,
        "up-to-date": `AGENTS.md up to date${r.version ? ` @ ${r.version}` : ""}`,
        offline: "AGENTS.md local only (service offline)",
        unconfigured: "AGENTS.md not synced (no service configured)",
      };
      lines.push(map[r.status]);
    }
    lines.push(
      `  url from: ${sources.urlSource || "none"} · token from: ${sources.tokenSource || "none"}`,
      "  override: /hone url … · /hone token … · save: option in this menu",
    );
    return lines;
  };

  const saveConfig = async (ctx: any): Promise<void> => {
    const { cfg } = resolveCfg();
    const ok = await ctx.ui.confirm(
      "Save configuration?",
      `Write url + token to ${configPath()} so future sessions use them?`,
    );
    if (!ok) return;
    try {
      fs.writeFileSync(configPath(), JSON.stringify({ url: cfg.url, token: cfg.token }, null, 2) + "\n", "utf8");
      ctx.ui.notify(`hone: saved to ${configPath()}`, "info");
    } catch (err) {
      ctx.ui.notify(`hone: could not save (${err instanceof Error ? err.message : err})`, "error");
    }
  };

  pi.registerCommand("hone", {
    description: "Hone service status and configuration (url, token, sync)",
    handler: async (args, ctx) => {
      const ui: any = ctx.ui;
      const argv = (args ?? "").trim().split(/\s+/);
      const sub = argv[0] ?? "";

      // Direct subcommands first — they also work non-interactively.
      if (sub === "url") {
        const url = argv.slice(1).join(" ").replace(/\/+$/, "");
        if (!url) {
          ui?.notify("usage: /hone url <http://host:port>", "warning");
          return;
        }
        sessionOverride.url = url;
        const { cfg } = resolveCfg();
        const p = await probe(cfg);
        const r = await syncAgentsMd(cfg);
        announce(ctx, r, cfg);
        ui?.notify(`hone: url set to ${url}${p.ok ? " — connected" : ` — unreachable (${p.error})`}`, p.ok ? "info" : "warning");
        return;
      }
      if (sub === "token") {
        const token = argv[1] ?? "";
        if (!token) {
          ui?.notify("usage: /hone token <token>", "warning");
          return;
        }
        sessionOverride.token = token;
        const { cfg } = resolveCfg();
        const p = await probe(cfg);
        ui?.notify(
          `hone: token set${p.ok ? " — authorized" : ` — check failed (${p.error})`}`,
          p.ok ? "info" : "warning",
        );
        return;
      }
      if (sub === "sync") {
        const { cfg } = resolveCfg();
        const r = await syncAgentsMd(cfg);
        announce(ctx, r, cfg);
        return;
      }
      if (sub === "status" || sub === "") {
        const resolved = resolveCfg();
        const p = await probe(resolved.cfg);
        const r = await syncAgentsMd(resolved.cfg);
        const lines = statusLines(p, r, resolved);

        if (!ctx?.hasUI) {
          // print/json mode: no dialogs — one notification is the whole status.
          ui?.notify(`hone: ${lines.join(" | ")}`, p.ok ? "info" : "warning");
          announce(ctx, r, resolved.cfg);
          return;
        }

        // TUI: persistent status panel above the editor + a menu.
        try {
          ui.setWidget("hone-status", lines);
        } catch {
          /* widget placement unavailable */
        }
        announce(ctx, r, resolved.cfg);

        for (;;) {
          const choice = await ui.select("Hone:", [
            "Set service URL…",
            "Set token…",
            "Re-sync AGENTS.md now",
            "Save configuration to ~/.pi/agent/hone.json…",
            "Close",
          ]);
          if (choice === undefined || choice === "Close") {
            try {
              ui.setWidget("hone-status", undefined);
            } catch {
              /* ignore */
            }
            return;
          }
          if (choice === "Set service URL…") {
            const url = await ui.input("Service URL:", "http://127.0.0.1:8080");
            if (url) {
              sessionOverride.url = url.trim().replace(/\/+$/, "");
              ui.notify(`hone: url set to ${sessionOverride.url}`, "info");
            }
          } else if (choice === "Set token…") {
            const token = await ui.input("Bearer token:", "dev-token");
            if (token) {
              sessionOverride.token = token.trim();
              ui.notify("hone: token set", "info");
            }
          } else if (choice === "Re-sync AGENTS.md now") {
            const { cfg } = resolveCfg();
            const res = await syncAgentsMd(cfg);
            announce(ctx, res, cfg);
          } else if (choice.startsWith("Save")) {
            await saveConfig(ctx);
          }
          // Refresh the panel after every action.
          const after = resolveCfg();
          const p2 = await probe(after.cfg);
          const r2 = await syncAgentsMd(after.cfg);
          try {
            ui.setWidget("hone-status", statusLines(p2, r2, after));
          } catch {
            /* ignore */
          }
        }
      } else {
        ui?.notify("usage: /hone [status | url <url> | token <token> | sync]", "warning");
      }
    },
  });
}
