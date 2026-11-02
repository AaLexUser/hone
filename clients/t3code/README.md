# Hone in t3code

[t3code](https://github.com/pingdotgg/t3code) is a web interface for coding agents. With these
patches, a Pi agent driven from t3code shows its Hone connection and sends feedback to Hone:

- A chip in the chat header shows that the agent is connected to Hone, which `AGENTS.md`
  version it runs, and how full the next optimization batch is. It shows `optimizing…` during
  a run and raises a toast when a session reaches Hone or `AGENTS.md` changes. Clicking it opens
  the Hone dashboard.
- Each Pi reply gets thumbs up and thumbs down buttons. Either one opens a comment box, and the
  rating and comment are appended to the session's Hone trace.

Pi itself needs no patch. t3code runs `pi --mode rpc` per thread, so Pi loads the Hone extension
(`clients/pi-extensions/hone.ts`) like any user extension: it syncs `AGENTS.md` into the project
folder at session start and publishes the session trace after each reply.

## Patches

`patches/` applies to t3code commit `ac8dce0cc3abd8a337f2d806b5082a6834b9b81a`.

| Patch | Adds |
|---|---|
| `0001` | `hone.status` and `hone.feedback` RPCs (`packages/contracts/src/hone.ts`, `apps/server/src/hone/Hone.ts`) |
| `0002` | The header chip and the reply rating control (`apps/web/src/components/chat/HoneControls.tsx`) |

The t3code server calls Hone, so the browser never holds the Hone token and Hone needs no CORS.
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
