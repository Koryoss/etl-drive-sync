# etl-drive-sync

eTL(Canvas LMS)에 새로 올라온 강의자료를 내 구글 드라이브 폴더로 자동 복사합니다.
복사된 폴더를 ChatGPT 등 AI 도구에 연결해 요약·문제 풀이에 활용할 수 있습니다.

```
eTL (Canvas API) ──토큰──▶ GitHub Actions (이 레포) ──▶ 구글 드라이브 ──▶ ChatGPT 등
```

토큰은 GitHub Secrets에만 들어가고, AI 도구에는 전달되지 않습니다.

## ⚠️ 먼저 읽어주세요

- **eTL 토큰은 사실상 비밀번호입니다.** 코드, 이슈, 로그, 채팅창에 절대 붙여넣지 마세요.
- **본인 fork의 Secrets에만** 등록하세요. 이 레포의 원본에는 누구의 토큰도 없습니다.
- **fork는 private 권장.** public이면 Actions 로그와 `state/synced.json`(파일 ID 목록)이 공개됩니다.
- **학교 정책 확인:** 학교에 따라 개인 액세스 토큰 발급이나 외부 연동이 제한될 수 있습니다.
- **저작권:** 강의자료는 개인 학습용으로만 사용하세요. 공유 폴더에 올려 2차 배포하지 마세요.
- **서버 부하:** `config.yml`의 기본값(요청 간 1초, 하루 1회 등)을 유지하세요. 학교 서버에 부담을 주지 않는 것이 이 도구의 전제입니다.

## 설정 방법

### 1. fork 후 private으로 설정

### 2. eTL 토큰 발급
eTL 로그인 → 계정 → 설정 → **새 액세스 토큰**. 목적에 `etl-drive-sync`, **만료일은 학기 말 정도로 짧게** 지정하세요. 다른 서비스(GPAI 등)와 토큰을 공유하지 말고 따로 발급하세요.

### 3. 구글 드라이브 인증 (OAuth 리프레시 토큰)
1. Google Cloud Console에서 프로젝트 생성 → **Drive API 사용 설정**
2. OAuth 동의 화면 설정(테스트 모드, 본인 계정을 테스트 사용자로 추가)
3. OAuth 클라이언트 ID(데스크톱 앱) 생성 → `CLIENT_ID`, `CLIENT_SECRET` 확보
4. 로컬에서 `python get_refresh_token.py`를 실행해 **리프레시 토큰** 발급 (기본 범위 `drive.file`)
   ```bash
   pip install -r requirements.txt
   export GOOGLE_CLIENT_ID=...  GOOGLE_CLIENT_SECRET=...
   python get_refresh_token.py          # 직접 만든 폴더를 쓰려면: --scope drive
   ```
   출력된 토큰은 화면에만 표시되고 파일로 저장되지 않습니다. 바로 GitHub Secrets에 등록하세요.
5. 드라이브에 저장용 폴더를 만들고 주소창 끝의 **폴더 ID** 확인

> 학교 구글 워크스페이스 계정은 관리자 정책으로 외부 앱 연동이 막혀 있는 경우가 많습니다. 안 되면 개인 구글 계정을 쓰세요.
> `drive.file` 범위는 이 앱이 만든 파일/폴더만 접근하므로, 폴더는 앱이 만든 것이어야 합니다. 루트 폴더를 직접 만들었다면 범위를 `drive`로 바꿔야 할 수 있습니다(권한이 넓어지니 주의).

### 4. GitHub Secrets 등록
Settings → Secrets and variables → Actions:

| 이름 | 값 |
|---|---|
| `CANVAS_BASE_URL` | 학교 eTL 주소 (예: `https://etl.example.ac.kr`) |
| `CANVAS_TOKEN` | eTL 액세스 토큰 |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REFRESH_TOKEN` | 위 3단계 값 |
| `DRIVE_ROOT_FOLDER_ID` | 저장 폴더 ID |

### 5. 실행
Actions 탭 → `etl-drive-sync` → **Run workflow**로 첫 실행. 이후 매일 07:00(KST)에 자동 실행됩니다.
첫 실행은 최근 4주 안에 수정된 파일만 받습니다(`first_run_lookback_weeks`).

## 부하 방지 설계

- 활성 과목만, 파일 목록만 조회 (성적·제출물·메시지는 호출하지 않음)
- 증분 동기화: 최신순 정렬 후 이미 받은 항목에서 중단
- `per_page=100`, 과목별 순차 처리, 요청 간 1초 대기
- `X-Rate-Limit-Remaining`이 낮아지면 중단
- 1회 실행당 API 호출 300회 / 파일 40개 상한
- 실패 시 지수 백오프(최대 3회), 인증 오류는 재시도하지 않음

## 로컬 테스트

```bash
pip install -r requirements.txt
cp .env.example .env   # 값 채우기 (커밋 금지)
set -a && source .env && set +a
python sync.py
```

## 토큰 폐기
사용을 멈추면 eTL 설정에서 토큰을 삭제하세요. 삭제 즉시 접근이 끊깁니다.

## 면책
이 프로젝트는 학교나 Instructure와 무관한 개인 학습 도구입니다. 사용에 따른 책임은 사용자에게 있습니다.
