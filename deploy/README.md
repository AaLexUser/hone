# Booth stack with Docker Compose

This folder runs the booth demo as three containers behind one shared login.

- `caddy` is the only service with published ports. It asks every visitor for the booth login and password, then sends `/hone/` to Hone and everything else to t3code.
- `t3code` is the web interface for the Pi agent. It is built from the pinned t3code commit with every patch in `clients/t3code/patches`, applied in name order. The image also holds Pi, the Hone extension and the office tools the agent runs, which are `pdftotext`, python-docx and LibreOffice.
- `hone` is the Hone service with its dashboard, started in demo mode.

t3code and Hone talk to each other on an internal network. Hone has no internet access. t3code reaches the internet only to call the model.

## Set up

1. Copy `.env.example` to `.env` in this folder and fill in every value. The comments in the file show how to make the password hash and the secrets.
2. Build and start the stack from this folder.

   ```sh
   docker compose up --build -d
   ```

   The first build takes several minutes, because it installs t3code and LibreOffice.
3. Open the site address in a browser and enter the booth login. The demo chats are listed under Offer letters. The Hone button in the sidebar opens the Hone dashboard inside t3code.

With `SITE_ADDRESS=:80` the stack serves plain HTTP on `HTTP_PORT`. With a domain name, Caddy gets a certificate on its own and serves HTTPS. The domain must point at this machine, and ports 80 and 443 must be open.

## How the login works

Caddy checks the booth login on every request, so nothing reaches t3code or Hone without it.

- Caddy adds the header `X-T3code-Proxy-Auth` with `T3CODE_PROXY_AUTH_SECRET` to every request it sends to t3code. Patch 0004 makes t3code sign in every request that carries this secret, so a new browser needs only the booth login and never sees a pairing page. t3code answers 401 to requests without the secret.
- Caddy adds Hone's write token to every request it sends to Hone. The token never reaches the browser, and anyone with the booth login can use the dashboard buttons.
- Hone's web UI is built with the base path `/hone/`, so t3code shows it in a frame from the same address and the same login. `/hone` without the slash is t3code's own Hone page, and `/hone/` is the dashboard itself.

## Pi is the only agent

On its first start, t3code writes its settings from `t3code/settings.json` and `t3code/settings.py`. Pi is the only enabled provider, and Codex, Claude and the other built-in providers are off. The model picker shows exactly one entry, the model in `t3code/pi-settings.json`. The entrypoint passes it to t3code as `HONE_DEMO_MODEL`, so the prepared chats use it too. Every other model in Pi's catalog is hidden. Later changes made in Settings are kept in `t3code-state`.

## Data

Named volumes keep the state across restarts.

| Volume | Holds |
|---|---|
| `hone-data` | Hone's sessions, feedback, runs and AGENTS.md history |
| `t3code-state` | t3code's projects, chats and settings |
| `pi-sessions` | Pi's session files |
| `demo-project` | The Offer letters project folder |
| `caddy-data`, `caddy-config` | Caddy's certificates and settings |

t3code resets the demo on every start and on the Reset demo button, so a restart of the `t3code` service brings back the prepared state. `docker compose down -v` deletes every volume and starts from nothing.

## Start optimization is not wired

Play prepared run works. Start optimization does not work in this stack. A real optimization runs each MAJICS stage as a Harbor job, and Harbor starts a Docker container for every stage (`packages/hone/majics/executor.py`). The Hone container has no Docker. Giving it the host's Docker socket would hand it control of the host. Harbor would also mount task folders by their path inside the Hone container, which does not exist on the host. The sandbox then calls back to Hone through `host.docker.internal`, which this stack does not expose. Run a real optimization with Hone outside Docker, as the main README describes.

## Change t3code or Pi

The t3code commit, its repository and the Pi version are build arguments in `t3code.Dockerfile`. After adding a patch to `clients/t3code/patches`, rebuild with `docker compose build t3code`. Pi uses the provider and model in `t3code/pi-settings.json`. A changed model reaches the model picker only on a fresh `t3code-state` volume, because t3code writes its settings once.
