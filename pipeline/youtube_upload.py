"""Upload a video to the authorised YouTube channel.

Credentials come from environment variables (GitHub Actions secrets):
YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN.
"""
import argparse
import os
import sys

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def youtube_client():
    missing = [k for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN") if not os.environ.get(k)]
    if missing:
        sys.exit(f"Secrets manquants : {', '.join(missing)}")
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"].strip(),
        client_id=os.environ["YT_CLIENT_ID"].strip(),
        client_secret=os.environ["YT_CLIENT_SECRET"].strip(),
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def channel_title(yt):
    items = yt.channels().list(part="snippet", mine=True).execute().get("items", [])
    return items[0]["snippet"]["title"] if items else None


def upload(yt, path, title, description, tags, privacy, publish_at=None, thumbnail=None):
    status = {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}
    if publish_at:
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "27",  # Education
            "defaultLanguage": "fr",
            "defaultAudioLanguage": "fr",
        },
        "status": status,
    }
    media = MediaFileUpload(path, chunksize=8 * 1024 * 1024, resumable=True)
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        progress, response = request.next_chunk()
        if progress:
            print(f"Envoi : {int(progress.progress() * 100)} %")
    video_id = response["id"]
    if thumbnail:
        try:
            yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(thumbnail)).execute()
            print("Miniature ajoutée")
        except HttpError as e:
            print(f"Miniature refusée ({e.status_code}) : la chaîne doit être validée par téléphone.")
    return video_id, response["status"]["privacyStatus"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("video")
    p.add_argument("--title", required=True)
    p.add_argument("--description", default="")
    p.add_argument("--description-file")
    p.add_argument("--tags", default="")
    p.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    p.add_argument("--publish-at", help="Date ISO 8601 UTC, ex. 2026-11-20T17:00:00Z")
    p.add_argument("--thumbnail")
    a = p.parse_args()

    if a.description_file:
        a.description = open(a.description_file, encoding="utf-8").read()
    yt = youtube_client()
    try:
        print(f"Chaîne autorisée : {channel_title(yt)}")
        vid, privacy = upload(
            yt, a.video, a.title, a.description,
            [t.strip() for t in a.tags.split(",") if t.strip()],
            a.privacy, a.publish_at, a.thumbnail,
        )
    except HttpError as e:
        sys.exit(f"Erreur YouTube {e.status_code} : {e.reason}")
    print(f"Vidéo envoyée : https://youtu.be/{vid} (statut : {privacy})")


if __name__ == "__main__":
    main()
