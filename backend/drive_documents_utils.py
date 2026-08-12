"""
drive_documents_utils.py
--------------------------
Scans the Google Drive folder tree that holds the written הלכה handouts
(PDF and/or DOCX) for השיעור השבועי videos - organized as
root -> year folder -> month folder -> files - and builds a
video_id -> document(s) mapping by parsing the 11-character YouTube video
ID embedded at the end of each file's name.

Filename convention (fixed by how files are uploaded to Drive, not by
us), e.g.:
  "הרב אהרון בוטבול - - הלכות בין המצרים,ענייני דיומא - ד אב תשעט - - 7qN9gMP9QcQ.pdf"
                                                              ^^^^^^^^^^^ YouTube video id

Auth: a Google OAuth *user* token (not a service account) - the Drive
folder is a personal folder, so the token must belong to a Google account
that already has at least Viewer access to it. Set GOOGLE_DRIVE_TOKEN_JSON
to the full JSON contents of an `authorized_user`-style token file (the
same shape python's google-auth library writes out: token, refresh_token,
client_id, client_secret, token_uri, scopes). The access token itself is
short-lived, but as long as refresh_token/client_id/client_secret are
present this refreshes itself automatically - no manual re-auth needed
unless the refresh_token itself is revoked or (common with an OAuth
consent screen still in "Testing" mode on Google Cloud Console) expires
after 7 days of the app being unverified. If Drive calls suddenly start
failing with an invalid_grant error, that's almost certainly it - the
consent screen needs to move to "Production"/verified, or the token needs
to be re-issued.

NEVER commit GOOGLE_DRIVE_TOKEN_JSON's value to a file tracked by git
(.env is gitignored - that's the only place it belongs locally; on Vercel
it must be set as a Project env var, not baked into any file).
"""

import json
import os
import re

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

ROOT_FOLDER_ID = "1vnRaCt1rr0tpCMU9XQG1poLxrj7yIrNa"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
FOLDER_MIME = "application/vnd.google-apps.folder"

# Matches "...- - <11-char id>.pdf" or ".docx" at the end of a filename.
# The dash(es)/spacing before the id vary a bit across files, so this only
# anchors on "id right before the extension", not the exact separator.
_VIDEO_ID_RE = re.compile(r"([A-Za-z0-9_-]{11})\.(pdf|docx)$", re.IGNORECASE)


def _get_drive_service():
    raw = os.environ.get("GOOGLE_DRIVE_TOKEN_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_DRIVE_TOKEN_JSON not configured")
    creds = Credentials.from_authorized_user_info(json.loads(raw), scopes=SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("drive", "v3", credentials=creds)


def _list_children(service, folder_id: str) -> list[dict]:
    """All non-trashed direct children of a Drive folder (files + subfolders)."""
    children, page_token = [], None
    while True:
        resp = service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken, files(id, name, mimeType)",
            pageToken=page_token,
            pageSize=1000,
        ).execute()
        children.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return children


def build_video_documents_index() -> dict[str, dict]:
    """
    Walks the full root -> year -> month -> file tree once and returns
    { video_id: {"pdf": {...} | None, "docx": {...} | None} } for every
    file whose name ends in a recognizable "<video_id>.<pdf|docx>".

    Each present doc dict: {"file_id", "name", "year", "month",
    "view_url", "preview_url"}. view_url opens the file in a new Drive
    tab; preview_url is embeddable in an <iframe> (Drive natively renders
    both PDF and DOCX at that URL - no separate handling needed per type).
    """
    service = _get_drive_service()
    index: dict[str, dict] = {}

    for year_folder in _list_children(service, ROOT_FOLDER_ID):
        if year_folder["mimeType"] != FOLDER_MIME:
            continue
        for month_folder in _list_children(service, year_folder["id"]):
            if month_folder["mimeType"] != FOLDER_MIME:
                continue
            for f in _list_children(service, month_folder["id"]):
                m = _VIDEO_ID_RE.search(f["name"])
                if not m:
                    continue
                video_id, ext = m.group(1), m.group(2).lower()
                entry = index.setdefault(video_id, {"pdf": None, "docx": None})
                entry[ext] = {
                    "file_id": f["id"],
                    "name": f["name"],
                    "year": year_folder["name"],
                    "month": month_folder["name"],
                    "view_url": f"https://drive.google.com/file/d/{f['id']}/view",
                    "preview_url": f"https://drive.google.com/file/d/{f['id']}/preview",
                }
    return index
