# FinTube Scout — install on the box

The scout is an automatic YouTube searcher: twice a day it searches YouTube for new
videos matching the topic queries in `fintube:topics`, distills the relevant ones with the
Opus worker pool, and pushes per-video cards (title · why-it-matters · key insights · link)
to the signals Telegram (@Siiigggbot).

It runs as a host systemd timer that triggers an in-app background task over the loopback
API — the discovery + distillation happen **inside the `tdbox-backend` container** (where
yt-dlp, local Redis, and the worker bus live). Same operating model as `crack-a-dawn`.

## Prereq
The backend must already be running the updated code:

```bash
cd ~/trading-dashboard && git pull
docker compose -f docker-compose.box.yml up -d --build backend
```

`yt-dlp` is already in the backend image (FinTube uses it); no new dependency.

## Install the timer (host)
```bash
sudo cp ~/trading-dashboard/deployment/fintube-scout.service /etc/systemd/system/
sudo cp ~/trading-dashboard/deployment/fintube-scout.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fintube-scout.timer
```

## Operate
```bash
systemctl list-timers fintube-scout.timer        # next fire (07:00 & 18:00 PT)
sudo systemctl start fintube-scout.service        # run once, now
journalctl -u fintube-scout.service -n 50         # last run
```

## Trigger / test by hand (no timer needed)
```bash
# real run (distills + pushes to Telegram)
curl -sS -X POST http://127.0.0.1:8000/api/fintube/scout -H 'Content-Type: application/json' -d '{}'

# silent run (no Telegram), tighter relevance bar
curl -sS -X POST http://127.0.0.1:8000/api/fintube/scout -H 'Content-Type: application/json' \
  -d '{"send": false, "min_relevance": 0.75}'
```

## Tune what it hunts for (topic registry)
```bash
curl -sS http://127.0.0.1:8000/api/fintube/topics                       # list
curl -sS -X POST http://127.0.0.1:8000/api/fintube/topics \
  -H 'Content-Type: application/json' \
  -d '{"query":"reinforcement learning trading agent","category":"finance"}'
curl -sS -X DELETE http://127.0.0.1:8000/api/fintube/topics/<topic_id>   # remove
```

Discovered videos also land in the normal FinTube feed (`/api/fintube/feed`) tagged
`source: "scout"` with a `relevance` score, so they show up in the dashboard alongside
tracked-channel videos.

## Preview discovery without distilling (inside the container)
```bash
docker exec tdbox-backend python -m fintube.scout --lookback 14
```
Prints the fresh/unseen candidates the next real run would consider — no worker cost, no
Telegram. Useful for sanity-checking new topic queries.
```
