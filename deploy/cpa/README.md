# CLIProxyAPI on the booth domain

The optional `cpa` Compose profile runs the official `eceasy/cli-proxy-api:latest`
image behind Caddy. Its API base is `/cpa/v1` and its management panel is
`/cpa/management.html`. Caddy redirects `/cpa` to `/cpa/`.

CPA uses its own client and management keys. The booth's Basic login remains on
Hone and t3code. The official panel detects the origin without `/cpa`, so Caddy
also forwards `/v8/management/*`, the legacy `/v0/management/*`, plugin
resources under `/v0/resource/plugins/*`, and the dashboard's `/v1/models`
request to CPA. These routes use CPA's own authentication; a missing key must
not trigger the booth's browser login dialog. A custom panel server address
ending in `/cpa` works too.

## Set up

1. Create `config/config.yaml` from `config.example.yaml`, replacing both keys
   with different randomly generated values. This directory is ignored by Git.
2. Add `cpa` to `COMPOSE_PROFILES` in `deploy/.env`.
3. From `deploy`, run `docker compose up -d --no-deps cpa` and reload Caddy with
   `docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile`.
4. Open the panel and enter the management key. Add upstream provider accounts
   or API keys there; none are configured by default.

The configuration directory is writable so panel edits and the startup hash of
the management key persist. Named volumes retain OAuth credentials, the panel,
and request error logs across container updates. CPA has no published host ports.

## Automatic updates

`update.sh` pulls `latest` and recreates only CPA when the image changes. On the
server, the user's crontab runs it hourly through `flock`; output goes to
`/var/essdata/a_lapin/hone/cpa-update.log`. Run `sh deploy/cpa/update.sh` from the
repository root for an immediate update.

The [official panel updater](https://github.com/router-for-me/CLIProxyAPI/blob/main/internal/managementasset/updater.go)
checks GitHub on startup and every three hours. `disable-auto-update-panel`
stays false and the panel repository points at the official release feed.
