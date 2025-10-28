#!/usr/bin/env python3
"""
send_texts.py — Personalized text campaign via Messages.app (macOS).
- Reads contacts.csv
- Sends initial + scheduled follow-ups
- Stops follow-ups if ANY reply is detected in Messages since campaign start
Requirements:
- macOS with Messages linked to your iPhone (Settings > Messages > Text Message Forwarding)
- Grant Full Disk Access to your terminal/Python (System Settings > Privacy & Security > Full Disk Access)
Usage examples:
  python3 send_texts.py --dry-run
  python3 send_texts.py --only "+15551234567"
  python3 send_texts.py --rate-per-minute 8
"""
import argparse, csv, json, os, re, shlex, subprocess, time, sqlite3, datetime as dt
from pathlib import Path

BASE = Path(__file__).resolve().parent
CSV_PATH = BASE / "contacts.csv"
STATE_PATH = BASE / "state.json"
APPLE_SCRIPT = BASE / "send_message.applescript"
CHAT_DB = Path.home() / "Library/Messages/chat.db"

def e164_or_digits(s: str) -> str:
    if not s:
        return ""
    # normalize to digits + leading plus if present
    s = s.strip()
    plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    return ("+" if plus else "") + digits

def last10(s: str) -> str:
    return re.sub(r"\D", "", s)[-10:] if s else ""

def load_contacts():
    rows = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            # normalize phone
            row["phone"] = e164_or_digits(row.get("phone",""))
            row["phone_last10"] = last10(row["phone"])
            rows.append(row)
    return rows

def load_state():
    if STATE_PATH.exists():
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_state(state):
    tmp = STATE_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp, STATE_PATH)

def format_message(template: str, vars: dict) -> str:
    # Basic {first_name} style formatting; missing fields become empty string
    class SafeDict(dict):
        def __missing__(self, key): return ""
    return template.format_map(SafeDict(vars))

def run_osascript(phone: str, text: str, dry_run=False):
    cmd = ["osascript", str(APPLE_SCRIPT), phone, text]
    if dry_run:
        print("[DRY RUN] would send to", phone, ":", text)
        return True
    try:
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print("osascript error:", e)
        return False

def connect_chatdb():
    # Open read-only, immutable (safer while Messages is open).
    # Requires Full Disk Access.
    uri = f"file:{CHAT_DB}?immutable=1"
    return sqlite3.connect(uri, uri=True)

def apple_to_unix(ts):
    # Apple absolute time in seconds or nanoseconds since 2001-01-01 00:00:00 UTC
    # Convert to Unix epoch
    if ts is None:
        return None
    try:
        ts = int(ts)
    except:
        return None
    # Heuristic: if it's huge, it is nanoseconds
    if ts > 1_000_000_000_000: # nanoseconds-ish
        sec = ts / 1_000_000_000
    else:
        sec = ts
    return sec + 978307200  # seconds between 1970 and 2001 epochs

def has_reply_since(phone_last10: str, since_unix: float) -> bool:
    if not CHAT_DB.exists():
        print("Warning: chat.db not found at", CHAT_DB)
        return False
    con = connect_chatdb()
    cur = con.cursor()
    # Look for any incoming (is_from_me = 0) messages for handles whose id ends with the last 10 digits
    q = """
    SELECT message.date
    FROM message
    JOIN handle ON handle.ROWID = message.handle_id
    WHERE message.is_from_me = 0
      AND REPLACE(REPLACE(REPLACE(handle.id,'-',''),' ',''),'tel:','') LIKE ?
    ORDER BY message.date DESC
    LIMIT 1
    """
    like_pat = f"%{phone_last10}"
    try:
        cur.execute(q, (like_pat,))
        row = cur.fetchone()
    except sqlite3.OperationalError as e:
        print("SQLite error (do you have Full Disk Access?):", e)
        return False
    finally:
        con.close()
    if not row:
        return False
    last_incoming_unix = apple_to_unix(row[0])
    return (last_incoming_unix or 0) >= since_unix

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Don't actually send, just print actions")
    ap.add_argument("--only", help="Send only to this phone (E.164 or digits)")
    ap.add_argument("--rate-per-minute", type=int, default=8, help="Throttle rate")
    args = ap.parse_args()

    contacts = load_contacts()
    state = load_state()

    # Filter if --only is specified
    only_last10 = last10(args.only) if args.only else None
    now_unix = time.time()

    sent_count = 0
    interval = 60 / max(args.rate_per_minute, 1)

    for c in contacts:
        if not c["phone"]:
            print("Skipping row with missing phone:", c)
            continue
        if only_last10 and last10(c["phone"]) != only_last10:
            continue

        key = last10(c["phone"])
        st = state.get(key, {
            "started_at": None,
            "stage": 0,           # 0=not sent, 1=sent initial, 2=sent fup1, 3=sent fup2
            "next_due": None,
            "halted": False
        })

        # Stop logic: if halted, skip
        if st.get("halted"):
            continue

        # If campaign started, stop if any reply since started_at
        if st.get("started_at"):
            if has_reply_since(key, st["started_at"]):
                st["halted"] = True
                state[key] = st
                print(f"[STOPPED] {c['phone']} replied; halting follow-ups.")
                continue

        # Determine what to send
        # Columns expected: phone, first_name, company, msg1, fup1_days, fup1_msg, fup2_days, fup2_msg
        vars = dict(c)
        msg1 = c.get("msg1","").strip()
        fup1_days = int(c.get("fup1_days", "0") or 0)
        fup1_msg = c.get("fup1_msg","").strip()
        fup2_days = int(c.get("fup2_days", "0") or 0)
        fup2_msg = c.get("fup2_msg","").strip()

        to_send = None

        if st["stage"] == 0 and msg1:
            to_send = format_message(msg1, vars)
            # after sending, set next_due
            next_due = now_unix + (fup1_days * 86400 if fup1_msg else 0)
            st.update({
                "started_at": now_unix,
                "stage": 1,
                "next_due": next_due
            })

        elif st["stage"] == 1 and fup1_msg and (st["next_due"] or 0) <= now_unix:
            to_send = format_message(fup1_msg, vars)
            next_due = now_unix + (fup2_days * 86400 if fup2_msg else 0)
            st.update({
                "stage": 2,
                "next_due": next_due
            })

        elif st["stage"] == 2 and fup2_msg and (st["next_due"] or 0) <= now_unix:
            to_send = format_message(fup2_msg, vars)
            st.update({
                "stage": 3,
                "next_due": None
            })

        # stage >=3 => nothing else to send
        if not to_send:
            state[key] = st
            continue

        ok = run_osascript(c["phone"], to_send, dry_run=args.dry_run)
        if ok:
            sent_count += 1
            state[key] = st
            save_state(state)
            if not args.dry_run and sent_count > 0:
                time.sleep(interval)

    save_state(state)
    print(f"Done. Sent {sent_count} messages.")
    
if __name__ == "__main__":
    main()