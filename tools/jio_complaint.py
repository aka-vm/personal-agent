#!/usr/bin/env python3
"""Send a formal complaint email to JIO Fiber customer care.

Usage:
  python3 tools/jio_complaint.py draft "<complaint_text>" "<sender_phone>"
  python3 tools/jio_complaint.py send  "<complaint_text>" "<sender_phone>"

Fixed details (not user-configurable):
  Recipient : jiofibercare@jio.com
  Fiber line : +91-1135698450
  Serial no  : RRIOTFLT0101689
"""
import os
import sys
import subprocess
import textwrap

RECIPIENT     = "jiofibercare@jio.com"
FIBER_PHONE   = "+91-1135698450"
SERIAL        = "RRIOTFLT0101689"
TOOLS_DIR     = os.path.dirname(os.path.abspath(__file__))
EMAIL_SCRIPT  = os.path.join(TOOLS_DIR, "email_send.py")


def _clean_phone(raw: str) -> str:
    """Strip WhatsApp JID suffix and ensure + prefix. e.g. 918899106088@s.whatsapp.net → +918899106088"""
    number = raw.split("@")[0].strip()
    if number and not number.startswith("+"):
        number = "+" + number
    return number


def _build(complaint: str, sender_phone: str) -> tuple[str, str]:
    phone = _clean_phone(sender_phone)
    subject = "JIO Fiber Service Complaint"
    body = textwrap.dedent(f"""\
        Dear JIO Fiber Customer Support Team,

        I am writing to formally raise a complaint regarding my JIO Fiber connection.

        Account Details:
          Fiber Landline Number : {FIBER_PHONE}
          Serial Number         : {SERIAL}

        Complaint:
        {complaint.strip()}

        Contact: {phone}

        Kindly look into this matter at the earliest and provide a resolution.

        Thank you,
        A JIO Fiber Customer
    """)
    return subject, body


def main():
    if len(sys.argv) < 4:
        print("Usage: jio_complaint.py <draft|send> <complaint_text> <sender_phone>")
        sys.exit(1)

    mode, complaint, sender_phone = sys.argv[1], sys.argv[2], sys.argv[3]
    subject, body = _build(complaint, sender_phone)

    if mode == "draft":
        print(f"TO: {RECIPIENT}")
        print(f"SUBJECT: {subject}")
        print()
        print(body)

    elif mode == "send":
        r = subprocess.run(
            [sys.executable, EMAIL_SCRIPT, RECIPIENT, subject, body],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            print(f"Complaint email sent to {RECIPIENT}.")
        else:
            print(f"Send failed: {r.stderr.strip() or r.stdout.strip()}")
            sys.exit(1)

    else:
        print(f"Unknown mode '{mode}'. Use 'draft' or 'send'.")
        sys.exit(1)


if __name__ == "__main__":
    main()
