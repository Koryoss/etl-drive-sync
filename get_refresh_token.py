#!/usr/bin/env python3
"""구글 OAuth 리프레시 토큰을 한 번 발급받는 로컬 전용 스크립트입니다.

사용법:
    pip install -r requirements.txt
    export GOOGLE_CLIENT_ID=...      # 또는 .env를 source
    export GOOGLE_CLIENT_SECRET=...
    python get_refresh_token.py

브라우저가 열리면 구글 로그인 후 권한을 허용하세요.
터미널에 출력된 리프레시 토큰을 GitHub Secrets의 GOOGLE_REFRESH_TOKEN에 등록하면 됩니다.

주의:
- 리프레시 토큰은 비밀번호와 같습니다. 파일로 저장하지 않고 화면에만 출력합니다.
  출력된 값을 커밋, 이슈, 채팅창에 붙여넣지 마세요.
- 기본 범위는 drive.file(이 앱이 만든 파일/폴더만 접근)입니다.
  직접 만든 폴더에 업로드하려면 --scope drive 를 쓰되, 권한이 넓어지는 점에 유의하세요.
"""
import argparse
import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = {
    "drive.file": "https://www.googleapis.com/auth/drive.file",
    "drive": "https://www.googleapis.com/auth/drive",
}


def main():
    ap = argparse.ArgumentParser(description="구글 드라이브 리프레시 토큰 발급")
    ap.add_argument("--scope", choices=SCOPES, default="drive.file")
    ap.add_argument("--port", type=int, default=0, help="로컬 콜백 포트 (0이면 자동)")
    args = ap.parse_args()

    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        sys.exit("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET 환경변수를 먼저 설정하세요.")

    config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(config, scopes=[SCOPES[args.scope]])
    # offline + consent: 리프레시 토큰이 확실히 발급되도록 강제
    creds = flow.run_local_server(
        port=args.port, access_type="offline", prompt="consent",
        authorization_prompt_message="브라우저에서 구글 로그인 및 권한 허용을 진행하세요...",
    )

    if not creds.refresh_token:
        sys.exit("리프레시 토큰이 발급되지 않았습니다. 구글 계정 보안 설정에서 이 앱의 권한을 "
                 "삭제한 뒤 다시 실행하세요.")

    print("\n=== GOOGLE_REFRESH_TOKEN (GitHub Secrets에 등록, 다른 곳에 붙여넣지 마세요) ===")
    print(creds.refresh_token)
    print("=== 끝 ===")
    print(f"범위: {SCOPES[args.scope]}")


if __name__ == "__main__":
    main()
