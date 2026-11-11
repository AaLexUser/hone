# Turn cache recordings

Recorded first turns of booth demo chats, one JSON file per recording, named by its key.
`apps/server/scripts/hone-pi.ts` from patch 0009 replays them. Each file comes from a real Pi
turn recorded with `HONE_TURN_CACHE_RECORD=1`. `docs/booth-demo.md` says how to record one.
