# Hone in t3code

[t3code](https://github.com/pingdotgg/t3code) is a web interface for coding agents. With these
patches, a Pi agent driven from t3code shows its Hone connection and sends feedback to Hone:

- A chip in the chat header shows that the agent is connected to Hone, which `AGENTS.md`
  version it runs, and how full the next optimization batch is. It shows `optimizing…` during
  a run and raises a toast when a session reaches Hone or `AGENTS.md` changes. Clicking it opens
  the Hone dashboard.
- Each Pi reply gets thumbs up and thumbs down buttons. Either one opens a popover with the
  feedback Hone already holds for the session, where each entry can be edited or removed, and a
  comment box for a new entry. A new rating and comment are appended to the session's Hone trace.
  The pressed thumb shows the newest rating, and the feedback under the newest reply expands to
  its full text.

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
| `0005` | Feedback that can be read in full, edited and removed, and the `hone.replaceFeedback` RPC that sends the edited list to Hone's `PUT /api/traces/{id}/feedback` (`apps/web/src/components/chat/HoneControls.tsx`) |
| `0006` | `HONE_DEMO_MODEL` names the Pi model the demo project and its prepared chats use, so the picker can hide Pi's `default` entry (`apps/server/src/hone/HoneDemo.ts`) |

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
