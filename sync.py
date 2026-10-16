#!/usr/bin/env python3
"""eTL(Canvas) 새 강의자료를 구글 드라이브로 동기화합니다.

- 토큰/인증정보는 코드가 아니라 환경변수(GitHub Secrets)로만 받습니다.
- 학교 서버 부하를 줄이도록 증분 동기화, 요청 간 지연, 호출 상한을 둡니다.
- 성적/제출물/메시지는 호출하지 않습니다. 과목과 파일 목록만 조회합니다.
"""
import io
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yaml
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

USER_AGENT = "etl-drive-sync/0.1 (personal study sync)"
CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", "config.yml"))


class BudgetExceeded(Exception):
    pass


class CanvasClient:
    def __init__(self, base_url, token, cfg):
        self.base = base_url.rstrip("/")
        self.cfg = cfg["api"]
        self.max_calls = cfg["limits"]["max_api_calls_per_run"]
        self.calls = 0
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT})

    def _request(self, url, params=None, stream=False):
        for attempt in range(self.cfg["max_retries"] + 1):
            if self.calls >= self.max_calls:
                raise BudgetExceeded(f"API 호출 상한({self.max_calls}) 도달")
            time.sleep(self.cfg["request_delay_sec"])
            self.calls += 1
            try:
                r = self.s.get(url, params=params, stream=stream, timeout=self.cfg["timeout_sec"])
            except requests.RequestException as e:
                print(f"  네트워크 오류: {e}")
                r = None
            if r is not None:
                remaining = r.headers.get("X-Rate-Limit-Remaining")
                if remaining is not None and float(remaining) < self.cfg["min_rate_limit_remaining"]:
                    raise BudgetExceeded(f"남은 호출 한도 낮음({remaining}), 중단")
                if r.status_code == 200:
                    return r
                if r.status_code in (401, 403) and "rate" not in r.text.lower():
                    r.raise_for_status()  # 인증/권한 문제는 재시도하지 않음
            if attempt < self.cfg["max_retries"]:
                time.sleep(2 ** attempt)
        raise RuntimeError(f"요청 실패: {url}")

    def paginate(self, path, params=None):
        params = dict(params or {})
        params.setdefault("per_page", self.cfg["per_page"])
        url = f"{self.base}/api/v1{path}"
        while url:
            r = self._request(url, params=params)
            yield from r.json()
            url = r.links.get("next", {}).get("url")
            params = None  # next 링크에 이미 쿼리가 포함됨

    def download(self, url):
        return self._request(url, stream=True)


class Drive:
    def __init__(self, root_id):
        creds = Credentials(
            token=None,
            refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
            client_id=os.environ["GOOGLE_CLIENT_ID"],
            client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
            token_uri="https://oauth2.googleapis.com/token",
            scopes=["https://www.googleapis.com/auth/drive.file"],
        )
        self.svc = build("drive", "v3", credentials=creds, cache_discovery=False)
        self.root = root_id
        self._folders = {}

    def folder(self, name):
        if name in self._folders:
            return self._folders[name]
        safe = name.replace("'", "\\'")
        q = (f"name='{safe}' and '{self.root}' in parents and "
             "mimeType='application/vnd.google-apps.folder' and trashed=false")
        res = self.svc.files().list(q=q, fields="files(id)").execute().get("files", [])
        if res:
            fid = res[0]["id"]
        else:
            meta = {"name": name, "parents": [self.root],
                    "mimeType": "application/vnd.google-apps.folder"}
            fid = self.svc.files().create(body=meta, fields="id").execute()["id"]
        self._folders[name] = fid
        return fid

    def upload(self, folder_id, filename, data, mime):
        meta = {"name": filename, "parents": [folder_id]}
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime or "application/octet-stream")
        self.svc.files().create(body=meta, media_body=media, fields="id").execute()


def load_state(path):
    p = Path(path)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def save_state(path, state):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def sanitize(name):
    return "".join("_" if c in '\\/:*?"<>|' else c for c in name).strip() or "untitled"


def main():
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    canvas = CanvasClient(os.environ["CANVAS_BASE_URL"], os.environ["CANVAS_TOKEN"], cfg)
    drive = Drive(os.environ[cfg["drive"]["root_folder_id_env"]])

    state_path = cfg["state"]["file"]
    state = load_state(state_path)
    first_run = not state
    cutoff = None
    weeks = cfg["files"]["first_run_lookback_weeks"]
    if first_run and weeks:
        cutoff = datetime.now(timezone.utc) - timedelta(weeks=weeks)

    allowed = {e.lower() for e in cfg["files"]["allowed_extensions"]}
    max_bytes = cfg["files"]["max_file_size_mb"] * 1024 * 1024
    max_files = cfg["limits"]["max_files_per_run"]
    whitelist = set(cfg["courses"]["whitelist"])
    uploaded = 0

    try:
        params = {"enrollment_state": "active"} if cfg["courses"]["only_active"] else {}
        courses = [c for c in canvas.paginate("/courses", params) if "name" in c]
        if whitelist:
            courses = [c for c in courses if c["id"] in whitelist]
        print(f"대상 과목 {len(courses)}개")

        for course in courses:
            cname = sanitize(course["name"])
            print(f"[{cname}]")
            try:
                files = canvas.paginate(
                    f"/courses/{course['id']}/files", {"sort": "updated_at", "order": "desc"})
                for f in files:
                    key = str(f["id"])
                    updated = f["updated_at"]
                    if state.get(key) == updated:
                        break  # 최신순 정렬이라 이미 본 항목이 나오면 나머지도 이미 처리됨
                    ext = f["display_name"].rsplit(".", 1)[-1].lower() if "." in f["display_name"] else ""
                    if ext not in allowed or f.get("size", 0) > max_bytes:
                        continue
                    if cutoff and datetime.fromisoformat(updated.replace("Z", "+00:00")) < cutoff:
                        break
                    if uploaded >= max_files:
                        raise BudgetExceeded(f"파일 상한({max_files}) 도달")
                    data = canvas.download(f["url"]).content
                    drive.upload(drive.folder(cname), sanitize(f["display_name"]), data,
                                 f.get("content-type"))
                    state[key] = updated
                    uploaded += 1
                    print(f"  + {f['display_name']}")
            except requests.HTTPError as e:
                # 파일 탭을 숨긴 과목은 403/401이 나올 수 있어 건너뜀
                print(f"  건너뜀 (HTTP {e.response.status_code})")
    except BudgetExceeded as e:
        print(f"중단: {e} (다음 실행에서 이어서 진행)")
    finally:
        save_state(state_path, state)

    print(f"완료: 업로드 {uploaded}개, API 호출 {canvas.calls}회")


if __name__ == "__main__":
    sys.exit(main())
