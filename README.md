
# iMessage Text Campaign (Mac)

This kit lets you run **personalized text campaigns from your personal phone number** via the Mac Messages app, then **auto‑halt follow‑ups as soon as someone replies**.

## What’s included
- `send_texts.py` — main orchestrator (reads `contacts.csv`, sends texts, schedules follow‑ups, checks for replies)
- `send_message.applescript` — sends a single message via Messages.app
- `contacts.csv` — example sheet with 2 contacts + templated messages
- `state.json` — created on first run; tracks who’s been messaged, next due follow‑ups, and who replied

## One‑time setup (10–15 mins)
1. **Link iPhone & Mac for SMS**  
   On iPhone: Settings → Messages → Text Message Forwarding → enable your Mac.  
   Ensure you can send/receive SMS/iMessage to your targets from your Mac.
2. **Full Disk Access for Terminal/Python** (needed to read `~/Library/Messages/chat.db`)  
   System Settings → Privacy & Security → Full Disk Access → add your terminal (and/or Python if separate).  
   Restart Terminal after toggling.
3. **Allow Automation**  
   On first send, macOS will prompt that Terminal wants to control Messages. Click **OK**.

## Customize your contacts
Edit `contacts.csv` (or export from Google Sheets as CSV) with columns:
```
phone, first_name, company, msg1, fup1_days, fup1_msg, fup2_days, fup2_msg
```
- Use E.164 phone format (e.g., `+19195550123`) for best reliability.
- Templating uses Python-style placeholders: `{first_name}`, `{company}`, etc.

## Run it
Open Terminal in this folder and test:
```bash
python3 send_texts.py --dry-run
```
If the preview looks good, actually send:
```bash
python3 send_texts.py
```
Send to just one number while testing:
```bash
python3 send_texts.py --only "+19195550111"
```

Control pacing (default ~8 texts/min):
```bash
python3 send_texts.py --rate-per-minute 6
```

## How follow‑ups stop on reply
- On the first send to a contact, the script records a `started_at` timestamp.
- Before any follow‑up, it checks `~/Library/Messages/chat.db` for **any inbound message** from that number **after `started_at`**.
- If found, it marks the contact as `halted: true` and **sends no more follow‑ups**.

> If you edit `state.json`, keep valid JSON. You can reset a contact by deleting their entry (keyed by last 10 digits).

## Scheduling (optional)
You can re‑run the script daily to send any due follow‑ups. On macOS, use **launchd** (preferred) or `cron`.

Example `~/Library/LaunchAgents/com.isaac.smscampaign.plist` that runs every day at 9:30am:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key><string>com.isaac.smscampaign</string>
    <key>ProgramArguments</key>
    <array>
      <string>/usr/bin/python3</string>
      <string>/mnt/data/sms_campaign/send_texts.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
      <key>Hour</key><integer>9</integer>
      <key>Minute</key><integer>30</integer>
    </dict>
    <key>StandardOutPath</key><string>/mnt/data/sms_campaign/launchd.log</string>
    <key>StandardErrorPath</key><string>/mnt/data/sms_campaign/launchd.err</string>
    <key>RunAtLoad</key><true/>
  </dict>
</plist>
```
Load/unload:
```bash
launchctl unload ~/Library/LaunchAgents/com.isaac.smscampaign.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.isaac.smscampaign.plist
```

## Notes & limits
- Apple may throttle mass sends; keep rates modest and content relevant. Human cadence wins.
- For green‑bubble SMS (non‑iMessage), ensure Text Message Forwarding is on.
- Some recipients appear in `handle.id` as `tel:+1...` or just `+1...`. This script matches the **last 10 digits** to be robust.
- If you run into `SQLite` permission errors, re‑check **Full Disk Access**.
- This kit is for informational/legit outreach. Follow TCPA and local laws; include a clear way to opt out if needed.
