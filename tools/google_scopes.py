"""
Canonical Google OAuth scope set, shared by ALL Google tools.

Every Google tool (calendar, drive, contacts, gmail) shares one token file per
account. If different tools request different scopes, whichever refreshes the
token last overwrites its `scopes` field and narrows it — breaking the others.
So they must ALL load the token with this same superset.
"""
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/contacts",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]
