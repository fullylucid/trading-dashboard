# Chart Smart Alerts — install on the box

Chart-condition alerts: each saved alert is an indicator spec + a condition
(`price >`, `price <`, `crosses ↑`, `crosses ↓`, or any spec plot) evaluated against
the symbol's latest bars. When it fires on a **new** bar, a card is pushed to the
signals Telegram (@Siiigggbot). Created/managed from the Charts tab's **"Alerts"**
panel (and `POST /api/alerts`).

It runs as a host systemd timer that triggers the in-app evaluator over the loopback
API every 5 minutes — evaluation happens **inside the `tdbox-backend` container** (where
Redis + the cached OHLC live). Same operating model as `fintube-scout` / `crack-a-dawn`.
The evaluator dedups per bar, so off-hours runs are cheap no-ops.

## Prereq
Backend must be running the merged alerts code (it already serves `/api/alerts/*`):

```bash
cd ~/trading-dashboard && git pull
docker compose -f docker-compose.box.yml up -d --build backend
```

Telegram delivery reuses the existing `SIGNAL_BOT_TOKEN` / `SIGNAL_BOT_CHAT_ID` env
(already set for the signals bot) — no new credentials.

## Install the timer (host) — requires sudo
```bash
sudo cp ~/trading-dashboard/deployment/chart-alerts.service /etc/systemd/system/
sudo cp ~/trading-dashboard/deployment/chart-alerts.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now chart-alerts.timer
```

## Operate
```bash
systemctl list-timers chart-alerts.timer       # next fire (every 5 min)
sudo systemctl start chart-alerts.service       # evaluate once, now
journalctl -u chart-alerts.service -n 50        # last run
```

## Trigger / test by hand (no timer needed)
```bash
# evaluate all active alerts now; delivers any that fired. Returns {checked, fired, total}
curl -sS -X POST http://127.0.0.1:8000/api/alerts/check

# list / create / delete alerts
curl -sS http://127.0.0.1:8000/api/alerts
curl -sS -X POST http://127.0.0.1:8000/api/alerts -H 'Content-Type: application/json' -d '{
  "symbol":"AAPL",
  "spec":{"name":"Price","steps":[{"id":"c","op":"series","ref":"close"}],"plots":[{"step":"c","label":"Close"}]},
  "plot_step":"c","op":"gt","value":250
}'
curl -sS -X DELETE http://127.0.0.1:8000/api/alerts/<alert_id>
```

Alerts are stored in Redis (`chart:alerts`) and persist across restarts. Evaluation runs
on cached daily bars; an alert fires at most once per new daily bar.
