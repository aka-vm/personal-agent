#!/usr/bin/env python3
"""
Google Drive CLI — personal + work accounts
Usage:
  gdrive.py list [personal|work] [folder_id]
  gdrive.py search <personal|work> <query>
  gdrive.py upload <personal|work> <local_path> [folder_id]
  gdrive.py download <personal|work> <file_id> [dest_path]
  gdrive.py read <personal|work> <file_id>     # read a Google Doc/Sheet as text
  gdrive.py share <personal|work> <file_id> <email> [viewer|editor]
  gdrive.py mkdir <personal|work> <name> [parent_folder_id]
  gdrive.py info <personal|work> <file_id>
  gdrive.py recent [personal|work] [limit]
"""
import sys, os, io
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

CONFIG_DIR = os.path.expanduser("~/.config/google")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from google_scopes import SCOPES

def get_service(account):
    token_file = os.path.join(CONFIG_DIR, f"{account}_token.json")
    if not os.path.exists(token_file):
        print(f"No token for {account}. Run: python3 google_auth.py {account}")
        sys.exit(1)
    creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_file, "w") as f:
            f.write(creds.to_json())
    return build("drive", "v3", credentials=creds)

def fmt_size(b):
    if b is None: return "-"
    b = int(b)
    for unit in ["B","KB","MB","GB"]:
        if b < 1024: return f"{b:.0f}{unit}"
        b /= 1024
    return f"{b:.1f}TB"

def fmt_file(f):
    name   = f.get("name", "?")
    ftype  = "📁" if f.get("mimeType") == "application/vnd.google-apps.folder" else "📄"
    size   = fmt_size(f.get("size"))
    mod    = f.get("modifiedTime", "")[:10]
    fid    = f.get("id", "")
    return f"{ftype} {name:<45} {size:>8}  {mod}  {fid}"

def cmd_list(account, folder_id="root"):
    svc = get_service(account)
    q = f"'{folder_id}' in parents and trashed=false"
    results = svc.files().list(
        q=q, pageSize=50, orderBy="folder,name",
        fields="files(id,name,mimeType,size,modifiedTime)"
    ).execute()
    files = results.get("files", [])
    print(f"\n── {account.upper()} Drive {'/ ' + folder_id if folder_id != 'root' else '(root)'} ──")
    if not files:
        print("  Empty.")
    for f in files:
        print(f"  {fmt_file(f)}")

def cmd_search(account, query):
    svc = get_service(account)
    q = f"name contains '{query}' and trashed=false"
    results = svc.files().list(
        q=q, pageSize=20, orderBy="modifiedTime desc",
        fields="files(id,name,mimeType,size,modifiedTime)"
    ).execute()
    files = results.get("files", [])
    print(f"\n── {account.upper()} — Search: '{query}' ──")
    if not files:
        print("  No results.")
    for f in files:
        print(f"  {fmt_file(f)}")

def cmd_recent(account, limit=10):
    svc = get_service(account)
    results = svc.files().list(
        pageSize=int(limit), orderBy="modifiedTime desc",
        q="trashed=false",
        fields="files(id,name,mimeType,size,modifiedTime)"
    ).execute()
    files = results.get("files", [])
    print(f"\n── {account.upper()} — Recent {limit} files ──")
    for f in files:
        print(f"  {fmt_file(f)}")

def cmd_upload(account, local_path, folder_id=None):
    if not os.path.exists(local_path):
        print(f"File not found: {local_path}"); sys.exit(1)
    svc = get_service(account)
    name = os.path.basename(local_path)
    meta = {"name": name}
    if folder_id:
        meta["parents"] = [folder_id]
    media = MediaFileUpload(local_path, resumable=True)
    f = svc.files().create(body=meta, media_body=media, fields="id,name,webViewLink").execute()
    print(f"✓ Uploaded: {f['name']}\n  ID: {f['id']}\n  Link: {f.get('webViewLink','')}")

def cmd_download(account, file_id, dest=None):
    svc = get_service(account)
    meta = svc.files().get(fileId=file_id, fields="name,mimeType").execute()
    name = meta.get("name", file_id)
    dest = dest or os.path.join("/tmp", name)
    request = svc.files().get_media(fileId=file_id)
    with open(dest, "wb") as fh:
        dl = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = dl.next_chunk()
    print(f"✓ Downloaded: {name} → {dest}")

def cmd_share(account, file_id, email, role="reader"):
    svc = get_service(account)
    perm = {"type": "user", "role": role if role == "editor" else "reader", "emailAddress": email}
    svc.permissions().create(fileId=file_id, body=perm, sendNotificationEmail=False).execute()
    print(f"✓ Shared with {email} as {role}")

def cmd_mkdir(account, name, parent=None):
    svc = get_service(account)
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent:
        meta["parents"] = [parent]
    f = svc.files().create(body=meta, fields="id,name").execute()
    print(f"✓ Folder created: {f['name']} (id: {f['id']})")

def cmd_info(account, file_id):
    svc = get_service(account)
    f = svc.files().get(
        fileId=file_id,
        fields="id,name,mimeType,size,modifiedTime,createdTime,webViewLink,owners,shared"
    ).execute()
    print(f"\nName:     {f.get('name')}")
    print(f"ID:       {f.get('id')}")
    print(f"Type:     {f.get('mimeType')}")
    print(f"Size:     {fmt_size(f.get('size'))}")
    print(f"Created:  {f.get('createdTime','')[:10]}")
    print(f"Modified: {f.get('modifiedTime','')[:10]}")
    print(f"Shared:   {f.get('shared', False)}")
    print(f"Link:     {f.get('webViewLink','')}")

def cmd_read(account, file_id):
    """Read a Google Doc/Sheet/Slides as text (via Drive export; uses existing scope)."""
    svc = get_service(account)
    meta = svc.files().get(fileId=file_id, fields="name,mimeType").execute()
    mime = meta["mimeType"]
    export_as = {
        "application/vnd.google-apps.document": "text/plain",
        "application/vnd.google-apps.spreadsheet": "text/csv",
        "application/vnd.google-apps.presentation": "text/plain",
    }.get(mime)
    print(f"\n── {meta['name']} ──")
    if not export_as:
        print(f"(Not a Google Doc/Sheet/Slides — {mime}. Use `download` instead.)")
        return
    data = svc.files().export(fileId=file_id, mimeType=export_as).execute()
    text = data.decode("utf-8", errors="replace") if isinstance(data, (bytes, bytearray)) else str(data)
    print(text[:6000])
    if len(text) > 6000:
        print(f"\n... ({len(text)-6000} more chars — refine or ask for a section)")

USAGE = __doc__

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args: print(USAGE); sys.exit(0)
    cmd = args[0]

    if cmd == "list":
        account   = args[1] if len(args) > 1 else "personal"
        folder_id = args[2] if len(args) > 2 else "root"
        cmd_list(account, folder_id)
    elif cmd == "search":
        cmd_search(args[1], " ".join(args[2:]))
    elif cmd == "recent":
        account = args[1] if len(args) > 1 else "personal"
        limit   = args[2] if len(args) > 2 else 10
        cmd_recent(account, limit)
    elif cmd == "upload":
        folder = args[3] if len(args) > 3 else None
        cmd_upload(args[1], args[2], folder)
    elif cmd == "download":
        dest = args[3] if len(args) > 3 else None
        cmd_download(args[1], args[2], dest)
    elif cmd == "read":
        cmd_read(args[1], args[2])
    elif cmd == "share":
        role = args[4] if len(args) > 4 else "viewer"
        cmd_share(args[1], args[2], args[3], role)
    elif cmd == "mkdir":
        parent = args[3] if len(args) > 3 else None
        cmd_mkdir(args[1], args[2], parent)
    elif cmd == "info":
        cmd_info(args[1], args[2])
    else:
        print(f"Unknown: {cmd}\n{USAGE}")
