# Booth stack with Docker Compose

This folder runs the booth demo as four containers behind one shared login.

- `caddy` is the only service with published ports. It asks every visitor for the booth login and password, then sends `/hone/` to Hone and everything else to t3code.
- `t3code` is the web interface for the Pi agent. It is built from the pinned t3code commit with every patch in `clients/t3code/patches`, applied in name order. The image also holds Pi, the Hone extension and the office tools the agent runs, which are `pdftotext`, python-docx and LibreOffice.
- `hone` is the Hone service with its dashboard, started in demo mode. Its settings are in `hone.yaml` in this folder.
- `docker` is a Docker daemon of its own, used only by Hone to run the sandboxes of a real optimization.

t3code and Hone talk to each other on an internal network. Hone has no internet access. t3code reaches the internet only to call the model. The sandboxes reach the internet only to build their image and to call the model.

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

## Guide mode

Guide mode lets visitors try the demo alone. `clients/t3code/README.md` describes it.

- The booth loop ships in the repo through Git LFS as `deploy/booth-video/loop.mp4` (re-encoded to about 73 MB). Run `git lfs install` once on the laptop before cloning or pulling, or the file arrives as a small pointer with its chapter list `loop.chapters.json`. Caddy serves the folder at `/booth-video/` behind the booth login. To ship a new loop, re-encode the rendered `hone-loop.mp4` with `ffmpeg -i hone-loop.mp4 -c:v libx264 -preset slow -crf 28 -tune animation -pix_fmt yuv420p -movflags +faststart -an loop.mp4` and copy `hone-loop.chapters.json` as `loop.chapters.json`.
- Open `/loop` to play the loop on demand, with a seek bar, the playing time and a chapter list. Space pauses, the arrows skip 10 seconds, page up and page down jump between chapters, and F is full screen.
- `HONE_GUIDE_PIN`, `HONE_GUIDE_IDLE_VIDEO_SECONDS` and `HONE_GUIDE_IDLE_RESET_SECONDS` in `.env` set the exit PIN and the two idle times. By default the booth video plays after 30 idle seconds and the demo starts over after 300. `HONE_GUIDE_VIDEO_URL` defaults to `/booth-video/loop.mp4`.
- The video fades in over the app with the hint "Hold any key to try Hone yourself". Taps, mouse moves and key presses do not end it. A press or any key held for 1.5 seconds does, and a ring labelled Keep holding fills in the middle of the screen while the visitor holds. The idle reset keeps counting while the video plays.
- In guide mode the sidebar shows Start over next to the Guide button in place of Reset demo, and every step card has a Start over button. It asks first, then resets the demo like Reset demo and shows the welcome card.
- On every start the entrypoint points Pi's binary path at the turn cache wrapper. It replays recordings from `clients/t3code/turn-cache/`, which the image holds, and from the `turn-cache` volume. `HONE_TURN_CACHE_RECORD=1` records new ones in the volume. `docs/booth-demo.md` says how to record the guided visit.

## Data

Named volumes keep the state across restarts.

| Volume | Holds |
|---|---|
| `hone-data` | Hone's sessions, feedback, runs and AGENTS.md history |
| `docker-lib` | The sandbox images, so the second run skips the image build |
| `docker-certs` | The client certificate Hone uses to reach the `docker` service |
| `t3code-state` | t3code's projects, chats and settings |
| `pi-sessions` | Pi's session files |
| `demo-project` | The Offer letters project folder |
| `turn-cache` | Recorded first turns of demo chats |
| `caddy-data`, `caddy-config` | Caddy's certificates and settings |

t3code resets the demo on every start and on the Reset demo button, so a restart of the `t3code` service brings back the prepared state. `docker compose down -v` deletes every volume and starts from nothing.

## Real optimization

Start optimization runs the real MAJICS pipeline on the current batch. With this roster a run took 10 to 13 minutes in testing. When Hone holds an approved recording of a real run on exactly the same batch, it replays that run in about a minute and a half instead. Approved recordings in `packages/hone/demo/run-cache/` ship with the image, and every finished real run is kept as a candidate in `hone-data`. `docs/booth-demo.md` describes the run cache.

A real run starts each MAJICS stage, review and then propose, as a Harbor job (`packages/hone/majics/executor.py`). Harbor builds a sandbox image, starts the sandbox with Docker Compose next to an egress sidecar, and lets the sandbox reach only the model provider and Hone. The stack wires this up as follows.

- The `docker` service is a separate Docker daemon (`docker:29-dind`). Hone talks to it with the Docker CLI over TLS on port 2376. The daemon writes a client certificate into the `docker-certs` volume, and only Hone mounts that volume.
- The `docker` service mounts `hone-data` at `/data`, the same path as in Hone. Harbor mounts the run folders into the sandboxes by path, so both containers must see them at one path.
- The sandboxes call Hone back at `hone.internal:8080`, Hone's alias on the internal `sandbox` network. The sandboxes' DNS forwards only names with a dot, so the plain name `hone` does not work there.
- The MAJICS seats follow the paper's design. Each panel of three, the reviewers and the proposers, has one model from each of three families, `minimax-m3.1-flash`, `deepseek-v4.1-flash` and `qwen3.8-flash`. Both judges use `glm-5.3`, a fourth family. The full model replaced GLM 5.3 Flash, which kept rules the paper's recurrence rule rejects. It allows fewer requests, but judges make few calls per run. A judge's follow-up question must get its answer within `optimization.follow_up_timeout_s`, 120 seconds here because the judges' questions often send a reviewer back to re-check a trace, so each panel model runs at the highest reasoning level that answers in time, high for MiniMax, medium for Qwen and low for DeepSeek. A reviewer's whole turn must also finish within the driver's five minute turn limit. MiMo V2.6 Flash, LongCat 2.0 and Kimi K2.7 Code ran past the turn limit and Hy3 missed a follow-up, so faster models took their seats. Among each family's OpenCode Go models, these allow the most requests per five hours, so one key lasts through the booth. All of them use `OPENCODE_API_KEY` from `.env`. Change the roster in `hone.yaml` and restart Hone with `docker compose restart hone`.

The first run builds the sandbox image, which adds about two minutes and 2.5 GB in `docker-lib`. Later runs reuse it. Run one real optimization before the booth opens, so the image is ready.

### What this costs in security

The `docker` service runs privileged, because a Docker daemon inside a container needs it. Code that takes over this daemon or escapes a sandbox into it controls the host. These rules keep that risk small.

- No port is published. Caddy is still the only service the outside can reach, and Hone's API stays behind the booth login.
- The daemon listens only on the internal `sandbox` network and on its own outbound network. Only Hone shares a network with it, and the daemon accepts only clients with the certificate from `docker-certs`. t3code, Caddy and the sandboxes cannot use it.
- The sandboxes are ordinary unprivileged containers inside that daemon. Harbor's egress sidecar limits them to the model provider, `hone.internal` and the hosts the image build needs (`packages/hone/majics/runtime.py`).
- A sandbox can reach Hone's API without the booth login, as it does when Hone runs on a laptop. It holds Hone's write token for its callbacks, so it can do what the dashboard buttons do.

The host must allow privileged containers, which stock Docker on Linux does. To turn real optimization off, remove the `docker` service and the `depends_on` line under `hone`. Replays of approved recordings keep working. Start optimization on any other batch then fails within seconds, and the run's Harbor job log says the Docker API cannot be reached.

## Change t3code or Pi

The t3code commit, its repository and the Pi version are build arguments in `t3code.Dockerfile`. After adding a patch to `clients/t3code/patches`, rebuild with `docker compose build t3code`. Pi uses the provider and model in `t3code/pi-settings.json`. A changed model reaches the model picker only on a fresh `t3code-state` volume, because t3code writes its settings once.
