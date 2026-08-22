#!/usr/bin/env python3
"""
Send the weekly L&D digest via Gmail SMTP using an App Password.

Auth: env GMAIL_APP_PASSWORD (a 16-char Gmail App Password). Sender defaults
to avi.j.levi@gmail.com (override with GMAIL_USER). DIGEST_TO is a comma
separated recipient list, set as a repo variable so the audience changes
without a commit; it defaults to Avi alone if unset.

Dedup: writes reports/<week>/.email_sent after a successful send; the caller
(workflow) commits and pushes it. That marker is the only thing preventing a
duplicate send when the hourly catch-net fires, so the workflow verifies the
commit landed.

Usage: python3 scripts/send_digest_smtp.py [week]
Exit 0 = sent or already-sent; 1 = real failure; 2 = no credential.
"""
import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import send_digest as sd  # noqa: E402

GMAIL_USER = os.environ.get("GMAIL_USER", "avi.j.levi@gmail.com")
# Comma separated, so a recipient can be added or removed by editing the
# DIGEST_TO repo variable rather than shipping a code change.
# `or` rather than a get() default: an unset repo variable reaches the job as
# an empty string, which a default would not catch, and an empty list would
# hard-fail the send.
RECIPIENTS = [a.strip() for a in
              (os.environ.get("DIGEST_TO") or "avi.j.levi@gmail.com").split(",")
              if a.strip()]
APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")


def send(week):
    top = sd.read_top_articles(week)
    html = sd.build_html(week, top)

    msg = MIMEMultipart("alternative")
    msg["To"] = ", ".join(RECIPIENTS)
    msg["From"] = GMAIL_USER
    msg["Subject"] = sd.build_subject(week)
    msg.attach(MIMEText(sd.PLAIN_BODY, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(GMAIL_USER, APP_PASSWORD)
        s.sendmail(GMAIL_USER, RECIPIENTS, msg.as_string())
    print(f"Email sent via SMTP to {', '.join(RECIPIENTS)} | Week: {week} | {len(top)} TL;DR items")


def main():
    week = sys.argv[1] if len(sys.argv) > 1 else sd.latest_week()
    sent_marker = os.path.join(sd.REPORTS_DIR, week, ".email_sent")
    if os.path.exists(sent_marker):
        print(f"Email already sent for {week}, skipping.")
        return 0
    if not RECIPIENTS:
        print("DIGEST_TO resolved to no recipients.", file=sys.stderr)
        return 2
    if not APP_PASSWORD:
        print("GMAIL_APP_PASSWORD not set — cannot send.", file=sys.stderr)
        return 2
    try:
        send(week)
    except Exception as e:
        print(f"SMTP send failed: {e}", file=sys.stderr)
        return 1
    open(sent_marker, "w").write(week)
    return 0


if __name__ == "__main__":
    sys.exit(main())
