# Hone in t3code

[t3code](https://github.com/pingdotgg/t3code) is a web interface for coding agents. With these
patches, a Pi agent driven from t3code shows its Hone connection and sends feedback to Hone:

- A chip in the chat header shows that the agent is connected to Hone, which `AGENTS.md`
  version it runs, and how full the next optimization batch is. It shows `optimizing…` during
  a run and raises a toast when a session reaches Hone or `AGENTS.md` changes. Clicking it opens
  the Hone dashboard.
- Each Pi reply gets thumbs up and thumbs down buttons. A session holds one feedback in Hone, a
  rating and a comment. The pressed thumb shows the rating, and the comment under the newest reply
  expands to its full text. Either thumb opens a popover with the comment filled in. Save replaces
  the feedback with that thumb's rating, and Remove feedback clears it.

Pi itself needs no patch. t3code runs `pi --mode rpc` per thread, so Pi loads the Hone extension
(`clients/pi-extensions/hone.ts`) like any user extension: it syncs `AGENTS.md` into the project
folder at session start and publishes the session trace after each reply.

## Patches

`patches/` applies to t3code commit `ac8dce0cc3abd8a337f2d806b5082a6834b9b81a`.

| Patch | Adds |
|---|---|
| `0001` | `hone.status` and `hone.feedback` RPCs (`packages/contracts/src/hone.ts`, `apps/server/src/hone/Hone.ts`) |
| `0002` | The header chip and the reply rating control (`apps/web/src/components/chat/HoneControls.tsx`) |
| `0003` | The booth demo seeder, the `hone.demoReset` and `hone.threadFeedback` RPCs, and the Hone page and Reset demo button in the sidebar (`apps/server/src/hone/HoneDemo.ts`, `apps/web/src/components/hone/HonePage.tsx`) |
| `0004` | Sign-in through an authenticating reverse proxy, with no pairing link (`apps/server/src/auth/proxyAuth.ts`) |
| `0005` | One feedback per session that can be read in full, edited and removed. `hone.feedback` sets or clears it through Hone's `POST` and `DELETE /api/traces/{id}/feedback`, and `hone.threadFeedback` returns its rating and comment (`apps/web/src/components/chat/HoneControls.tsx`) |
| `0006` | `HONE_DEMO_MODEL` names the Pi model the demo project and its prepared chats use, so the picker can hide Pi's `default` entry (`apps/server/src/hone/HoneDemo.ts`) |
| `0007` | The orchestration WebSocket at `/api/ws/`, for reverse proxies that upgrade only that prefix (`apps/server/src/ws.ts`) |
| `0008` | Guide mode for the booth, the `hone.guideUnlock` RPC and the guide settings in `hone.status` (`apps/web/src/components/hone/guide/`) |
| `0009` | The agent turn cache, a Pi wrapper that replays a recorded first turn of a demo chat (`apps/server/scripts/hone-pi.ts`) |
| `0010` | No GitHub star prompt while the server runs the Hone demo, since booth visitors share one browser (`apps/web/src/components/chat/useComposerSend.ts`) |
| `0011` | A turn cache hit when the message differs from the recording only in whitespace (`apps/server/scripts/hone-pi.ts`) |
| `0012` | A two second press and hold to end the booth video (`apps/web/src/components/hone/guide/GuideLayer.tsx`) |
| `0013` | Start over in every guide step card and next to the Guide button (`apps/web/src/components/hone/guide/useGuideStartOver.ts`) |
| `0014` | A booth video that fades in, ends only on a key or mouse press held 1.5 seconds with a Keep holding ring, and plays after 30 idle seconds by default (`apps/web/src/components/hone/guide/GuideLayer.tsx`) |

The t3code server calls Hone for status and feedback, so those calls need no token in the browser and
Hone needs no CORS. The Hone page in demo mode loads the dashboard itself, which reads the write token
when Hone exposes it, so keep Hone bound to 127.0.0.1 on a shared network.
Feedback finds the thread's Pi session file from t3code's stored thread record, so it works after
the Pi process exits.

## Set up

Requirements: Node 26.12.1 and `vp` (Vite+) for t3code, Pi 1.5 or newer, and a running Hone
service.

```sh
git clone https://github.com/pingdotgg/t3code && cd t3code
git checkout ac8dce0cc3abd8a337f2d806b5082a6834b9b81a
git am /path/to/hone/clients/t3code/patches/*.patch
vp i
(cd apps/web && vp build)
```

Install the Hone extension for Pi and choose Pi's model:

```sh
mkdir -p ~/.pi/agent/extensions
ln -s /path/to/hone/clients/pi-extensions/hone.ts ~/.pi/agent/extensions/hone.ts
cat > ~/.pi/agent/settings.json <<'EOF'
{ "defaultProvider": "opencode-go", "defaultModel": "deepseek-v4.1-flash" }
EOF
```

Start the t3code server with the Hone settings in its environment. Pi inherits them.

```sh
export HONE_URL=http://127.0.0.1:8080      # where the t3code server reaches Hone
export HONE_TOKEN=...                       # Hone write token
export HONE_DASHBOARD_URL=https://hone.example.com   # optional public link for the chip
export OPENCODE_API_KEY=...                 # the model key Pi uses
cd apps/server && node src/bin.ts serve --port 3773
```

Then:

1. Enable Pi under Settings → Providers. Disable the providers you do not use.
2. Add the project folder: `node src/bin.ts project add /path/to/folder --title "…"`. It does not
   need to be a git repository.
3. Create a browser pairing link:
   `node src/bin.ts auth pairing create --base-url https://t3.example.com --ttl 7d`.
   Each link works once. The browser stays signed in for 30 days.

The extension skips `--no-session` processes, which t3code starts to discover models and commands,
so it does not write `AGENTS.md` into the t3code server's folder.

## Booth demo

Start the t3code server with `HONE_DEMO=1` next to a Hone service that also runs with
`HONE_DEMO=1` on a data folder of its own (`HONE_DATA_DIR`). Hone refuses a demo reset on a data
folder that holds a real history. Nothing changes when demo mode is off.

```sh
export HONE_DEMO=1
export HONE_DEMO_DIR="$HOME/Hone demo/Offer letters"   # a new, empty folder for the demo project
export HONE_DEMO_MODEL=opencode-go/deepseek-v4.1-flash  # optional, Pi's default when unset
```

- On every start, and on the Reset demo button in the sidebar, the server calls Hone's
  `POST /api/demo/reset`. It deletes the previous demo project and its chats, rewrites
  `HONE_DEMO_DIR` from Hone's files, and loads the prepared chats with their tool calls,
  replies and documents. Open browsers update at once and stay signed in. If Hone is not up yet,
  the start retries for five minutes.
- `HONE_DEMO_DIR` defaults to `hone-demo` in the t3code data folder. Everything in it is replaced
  on each reset, so the server only takes over an empty folder or the one its last reset created.
- Each prepared chat is bound to its own copy of the Pi session file, so a new message continues
  the same Pi session. The rating control on its replies shows the feedback Hone already holds.
- Demo chats open with the Files panel. Drag files from `Inbox/` into the composer to start a
  live chat.
- The Hone button next to Settings, Usage and Pull requests shows the Hone dashboard inside
  t3code. It loads `HONE_DASHBOARD_URL`, or `HONE_URL` when that is not set, so the browser must
  reach that address. The header chip opens the same page.

## Guide mode

Guide mode lets a visitor try the booth demo alone. A card walks them through the offer letter
scenario one step at a time. It outlines the control to use, says why, and moves on when the
visitor does the real thing, such as sending the chat or pressing Start optimization. Back and
Skip are always there, and a bar shows the progress.

1. Meet Hone. One screen on what Hone does.
2. Open the prepared chat for Olivia Grant and read the feedback under the reply.
3. Start a new chat. The guide writes the request and adds the two Inbox files. The visitor
   presses send.
4. Watch the agent work, open `Offer_Osei_Amara.pdf` and spot the £0 bonus and 0 shares rows.
5. Press thumbs down. The guide writes the feedback. The visitor presses Send to Hone.
6. Click the Hone chip, press Start optimization and watch the reviewers and the judge.
7. Open Versions and see the new rule. The last card has a QR code to the repository and a Start
   over button.

The steps on the Hone page follow messages the Hone dashboard posts to t3code from its frame,
for the route, Start optimization, and the start and end of a run. Each side checks the other's
origin. t3code asks the frame to outline Start optimization, the judge's open question and
Versions. A run that replays a recording takes about a minute and a half and a real one about
ten minutes, and the card says which. During a real run the card offers the booth video. A run
that fails sends the visitor back to Start optimization.

The Guide button in the sidebar footer turns guide mode on. It stays on through reloads, and
Reset demo gives way to Start over while it is on. Start over is also in every step card. It
asks first, then resets the demo the way Reset demo does and shows the welcome card. To leave
guide mode, hold the button for two seconds, then enter the PIN when one is set. After a short
idle the booth video fades in full screen and muted, with the hint "Hold any key to try Hone
yourself". Taps, mouse moves and key presses neither end it nor count as activity. A press or
any key held for 1.5 seconds ends it, and a ring labelled Keep holding fills in the middle of
the screen while the visitor holds. After a long idle the
guide resets the demo and shows the welcome card again, also while the video plays. Idle time
does not count while the agent or an optimization works.

| Variable | Default | Meaning |
|---|---|---|
| `HONE_GUIDE_VIDEO_URL` | none | The booth video. Without it the guide plays no video |
| `HONE_GUIDE_IDLE_VIDEO_SECONDS` | `30` | Idle seconds before the video plays, `0` for never |
| `HONE_GUIDE_IDLE_RESET_SECONDS` | `300` | Idle seconds before the demo starts over, `0` for never |
| `HONE_GUIDE_PIN` | none | The PIN that ends guide mode. Without it the hold is enough |

All guide text is in one table, `apps/web/src/components/hone/guide/guideText.ts`, so another
language can be added next to English.

## Agent turn cache

A live model answers differently every time, so a visitor's chat would never match a recorded
optimization run. In the booth demo, Pi's binary path points at `apps/server/scripts/hone-pi.ts`.
It starts the real Pi and passes every message through. When the first message of a new chat,
the model, the thinking level, the file names in the project folder, and the contents of
`AGENTS.md` and of the files the message links to match a recording, it plays
the recorded Pi events back at their recorded pace, with each pause cut to 1.5 seconds. It writes
the files the turn wrote, writes the Pi session file and sends it to Hone with the same request the
Hone extension sends after a reply. Pi then loads that session, so a follow-up message continues
it live. Anything that differs runs live. An upload counts by its name and content, not by where
t3code saved it. Other files count by name only, because a rebuilt demo writes the prepared
letters again with a new PDF creation date.

A replay leaves `<session file>.hone-replay.json` next to the Pi session file, with the recording
key, the recording date and the source session. Nothing on the page shows it.

| Variable | Meaning |
|---|---|
| `HONE_TURN_CACHE_DIR` | Recording folders separated by `:`. New recordings go to the first. Unset, Pi runs untouched |
| `HONE_TURN_CACHE_RECORD` | `1` records the first turn of each new chat that matches no recording |
| `HONE_TURN_CACHE_MAX_GAP_MS` | The longest pause in a replay, `1500` by default |
| `HONE_PI_BIN` | The real Pi, `pi` on `PATH` by default |

A recording is the Pi output of a real turn, recorded as it happens. Never write one by hand.
Shipped recordings live in `clients/t3code/turn-cache/`.

## Sign in through a reverse proxy

Patch `0004` lets a reverse proxy own sign-in, so the booth needs one shared login and no pairing
link. Set `T3CODE_PROXY_AUTH_SECRET` to a long random value, for example from
`openssl rand -hex 32`, and have the proxy send it in the `X-T3code-Proxy-Auth` header with every
request, WebSocket upgrades included. A Caddy site for this looks like the following.

```caddy
booth.example.com {
	basic_auth {
		booth <bcrypt hash from `caddy hash-password`>
	}
	reverse_proxy t3code:3773 {
		header_up X-T3code-Proxy-Auth {$T3CODE_PROXY_AUTH_SECRET}
	}
}
```

- A browser that comes through the proxy gets a normal 30-day session with full access on its
  first visit. It never sees a pairing page, and the server prints no pairing URL at start.
- The server answers 401 to every request without the right secret, so a published container port
  does not bypass the proxy. A session cookie alone is not enough either.
- Requests that bring their own bearer token and no cookie still pass. They come from the `t3`
  CLI and from agents inside the container, which hold tokens the server issued them.
- Without the variable the server behaves as before.
