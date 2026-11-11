/**
 * Hone MAJICS driver — one stage of the optimization pipeline, in-sandbox.
 *
 * The service runs TWO Harbor jobs per optimization run. Hone's custom Harbor
 * agent launches this driver directly (TypeScript, erasable syntax — run with
 * `node --experimental-strip-types`) with the mode from config/majics.json:
 *
 *   review  — N reviewers (configured models, byte-identical prompt, read-only
 *             workspace tools) ⇄ review judge (ask_panel cross-examination)
 *             → artifacts/review.json
 *   propose — N proposers (judged review + experience history + submit_proposal)
 *             ⇄ propose judge (ask_panel + submit_proposal)
 *             → artifacts/proposal.json
 *
 * Everything inside a stage — the panel fan-out with sibling cancellation,
 * the judge with its single ask_panel reach into the live sessions — is
 * ported from Rejudge in reference/rejudge/src/{runner,panel,judge,ask-panel-tool,
 * activity}.ts and runs on the pi agent SDK, exactly like the original.
 * Live progress is POSTed to the Hone service.
 */

import {
  DefaultResourceLoader,
  ModelRuntime,
  SessionManager,
  SettingsManager,
  createAgentSession,
  defineTool,
} from "@earendil-works/pi-coding-agent";
import type { AgentSession, ToolDefinition } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import * as fs from "node:fs";
import * as path from "node:path";

type ReasoningLevel = "off" | "minimal" | "low" | "medium" | "high" | "xhigh";

interface ModelSpec {
  id: string;
  reasoning: ReasoningLevel;
}

/** One seat in the roster, as materialized by the service. */
interface RosterConfig {
  mode: "review" | "propose";
  attempt?: number;
  rejection?: string | null;
  followUpTimeoutS?: number;
  reviewModels: ModelSpec[];
  reviewJudge: ModelSpec;
  proposeModels: ModelSpec[];
  proposeJudge: ModelSpec;
}

interface HoneConfig {
  url: string;
  runId: string;
}

/** A live progress event POSTed to the Hone service. */
interface ProgressEvent {
  kind: string;
  [key: string]: unknown;
}

/** A submitted edit proposal (submit_proposal payload). */
interface ProposalEdit {
  oldText: string;
  newText: string;
  rationale: string;
  evidence: string[];
}

interface Proposal {
  edits: ProposalEdit[];
  note?: string;
  commit_title?: string;
  commit_body?: string;
}

interface ReviewItem {
  statement: string;
  traceIds: string[];
  confidence: "low" | "medium" | "high";
}

interface ReviewHypothesis extends ReviewItem {
  contradictions?: string[];
}

interface Review {
  version: 1;
  summary: string;
  findings: ReviewItem[];
  hypotheses: ReviewHypothesis[];
  directions: string[];
  unresolved: string[];
}

interface Capture {
  proposal?: Proposal;
  review?: Review;
}

/** A finished agent: stable key, model, final text, live session, emitter. */
interface AgentResult {
  roleKey: string;
  modelId: string;
  reasoning: ReasoningLevel;
  role: string;
  stage: string;
  text: string;
  session: AgentSession;
  emit: (event: ProgressEvent) => void;
  capture?: Capture;
}

/** The seat parameters executeAgent runs one agent with. */
interface Seat {
  modelId: string;
  reasoning: ReasoningLevel;
  roleKey: string;
  role: string;
  stage: string;
  customTools: ToolDefinition[];
  emit: (event: ProgressEvent) => void;
  capture?: Capture;
  interruptedRetries?: number;
}

/** The result of one executeAgent run: an AgentResult, or a failure string. */
type AgentOutcome = AgentResult | { error: string };

interface FollowUpAnswer {
  text: string;
  timedOut: boolean;
}

const isError = (r: AgentOutcome): r is { error: string } => (r as { error?: string }).error !== undefined;

const APP = "/app";
const WORK = path.join(APP, "workspace");
const CONFIG: RosterConfig = JSON.parse(fs.readFileSync(path.join(APP, "config", "majics.json"), "utf8"));
const HONE: HoneConfig = JSON.parse(fs.readFileSync(path.join(APP, "config", "hone.json"), "utf8"));
const HONE_TOKEN = process.env.HONE_MAJICS_SERVICE_TOKEN ?? "";
if (!HONE_TOKEN) throw new Error("HONE_MAJICS_SERVICE_TOKEN is missing");

/**
 * Pi's custom-provider config accepts a literal apiKey/header value; it does
 * not dereference an environment-variable name.  Hone deliberately
 * materializes only those names into the task so credentials never land in
 * the task bundle or cached image.  Resolve the references only in the live,
 * ephemeral container immediately before ModelRuntime reads models.json.
 */
function hydrateCredentialReferences(file: string): void {
  if (!fs.existsSync(file)) return;
  const config = JSON.parse(fs.readFileSync(file, "utf8")) as {
    providers?: Record<string, { apiKey?: unknown; headers?: unknown; models?: unknown[] }>;
  };
  const hydrateHeaders = (headers: unknown): void => {
    if (!headers || typeof headers !== "object" || Array.isArray(headers)) return;
    for (const [header, reference] of Object.entries(headers as Record<string, unknown>)) {
      if (typeof reference === "string" && process.env[reference]) {
        (headers as Record<string, unknown>)[header] = process.env[reference];
      }
    }
  };
  for (const provider of Object.values(config.providers ?? {})) {
    if (typeof provider.apiKey === "string" && process.env[provider.apiKey]) {
      provider.apiKey = process.env[provider.apiKey];
    }
    hydrateHeaders(provider.headers);
    for (const model of provider.models ?? []) {
      if (model && typeof model === "object") {
        hydrateHeaders((model as { headers?: unknown }).headers);
      }
    }
  }
  fs.writeFileSync(file, JSON.stringify(config, null, 2) + "\n", { mode: 0o600 });
}

hydrateCredentialReferences(path.join(APP, "pi-home", "models.json"));
hydrateCredentialReferences("/root/.pi/agent/models.json");
const modelRuntimePromise = ModelRuntime.create();

const promptFile = (name: string): string =>
  fs.readFileSync(path.join(APP, "config", "prompts", name), "utf8");

const EMPTY_AFTER_WORK_RETRY_PROMPT =
  "Your previous turn had no visible final answer. Please provide the final answer now in visible assistant text only. Do not use hidden thinking as the answer.";
const EMPTY_BEFORE_WORK_RETRY_PROMPT =
  "Your previous turn ended without examining anything and without a visible answer. Start the work now: call your tools to read the code the task refers to, then give the final answer in visible assistant text only. Do not use hidden thinking as the answer.";
const EMPTY_OUTPUT_RETRIES = 3;
const INTERRUPTED_TURN_RETRIES = 2;
const MODEL_TURN_TIMEOUT_MS = 5 * 60 * 1000;
const ASK_PANEL_FOLLOW_UP_TIMEOUT_MS = (CONFIG.followUpTimeoutS ?? 60) * 1000;
const INTERRUPTED_TURN_RETRY_PROMPT =
  "Your previous response was interrupted by a transient stream or network error. Continue from the work already in this session and complete the task now. Do not restart the analysis. If the task requires a final tool call, make that call now.";

/* ------------------------------------------------------------------ events */

const eventsEndpoint = `/api/runs/${HONE.runId}/pipeline-event`;

let posted: Promise<void> = Promise.resolve();

/** Posts one at a time. The service stamps and stores events in arrival order, and the run page reads that order. */
function postEvent(event: ProgressEvent): Promise<void> {
  const body = JSON.stringify(event);
  posted = posted.then(async () => {
    try {
      await fetch(HONE.url + eventsEndpoint, {
        method: "POST",
        headers: { "content-type": "application/json", authorization: `Bearer ${HONE_TOKEN}` },
        body,
      });
    } catch {
      /* best-effort: the run must survive the dashboard being down */
    }
  });
  return posted;
}

function agentSink(roleKey: string, modelId: string, role: string, stage: string) {
  return (event: ProgressEvent): void => {
    void postEvent({ ...event, agent: roleKey, model: modelId, role, stage });
  };
}

/* ------------------------------------------------------ inner agent runner */

function attachActivityLog(session: AgentSession, emit: (e: ProgressEvent) => void): () => void {
  const open = new Map<string, { name: string; detail?: string }>();
  const start = (key: string, name: string, args: unknown): void => {
    const detail = summarizeArgs(args);
    open.set(key, { name, detail });
    emit({
      kind: "tool",
      name,
      detail: detail ? String(detail).slice(0, 400) : undefined,
      ...(name === "ask_panel" ? { queries: askedQueries(args) } : {}),
    });
  };
  const end = (key: string, refused?: string): void => {
    const step = open.get(key);
    if (!step) return;
    open.delete(key);
    emit({ kind: "tool_result", name: step.name, detail: step.detail?.slice(0, 160), ...(refused ? { error: refused.slice(0, 400) } : {}) });
  };
  const unsubscribe = session.subscribe((event: any) => {
    if (event.type === "tool_execution_start") {
      start(event.toolCallId, event.toolName, event.args);
    } else if (event.type === "tool_execution_end") {
      end(event.toolCallId, event.isError ? assistantText(event.result ?? {}) || "tool error" : undefined);
    } else if (event.type === "message_end" && event.message?.role === "assistant") {
      // The session commits a message to its history only at message_end, so read the text off the event.
      const text = assistantText(event.message);
      if (text) emit({ kind: "message", text });
    }
  });
  return () => {
    unsubscribe();
    for (const key of [...open.keys()]) end(key);
  };
}

/** An assistant message's visible text, joined the way AgentSession.getLastAssistantText joins it. */
function assistantText(message: { content?: unknown }): string {
  const parts = Array.isArray(message.content) ? message.content : [];
  return parts
    .map((c: any) => (c?.type === "text" && typeof c.text === "string" ? c.text : ""))
    .join("")
    .trim();
}

function summarizeArgs(args: unknown): string | undefined {
  if (!args || typeof args !== "object") return undefined;
  const a = args as Record<string, unknown>;
  const str = (key: string): string | undefined =>
    typeof a[key] === "string" && a[key] ? String(a[key]) : undefined;
  const pick =
    ["id", "traceId", "path", "query", "pattern", "command"].map(str).find(Boolean) ??
    Object.values(a).find((v): v is string => typeof v === "string" && v.length > 0);
  if (!pick) return undefined;
  const oneLine = pick.replace(/\s+/g, " ").trim();
  return oneLine.length > 120 ? oneLine.slice(0, 119) + "…" : oneLine;
}

/** The judge's ask_panel questions as the activity feed shows them. */
function askedQueries(args: unknown): { role: string; question: string }[] {
  const queries = (args as { queries?: unknown } | null)?.queries;
  if (!Array.isArray(queries)) return [];
  return queries.map((q) => ({
    role: typeof q?.role === "string" ? q.role : "",
    question: typeof q?.question === "string" ? q.question : "",
  }));
}

async function createInnerAgentSession(
  modelId: string,
  reasoning: ReasoningLevel,
  customTools: ToolDefinition[],
): Promise<AgentSession> {
  const modelRuntime = await modelRuntimePromise;
  const slash = modelId.indexOf("/");
  if (slash < 1) throw new Error(`Invalid model id "${modelId}" (expected "provider/model")`);
  const model = modelRuntime.getModel(modelId.slice(0, slash), modelId.slice(slash + 1));
  if (!model) throw new Error(`Unknown model "${modelId}"`);
  const agentDir = path.join(APP, "pi-home");
  const settingsManager = SettingsManager.create(WORK, agentDir);
  const resourceLoader = new DefaultResourceLoader({
    cwd: WORK,
    agentDir,
    settingsManager,
    // Environment-level extensions must not load inside inner agents — the
    // same filtering the reference does.
    extensionsOverride: (base: any) => ({ ...base, extensions: [] }),
  });
  await resourceLoader.reload();
  const { session } = await createAgentSession({
    model,
    modelRuntime,
    cwd: WORK,
    tools: ["bash", ...customTools.map((t) => t.name)],
    customTools,
    thinkingLevel: reasoning,
    resourceLoader,
    settingsManager,
    sessionManager: SessionManager.inMemory(WORK),
  });
  return session;
}

async function executeAgent(seat: {
  modelId: string;
  reasoning: ReasoningLevel;
  roleKey: string;
  role: string;
  stage: string;
  prompt: string;
  customTools?: ToolDefinition[];
  emit: (e: ProgressEvent) => void;
  retryEmpty?: boolean;
  interruptedRetries?: number;
  turnTimeoutMs?: number;
  existingSession?: AgentSession | null;
  capture?: Capture;
}): Promise<AgentOutcome> {
  const { modelId, reasoning, roleKey, role, stage, prompt, emit } = seat;
  const retryEmpty = seat.retryEmpty ?? true;
  const interruptedRetries = seat.interruptedRetries ?? INTERRUPTED_TURN_RETRIES;
  const turnTimeoutMs = seat.turnTimeoutMs ?? MODEL_TURN_TIMEOUT_MS;
  const customTools = seat.customTools ?? [];
  const startedAt = Date.now();
  emit({ kind: "agent_start" });
  let endStatus = "error";
  let endError: string | undefined;
  const modelLabel = `${modelId}@${reasoning}`;
  const fail = (error: string): { error: string } => ({ error: `${modelLabel}: ${error}` });

  let detach = (): void => {};
  let detachCount = (): void => {};
  let session = seat.existingSession ?? null;
  try {
    if (!session) session = await createInnerAgentSession(modelId, reasoning, customTools);
    detach = attachActivityLog(session, agentSink(roleKey, modelLabel, role, stage));
    let toolCalls = 0;
    detachCount = session.subscribe((event: any) => {
      if (event.type === "tool_execution_start") toolCalls++;
    });

    const runPromptTurn = async (turnPrompt: string, retry: boolean): Promise<{ text?: string; empty?: boolean; error?: string }> => {
      const messageCount = session.state.messages.length;
      let timeout: ReturnType<typeof setTimeout> | undefined;
      try {
        try {
          await Promise.race([
            session.prompt(turnPrompt),
            new Promise<never>((_resolve, reject) => {
              timeout = setTimeout(() => {
                reject(new Error(`model turn timeout after ${turnTimeoutMs / 1000}s`));
              }, turnTimeoutMs);
            }),
          ]);
        } catch (e) {
          const message = e instanceof Error ? e.message : String(e);
          if (message.includes("model turn timeout")) {
            await session.abort().catch(() => {});
          }
          return { error: message };
        }
      } finally {
        if (timeout) clearTimeout(timeout);
      }
      const added = session.state.messages.slice(messageCount);
      const last = [...added].reverse().find((m: any) => m.role === "assistant");
      if (!last) {
        return { error: retry ? "empty-output retry produced no response" : "produced no response" };
      }
      if (last.stopReason !== "stop") {
        const detail = last.errorMessage ? `: ${last.errorMessage}` : "";
        return {
          error: `${retry ? "empty-output retry did not complete cleanly" : "did not complete cleanly"} (stopReason: ${last.stopReason})${detail}`,
        };
      }
      const text = session.getLastAssistantText();
      if (!text || text.trim() === "") return { empty: true };
      return { text };
    };

    const first = await runPromptTurn(prompt, false);
    let outcome = first;
    for (
      let attempt = 0;
      outcome.error && attempt < interruptedRetries &&
        /stream|disconnect|closed before|network|connection|timeout|ECONN|fetch failed/i.test(outcome.error);
      attempt++
    ) {
      emit({ kind: "retry", reason: "transient model transport error", attempt: attempt + 1 });
      outcome = await runPromptTurn(INTERRUPTED_TURN_RETRY_PROMPT, true);
    }
    if (outcome.empty && retryEmpty) {
      let retryTurn: { text?: string; empty?: boolean; error?: string } = { empty: true };
      for (let attempt = 0; attempt < EMPTY_OUTPUT_RETRIES && retryTurn.empty; attempt++) {
        retryTurn = await runPromptTurn(
          toolCalls > 0 ? EMPTY_AFTER_WORK_RETRY_PROMPT : EMPTY_BEFORE_WORK_RETRY_PROMPT,
          true,
        );
      }
      outcome = retryTurn;
    }
    if (outcome.error) {
      if (seat.capture?.proposal || seat.capture?.review) {
        endStatus = "done";
        return {
          roleKey, modelId, reasoning, role, stage,
          text: "Validated stage artifact submitted before the transport timeout.",
          session, emit, capture: seat.capture,
        };
      }
      endError = outcome.error;
      session.dispose();
      return fail(outcome.error);
    }
    if (outcome.empty) {
      endError = "returned empty text";
      session.dispose();
      return fail(endError);
    }
    endStatus = "done";
    return { roleKey, modelId, reasoning, role, stage, text: outcome.text!, session, emit, capture: seat.capture };
  } catch (e) {
    endError = e instanceof Error ? e.message : String(e);
    try { session?.dispose(); } catch {}
    return fail(endError);
  } finally {
    try { detachCount(); } catch {}
    detach();
    emit({
      kind: "agent_end",
      status: endStatus,
      durationMs: Date.now() - startedAt,
      ...(endError ? { error: endError } : {}),
    });
  }
}

/** Re-prompt a live session without taking ownership (ask_panel round 2). */
async function rerunAgent(result: AgentResult, question: string): Promise<FollowUpAnswer> {
  const followUpPrompt =
    `Your ask_panel follow-up has a hard ${ASK_PANEL_FOLLOW_UP_TIMEOUT_MS / 1000}-second deadline. ` +
    "Answer directly from the context you already gathered. Use tools only for a quick check. " +
    `Do not restart broad research. State uncertainty if the evidence is incomplete.\n\n${question}`;
  const outcome = await executeAgent({
    modelId: result.modelId,
    reasoning: result.reasoning,
    roleKey: result.roleKey,
    role: result.role,
    stage: result.stage,
    prompt: followUpPrompt,
    emit: result.emit,
    retryEmpty: false,
    interruptedRetries: 0,
    turnTimeoutMs: ASK_PANEL_FOLLOW_UP_TIMEOUT_MS,
    existingSession: result.session,
  });
  if (isError(outcome)) {
    const timedOut = outcome.error.includes("model turn timeout");
    return {
      timedOut,
      text: timedOut
        ? `(no answer: follow-up timed out after ${ASK_PANEL_FOLLOW_UP_TIMEOUT_MS / 1000}s)`
        : `(could not answer: ${outcome.error})`,
    };
  }
  return { text: outcome.text, timedOut: false };
}

/* ------------------------------------------------------------------- panel */

async function runPanel(
  seats: Seat[],
  prompt: string | ((seat: Seat, index: number) => string),
): Promise<AgentResult[]> {
  const controller = new AbortController();
  const results = await Promise.all(
    seats.map(async (seat, index): Promise<AgentOutcome> => {
      try {
        controller.signal.throwIfAborted();
        const seatPrompt = typeof prompt === "string" ? prompt : prompt(seat, index);
        const result = await executeAgent({ ...seat, prompt: seatPrompt });
        if (isError(result)) controller.abort();
        return result;
      } catch (e) {
        controller.abort();
        return { error: e instanceof Error ? e.message : String(e) };
      }
    }),
  );
  const failure = results.find(isError);
  if (failure) {
    for (const r of results) if (!isError(r)) try { r.session.dispose(); } catch {}
    throw new Error(failure.error);
  }
  return results as AgentResult[];
}

/* --------------------------------------------------------- tool arguments */

/**
 * Some models send an array argument as its JSON text. Pi's validator coerces
 * such a string into a one-item array of that text, and a list of objects then
 * fails validation. Decode those strings wherever the schema expects an array,
 * before validation, as Pi's own edit tool does for its `edits` argument. The
 * text can run on into the arguments after it, as in `[…], "note": "…"`, and
 * those come back as the arguments they are.
 */
function decodeJsonArrays(schema: any, value: unknown): unknown {
  if (schema?.type === "array") {
    if (typeof value === "string") {
      try {
        const parsed = JSON.parse(value);
        if (Array.isArray(parsed)) value = parsed;
      } catch {
        /* not JSON, so validation reports it */
      }
    }
    return Array.isArray(value) ? value.map((item) => decodeJsonArrays(schema.items, item)) : value;
  }
  if (schema?.type === "object" && value && typeof value === "object" && !Array.isArray(value)) {
    const members: Record<string, unknown> = { ...value };
    for (const [key, v] of Object.entries(value)) {
      if (schema.properties?.[key]?.type !== "array" || typeof v !== "string") continue;
      const spilled = runOnMembers(key, v);
      if (spilled) Object.assign(members, { ...spilled, ...value, [key]: spilled[key] });
    }
    return Object.fromEntries(
      Object.entries(members).map(([key, v]) => [key, decodeJsonArrays(schema.properties?.[key], v)]),
    );
  }
  return value;
}

/** `key`'s JSON text read as the rest of the call's arguments, with or without their closing brace, when it is not JSON on its own. */
function runOnMembers(key: string, text: string): Record<string, unknown> | null {
  try {
    JSON.parse(text);
    return null;
  } catch {
    /* read on below */
  }
  const members = `{${JSON.stringify(key)}:${text}`;
  for (const object of [members, `${members}}`]) {
    try {
      return JSON.parse(object);
    } catch {
      /* try with the closing brace */
    }
  }
  return null;
}

/* --------------------------------------------------------------- ask_panel */

function makeAskPanelTool(panel: AgentResult[]): ToolDefinition {
  const valid = panel.map((r) => r.roleKey).join(", ");
  const parameters = Type.Object({
    queries: Type.Array(
      Type.Object({
        role: Type.String({ description: `Which author to re-query. One of: ${valid}` }),
        question: Type.String({
          description:
            "The follow-up for that author — e.g. another author's point to react to, or a disputed " +
            "claim to defend or concede. It still remembers its own earlier analysis.",
        }),
      }),
      { minItems: 1, description: "Every follow-up to ask. Send all reviewers in a SINGLE call." },
    ),
  });
  return defineTool({
    name: "ask_panel",
    label: "ask panel",
    description:
      "Re-query one or more analyses' authors for a second round (cross-examine a disagreement or " +
      "pressure a disputed point). Pass every follow-up in one call. Different authors run in " +
      `parallel; repeated queries to one author run sequentially. Each follow-up has a ${ASK_PANEL_FOLLOW_UP_TIMEOUT_MS / 1000}s ` +
      `deadline; completed answers are returned when another author times out. Valid roles: ${valid}.`,
    parameters,
    prepareArguments: (args) => decodeJsonArrays(parameters, args) as any,
    async execute(_toolCallId: string, params: { queries: { role: string; question: string }[] }) {
      const startedAt = Date.now();
      const answers: string[] = new Array(params.queries.length);
      const replies: { role: string; text: string }[] = params.queries.map((q) => ({ role: q.role, text: "" }));
      const timedOutRoles = new Set<string>();
      let timedOutQueries = 0;
      const byRole = new Map<string, { index: number; question: string }[]>();
      params.queries.forEach((q, index) => {
        const queue = byRole.get(q.role) ?? [];
        queue.push({ index, question: q.question });
        byRole.set(q.role, queue);
      });
      await Promise.all(
        [...byRole.entries()].map(async ([role, queue]) => {
          const target = panel.find((r) => r.roleKey === role);
          if (!target) {
            for (const q of queue) {
              answers[q.index] = `### ${role}\nUnknown reviewer role "${role}". Valid roles: ${valid}.`;
            }
            return;
          }
          for (const q of queue) {
            const answer = await rerunAgent(target, q.question);
            if (answer.timedOut) {
              timedOutRoles.add(target.roleKey);
              timedOutQueries++;
            }
            replies[q.index].text = answer.text;
            answers[q.index] = `### ${target.roleKey} (${target.modelId})\n${answer.text}`;
          }
        }),
      );
      const judge = CONFIG.mode === "review" ? CONFIG.reviewJudge : CONFIG.proposeJudge;
      await postEvent({
        kind: "analytics",
        name: "ask_panel",
        stage: CONFIG.mode,
        agent: `${CONFIG.mode}-judge`,
        model: `${judge.id}@${judge.reasoning}`,
        role: "judge",
        workersAsked: [...byRole.keys()].filter((role) => panel.some((worker) => worker.roleKey === role)).length,
        workersTimedOut: timedOutRoles.size,
        timedOutRoles: [...timedOutRoles],
        queriesAsked: params.queries.length,
        queriesTimedOut: timedOutQueries,
        // Each answer exactly as the judge receives it, in query order.
        answers: replies,
        timeoutMs: ASK_PANEL_FOLLOW_UP_TIMEOUT_MS,
        durationMs: Date.now() - startedAt,
        text: `ask_panel: ${timedOutRoles.size} worker timeout(s)`,
        detail: timedOutRoles.size ? [...timedOutRoles].join(", ") : "none",
      });
      return { content: [{ type: "text" as const, text: answers.join("\n\n") }] };
    },
  });
}

/* -------------------------------------------------------- workspace tools */

const batch: string[] = JSON.parse(fs.readFileSync(path.join(WORK, "batch.json"), "utf8"));

/* --------------------------------------------------------- submit_review */

/** Text a visitor reads on the run page must be whole: no sentence cut at an open bracket, no JSON escapes left in. */
function brokenText(text: string): string | null {
  if (text.includes('\\"')) return 'contains escaped quotes (\\"), write plain quotes';
  for (const [open, close] of [["(", ")"], ["[", "]"]] as const) {
    if (text.split(open).length !== text.split(close).length) return `is cut off or has an unmatched "${open}", finish the sentence`;
  }
  if (/[(\[,:]\s*$/.test(text)) return "ends mid sentence, finish it";
  return null;
}

function submitReviewTool(capture: Capture): ToolDefinition {
  const confidence = Type.Union([
    Type.Literal("low"),
    Type.Literal("medium"),
    Type.Literal("high"),
  ]);
  const cited = {
    statement: Type.String({ description: "One observed fact or bounded hypothesis." }),
    traceIds: Type.Array(Type.String(), { description: "Trace ids that support this item." }),
    confidence,
  };
  // review.json's version is the driver's to stamp, not a constant the judge has to echo back.
  const parameters = Type.Object({
    summary: Type.String(),
    findings: Type.Array(Type.Object(cited)),
    hypotheses: Type.Array(Type.Object({
      ...cited,
      contradictions: Type.Optional(Type.Array(Type.String())),
    })),
    directions: Type.Array(Type.String()),
    unresolved: Type.Array(Type.String()),
  });
  return defineTool({
    name: "submit_review",
    label: "Submit judged review",
    description:
      "Submit the single fused review after reading all worker reports and completing any needed cross-examination.",
    parameters,
    prepareArguments: (args) => decodeJsonArrays(parameters, args) as any,
    async execute(_toolCallId: string, params: Omit<Review, "version">) {
      const fail = (text: string) => ({
        content: [{ type: "text" as const, text: `submit_review failed: ${text}` }],
        isError: true,
      });
      if (!params.summary.trim()) return fail("summary is empty");
      const summaryProblem = brokenText(params.summary);
      if (summaryProblem) return fail(`the summary ${summaryProblem}`);
      for (const item of [...params.findings, ...params.hypotheses]) {
        if (!item.statement.trim()) return fail("an item statement is empty");
        const problem = brokenText(item.statement);
        if (problem) return fail(`this statement ${problem}: ${item.statement.slice(-80)}`);
        if (!item.traceIds.length) return fail(`item has no trace ids: ${item.statement.slice(0, 80)}`);
        const unknown = item.traceIds.filter((traceId) => !batch.includes(traceId));
        if (unknown.length) return fail(`unknown trace ids: ${unknown.join(", ")}`);
      }
      capture.review = { ...params, version: 1 };
      return {
        content: [{
          type: "text" as const,
          text: "review recorded. Reply with a one-line confirmation and stop.",
        }],
      };
    },
  });
}

/* ------------------------------------------------------- submit_proposal */

/** The longest commit title the service commits. */
const TITLE_MAX = 72;

/**
 * The judge's commit title, or the title without its last word when only that word
 * runs past {@link TITLE_MAX} characters. Judges overshoot by a word, as in "Add
 * Beijing-day conversion, yuan amounts, and audit-before-flagging rules" (73), and
 * refusing it made them send the whole proposal again. Null when it does not fit.
 */
function fitTitle(title: string): string | null {
  const whole = title.trim();
  if (whole.length <= TITLE_MAX) return whole || null;
  const space = whole.lastIndexOf(" ");
  let fitted = space > 0 ? whole.slice(0, space) : "";
  const dangling = /(?:[\s,;:\u2013\u2014-]+|\s+(?:and|or|plus|for|to|with|of|in|on|the|a|an))$/i;
  while (dangling.test(fitted)) fitted = fitted.replace(dangling, "");
  return fitted && fitted.length <= TITLE_MAX ? fitted : null;
}

/** The proposers' and the propose judge's answer channel: validated at call
 *  time. Anchors must match the current file exactly once, evidence must be
 *  batch trace ids, and commit messages must be present and concise. */
function submitProposalTool({ judge, capture, agentsMd }: {
  judge: boolean;
  capture: Capture;
  agentsMd: string;
}): ToolDefinition {
  const properties: Record<string, any> = {
    edits: Type.Array(
      Type.Object({
        oldText: Type.String({
          description: "Exact existing text to replace. Must match exactly once in the current AGENTS.md. Empty for a pure insertion.",
        }),
        newText: Type.String({ description: "Replacement text (the full new line(s)). Empty for a deletion." }),
        rationale: Type.String({ description: "1-3 sentences: which finding this addresses and why the edit changes the behavior." }),
        evidence: Type.Array(Type.String(), { description: "Trace ids from the batch that evidence this edit." }),
      }),
      { maxItems: 5, description: "0-5 surgical line edits, one per distinct signal." },
    ),
    note: Type.Optional(Type.String({ description: "One sentence on why this edit set (or why none)." })),
  };
  if (judge) {
    properties.commit_title = Type.String({ description: "Clear commit title, <= 72 characters." });
    properties.commit_body = Type.String({ description: "1-4 sentences: what changed and why." });
  }
  const parameters = Type.Object(properties, {
    required: judge ? ["edits", "commit_title", "commit_body"] : ["edits"],
  });
  return defineTool({
    name: "submit_proposal",
    label: "Submit proposal",
    description: judge
      ? "Submit the fused final proposal. This is your final answer — call exactly once, after cross-examination."
      : "Submit the final edit proposal for AGENTS.md. Call exactly once.",
    parameters,
    prepareArguments: (args) => decodeJsonArrays(parameters, args) as any,
    async execute(_toolCallId: string, params: any) {
      const fail = (text: string) => ({ content: [{ type: "text" as const, text: `submit_proposal failed: ${text}` }], isError: true });
      if (!Array.isArray(params.edits)) return fail("edits must be an array");
      let text = agentsMd;
      for (let i = 0; i < params.edits.length; i++) {
        const e: ProposalEdit = params.edits[i];
        if (!e.rationale?.trim()) return fail(`edit ${i + 1} rationale missing`);
        if (!Array.isArray(e.evidence) || e.evidence.length === 0) return fail(`edit ${i + 1} evidence is empty`);
        const bad = e.evidence.filter((x: string) => !batch.includes(x));
        if (bad.length) return fail(`edit ${i + 1} evidence [${bad.join(", ")}] not in the frozen batch`);
        if (e.oldText) {
          const n = text.split(e.oldText).length - 1;
          if (n === 0) return fail(`edit ${i + 1} oldText not found in the current AGENTS.md — copy the anchor verbatim from /app/workspace/agents.md`);
          if (n > 1) return fail(`edit ${i + 1} oldText matched ${n} places — add surrounding context to make it unique`);
          text = text.replace(e.oldText, e.newText);
        }
      }
      if (judge) {
        const title = fitTitle(params.commit_title ?? "");
        if (!title) return fail("commit_title must be present and at most 72 characters");
        params.commit_title = title;
        if (!(params.commit_body ?? "").trim()) return fail("commit_body missing — explain the changes");
      }
      capture.proposal = params;
      const summary = `proposal recorded: ${params.edits.length} edit(s)` +
        (judge ? ` · commit: ${params.commit_title}` : "") +
        ". You are done — reply with a one-line confirmation and stop.";
      return { content: [{ type: "text" as const, text: summary }] };
    },
  });
}

/* ------------------------------------------------------------------ judge */

function buildJudgePrompt(panel: AgentResult[], task: string, output: string, contributions?: string[]): string {
  const texts = contributions ?? panel.map((p) => p.text);
  const analyses = panel.map((p, i) => `### ${p.roleKey} (${p.modelId})\n${texts[i]}`).join("\n\n");
  const roles = panel.map((p) => p.roleKey).join(", ");
  // A replacer function keeps `$'` and `$&` in model-written text literal, as in `tr -d $'\r'`.
  return `${task}\n\n${output}`
    .replaceAll("{{PANEL_ROLES}}", roles)
    .replaceAll("{{PANEL_REPORTS}}", () => analyses);
}

/* ------------------------------------------------------------------ stages */

function rosterPayload(): { key: string; model: string; role: string; stage: string; color: string }[] {
  const agents: { key: string; model: string; role: string; stage: string; color: string }[] = [];
  const colors = ["#2fbcb0", "#d99a3c", "#b06ee8", "#4aa3f0", "#e5736e"];
  CONFIG.reviewModels.forEach((spec, i) => {
    agents.push({ key: `review-${i + 1}`, model: `${spec.id}@${spec.reasoning}`, role: "reviewer", stage: "review", color: colors[i % colors.length] });
  });
  agents.push({ key: "review-judge", model: `${CONFIG.reviewJudge.id}@${CONFIG.reviewJudge.reasoning}`, role: "judge", stage: "review", color: "#6672e0" });
  CONFIG.proposeModels.forEach((spec, i) => {
    agents.push({ key: `propose-${i + 1}`, model: `${spec.id}@${spec.reasoning}`, role: "proposer", stage: "propose", color: colors[(i + 2) % colors.length] });
  });
  agents.push({ key: "propose-judge", model: `${CONFIG.proposeJudge.id}@${CONFIG.proposeJudge.reasoning}`, role: "judge", stage: "propose", color: "#6672e0" });
  return agents;
}

function seat(key: string, spec: ModelSpec, role: string, stage: string, customTools: ToolDefinition[]): Seat {
  const modelLabel = `${spec.id}@${spec.reasoning}`;
  return {
    modelId: spec.id,
    reasoning: spec.reasoning,
    roleKey: key,
    role,
    stage,
    customTools,
    emit: agentSink(key, modelLabel, role, stage),
  };
}

async function reviewStage(): Promise<void> {
  await postEvent({ kind: "stage", stage: "review", status: "start" });
  const startedAt = Date.now();
  const seats = CONFIG.reviewModels.map((spec, i) =>
    seat(`review-${i + 1}`, spec, "reviewer", "review", []));
  const sharedCoverage = batch.length <= 8;
  const panel = await runPanel(seats, (_seat, reviewerIndex) => {
    const assigned = sharedCoverage
      ? batch
      : batch.filter((_traceId, traceIndex) => traceIndex % seats.length === reviewerIndex);
    return promptFile("reviewer.txt")
      .replaceAll("{{BATCH_TRACE_IDS}}", batch.join(", ") || "(none)")
      .replaceAll("{{ASSIGNED_TRACE_IDS}}", assigned.join(", ") || "(none)")
      .replaceAll("{{COVERAGE_MODE}}", sharedCoverage ? "full" : "sharded");
  });

  const judgeCapture: Capture = {};
  const judgeSeat = seat("review-judge", CONFIG.reviewJudge, "judge", "review", [
    makeAskPanelTool(panel),
    submitReviewTool(judgeCapture),
  ]);
  const prompt = buildJudgePrompt(panel, promptFile("review-judge-task.txt"), promptFile("review-judge-output.txt"));
  let judge = await executeAgent({ ...judgeSeat, prompt, capture: judgeCapture });
  if (isError(judge)) throw new Error(`review judge ${judge.error}`);
  let nudges = 0;
  while (!judgeCapture.review && nudges < 3) {
    nudges++;
    judge = await executeAgent({
      ...judgeSeat,
      prompt: "You have not called submit_review. Call it now with the single proven review artifact, then stop.",
      retryEmpty: false,
      existingSession: judge.session,
      capture: judgeCapture,
    });
    if (isError(judge)) throw new Error(`review judge ${judge.error}`);
  }
  if (!judgeCapture.review) throw new Error("review judge never called submit_review");
  const review = JSON.stringify(judgeCapture.review, null, 2) + "\n";
  fs.writeFileSync(path.join(APP, "review.json"), review, "utf8");
  await postEvent({ kind: "stage", stage: "review", status: "end", durationMs: Date.now() - startedAt });
  await postEvent({ kind: "report", bytes: Buffer.byteLength(review), title: judgeCapture.review.summary });
  for (const r of panel) try { r.session.dispose(); } catch {}
  try { judge.session.dispose(); } catch {}
}

function proposalText(result: AgentResult): string {
  const p = result.capture?.proposal ?? { edits: [] as ProposalEdit[] };
  const edits = p.edits ?? [];
  if (!edits.length) return `No edits. ${p.note ?? "No defensible signal found."}`;
  const lines = [`${edits.length} edit(s). ${p.note ?? ""}`.trim()];
  edits.forEach((e, i) => {
    lines.push(
      `${i + 1}. oldText: ${JSON.stringify(e.oldText ?? "")}`,
      `   newText: ${JSON.stringify(e.newText ?? "")}`,
      `   rationale: ${e.rationale}`,
      `   evidence: ${(e.evidence ?? []).join(", ")}`,
    );
  });
  return lines.join("\n");
}

async function proposeStage(): Promise<Proposal> {
  await postEvent({ kind: "stage", stage: "propose", status: "start" });
  const startedAt = Date.now();
  const agentsMd = fs.readFileSync(path.join(WORK, "agents.md"), "utf8");
  const review = fs.readFileSync(path.join(WORK, "review.json"), "utf8");

  const rejection = CONFIG.rejection
    ? `## Previous attempt rejected — fix it\n\nThe proposal you are replacing was rejected by the verifier:\n\n\`\`\`\n${CONFIG.rejection}\n\`\`\`\n\nIf an oldText anchor was ambiguous or missing, copy it exactly from the CURRENT /app/workspace/agents.md; the file may have changed.\n\n`
    : "";
  const prompt = promptFile("proposer.txt")
    .replaceAll("{{REVIEW}}", () => review)
    .replaceAll("{{REJECTION}}", () => rejection);

  const panelSeats = CONFIG.proposeModels.map((spec, i) => {
    const capture: { proposal?: Proposal } = {};
    const tools = [submitProposalTool({ judge: false, capture, agentsMd })];
    return { ...seat(`propose-${i + 1}`, spec, "proposer", "propose", tools), capture, interruptedRetries: 0 };
  });
  const panel = await runPanel(panelSeats, prompt);
  panel.forEach((result, i) => {
    result.capture = panelSeats[i].capture;
    result.role = "proposer";
    result.stage = "propose";
  });

  // A proposer that finished without submitting gets one nudge (the
  // reference's empty-output retry); still missing → the panel fails.
  for (const result of panel) {
    if (!result.capture?.proposal) {
      const seatConfig = panelSeats.find((s) => s.roleKey === result.roleKey)!;
      const retry = await executeAgent({
        modelId: result.modelId,
        reasoning: result.reasoning,
        roleKey: result.roleKey,
        role: "proposer",
        stage: "propose",
        customTools: seatConfig.customTools,
        emit: result.emit,
        prompt: "You finished without calling submit_proposal. Call it now with your final edit set (0 edits is valid when nothing is defensible), then stop.",
        retryEmpty: false,
        existingSession: result.session,
      });
      if (isError(retry)) throw new Error(`proposer ${retry.error}`);
    }
  }
  const missing = panel.filter((r) => !r.capture?.proposal);
  if (missing.length) {
    throw new Error(`${missing[0].roleKey} (${missing[0].modelId}) finished without submitting a proposal`);
  }
  for (const result of panel) {
    const p = result.capture!.proposal!;
    await postEvent({
      kind: "proposal",
      agent: result.roleKey,
      count: p.edits.length,
      note: p.note ?? "",
      edits: p.edits.map((e) => ({
        oldText: e.oldText ?? "",
        newText: e.newText ?? "",
        rationale: e.rationale ?? "",
        evidence: e.evidence ?? [],
      })),
    });
  }

  // The propose judge cross-examines the live proposers, then uses
  // submit_proposal as its final answer channel.
  const judgeCapture: { proposal?: Proposal } = {};
  const judgeTools = [
    makeAskPanelTool(panel),
    submitProposalTool({ judge: true, capture: judgeCapture, agentsMd }),
  ];
  const judgeSeat = seat("propose-judge", CONFIG.proposeJudge, "judge", "propose", judgeTools);
  const judgePrompt = buildJudgePrompt(
    panel,
    promptFile("propose-judge-task.txt"),
    promptFile("propose-judge-output.txt"),
    panel.map(proposalText),
  );
  let judge = await executeAgent({ ...judgeSeat, prompt: judgePrompt, capture: judgeCapture });
  if (isError(judge)) throw new Error(`propose judge ${judge.error}`);
  let nudges = 0;
  while (!judgeCapture.proposal && nudges < 3) {
    nudges++;
    judge = await executeAgent({
      ...judgeSeat,
      prompt: "You have not called submit_proposal yet. Call it now with the fused final proposal (0-5 edits, commit_title, commit_body), then stop.",
      retryEmpty: false,
      existingSession: judge.session,
      capture: judgeCapture,
    });
    if (isError(judge)) throw new Error(`propose judge ${judge.error}`);
  }
  if (!judgeCapture.proposal) throw new Error("propose judge never called submit_proposal");
  await postEvent({ kind: "stage", stage: "propose", status: "end", durationMs: Date.now() - startedAt });

  const proposal = judgeCapture.proposal;
  await postEvent({ kind: "commit", title: proposal.commit_title, body: proposal.commit_body });
  fs.writeFileSync(
    path.join(APP, "proposal.json"),
    JSON.stringify({
      edits: proposal.edits,
      note: proposal.note ?? "",
      commit_title: proposal.commit_title ?? "",
      commit_body: proposal.commit_body ?? "",
    }, null, 2) + "\n",
    "utf8",
  );
  for (const r of panel) try { r.session.dispose(); } catch {}
  try { judge.session.dispose(); } catch {}
  return proposal;
}

/* ------------------------------------------------------------------- main */

async function main(): Promise<void> {
  // The artifact collector expects this file to exist even on success.
  fs.writeFileSync(path.join(APP, "driver-error.txt"), "", "utf8");
  await postEvent({ kind: "pipeline", attempt: CONFIG.attempt ?? 1, agents: rosterPayload() });
  if (CONFIG.mode === "review") {
    await reviewStage();
    console.log("MAJICS review stage done: review.json written");
  } else if (CONFIG.mode === "propose") {
    const proposal = await proposeStage();
    console.log(`MAJICS propose stage done: ${proposal.edits.length} edit(s), commit: ${proposal.commit_title}`);
  } else {
    throw new Error(`unknown mode "${CONFIG.mode}" (expected review|propose)`);
  }
}

main().catch((err: unknown) => {
  console.error("MAJICS driver failed:", err);
  fs.writeFileSync(
    path.join(APP, "driver-error.txt"),
    `${err instanceof Error ? err.stack ?? err.message : String(err)}\n`,
    "utf8",
  );
  process.exitCode = 1;
});
