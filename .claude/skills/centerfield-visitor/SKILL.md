---
name: centerfield-visitor
description: 센터필드 빌딩(www.centerfield.co.kr) 방문자 사전등록 자동화. 방문자 1명 또는 명단(설문 export CSV/엑셀/붙여넣은 텍스트)을 받아 centerfield-visitor MCP 도구로 검증(preview)→확인→등록합니다. '센터필드 방문 등록', '방문자 등록', '방문 예약', '참석자 명단 등록', 'visitor registration', 'centerfield reservation' 요청에 사용.
license: MIT
compatibility: Requires the centerfield-visitor MCP server (uvx centerfield-visitor-mcp) configured with CF_COMPANY_NAME and CF_PERSON_IN_CHARGE_MOBILE.
allowed-tools: mcp__centerfield-visitor__validate_configuration mcp__centerfield-visitor__preview_visitors_from_text mcp__centerfield-visitor__preview_visitors_from_file
metadata:
  display_name: 센터필드 방문자 등록
  icon: "🏢"
  mcp_server: centerfield-visitor
  tools: validate_configuration, register_visitor, preview_visitors_from_text, register_visitors_from_text, preview_visitors_from_file, register_visitors_from_file
---

# 센터필드 방문자 등록

MCP 서버 `centerfield-visitor`가 세션·CSRF·입주사·승인 담당자·층 매핑을 모두 처리한다. 이 스킬은 방문자 정보를 정리해 도구에 넘기고, **등록 전에 반드시 사람 확인을 받는다.**

## 도구

| 도구 | 용도 | 부작용 |
|---|---|---|
| `validate_configuration()` | 입주사·담당자·층 목록을 실제 사이트에 조회 | 없음 |
| `preview_visitors_from_text(text, default_visit_date, default_visit_time, default_floor, default_purpose, participation)` | 붙여넣은 CSV/TSV 파싱·검증 결과 | 없음 |
| `preview_visitors_from_file(file_path, ...)` | 파일(.xlsx/.csv/.tsv) 파싱·검증 결과. **로컬(stdio) 서버에서만 존재** | 없음 |
| `register_visitor(..., dry_run=false)` | 1명 등록 | **예약 생성** |
| `register_visitors_from_text(text, ..., dry_run=false)` | 명단 등록 | **예약 생성** |
| `register_visitors_from_file(file_path, ..., dry_run=false)` | 파일 명단 등록. 로컬 서버에서만 | **예약 생성** |

`dry_run=true`는 입력 검증 + 사이트 검증(회사/담당자/층)까지 하고 제출하지 않는다.
원격(Amazon Quick 등) 서버에는 파일 도구가 없으므로 파일 내용을 텍스트로 붙여 넣어 `*_from_text`를 쓴다.
서버가 `CF_EXPOSE_WRITE_TOOLS=false`(preview 전용)로 떠 있으면 `register_*` 도구가 목록에 없다. 이때는 등록을 시도하지 말고, 등록 권한이 있는 서버/담당자에게 넘기도록 안내한다.

## 방문자 1명당 필수 정보

| 필드 | 필수 | 형식 |
|---|---|---|
| `visitor_name` | ✅ | |
| `visitor_company_name` | ✅ | 없으면 "개인" |
| `visitor_mobile` | ✅ | **한국 휴대폰(010…)만 가능.** 하이픈/공백/+82 자동 정리. **없으면 등록 불가 → 사용자에게 요청** (해외 방문자는 아래 참고) |
| `visitor_email` | ✅ | 유효한 이메일 |
| `visit_date` | ✅ | `YYYY-MM-DD`, **Asia/Seoul 기준** 오늘 이후 |
| `visit_time` | ✅ | `HH:MM`, 30분 단위, 08:00~20:00. 오늘 날짜면 Asia/Seoul 기준으로 이미 지난 시각은 거부됨 |
| `visit_purpose` | 선택 | `meeting`(기본) `visit_business` `interview` `tour` `construction` `others` |
| `floor` | 선택 | `12`/`18`, 생략 시 서버 기본 층 |

### 한국 휴대폰이 없는 해외 방문자

센터필드 사전등록은 한국 휴대폰 번호만 받는다. 한국 번호가 없는 방문자는 이 도구로 등록할 수 없다.

- 임의 번호나 주최자 번호로 채우지 않는다.
- 센터필드 쪽은 **수동 절차(manual fallback)** 로 안내한다. 예: 주최자가 현장 안내데스크나 센터필드 관리 채널로 직접 처리.
- 회사 자체 방문객 출입 시스템처럼 휴대폰이 필요 없는 다른 출입 절차는 이 제약과 상관없이 따로 진행할 수 있다.
- 결과 보고에는 해당 방문자를 "센터필드 미등록(수동 처리 필요)"로 표시한다.

## 결과 상태

등록 도구는 방문자마다 상태를 하나 돌려준다. 일괄 요약은 `총 N명 중 A명 성공, B명 실패, C명 결과 불명(UNKNOWN), D명 미제출(NOT_SUBMITTED)` 형식이다.

| 상태 | 뜻 | 다음 행동 |
|---|---|---|
| `SUCCEEDED` | 센터필드가 `success=true`로 응답함. 이것이 성공의 유일한 기준이다. 예약 식별자는 반환되지 않는다 | 완료로 보고 |
| `FAILED` | 명시적 실패. 사이트 거절(`success=false`), 408/429를 제외한 4xx, 입력·설정 오류, 연결 자체가 안 됨. 예약은 생성되지 않았다 | 원인을 고친 뒤 **새 preview → 사용자 승인 → 해당 행만** 재등록 |
| `UNKNOWN` | 제출 뒤 응답을 확인하지 못함. HTTP 408/429/5xx, timeout, 연결 끊김, JSON이 아닌 응답 등. **예약이 이미 생성됐을 수 있다** | **재시도 금지.** 사용자에게 센터필드 앱/사이트에서 예약 여부를 확인하도록 요청 |
| `NOT_SUBMITTED` | 앞선 행이 `UNKNOWN`이라 서버가 일괄 처리를 멈춰서 제출하지 않은 행 | `UNKNOWN` 행을 확인한 뒤 새 preview → 승인을 거쳐 등록 |

## 절차

1. **입력 정리.** 파일 경로(절대경로)나 텍스트를 받는다. 참석 신청 설문 export처럼 **방문일·방문시간 컬럼이 없는 명단**이면 사용자에게 행사 일시·층을 확인하고 `default_visit_date` / `default_visit_time` / `default_floor` 인자로 넘긴다(행마다 채우지 않아도 됨). 헤더는 한/영·설문 헤더(`Full Name`, `연락처(…)`, `소속/회사 (…)`) 모두 자동 인식된다.
2. **필터.** 설문 명단이면 `participation="오프라인"` 인자로 오프라인(현장) 참석자만 남긴다(0.2.1+; 참석 형태 컬럼이 없으면 등록 도구가 중단하므로 그때는 사용자에게 확인). 주최자·내부 직원 행은 여전히 사람이 골라 제외한다. 상대 표현("다음 주 화요일")은 실제 날짜로 바꿔 확인한다.
3. **preview.** `preview_visitors_from_text` / `preview_visitors_from_file`로 파싱 결과를 받아 표로 보여준다. 휴대폰·이메일은 서버가 마스킹해서 돌려주므로 그대로 보여 주면 된다. 등록 도구에는 사용자가 준 원문을 넘긴다. 오류 행(휴대폰 누락 등)은 **사용자에게 값을 요청**하거나 제외 여부를 묻는다. 중복 행은 서버가 자동으로 건너뛴다.
4. **확인.** "N명을 M월 D일 HH:MM, F층으로 등록합니다" 를 사용자가 승인하기 전에는 `register_*`를 호출하지 않는다. 승인 뒤 입력이 바뀌면 새 preview와 재승인을 받는다. 처음 쓰는 환경이면 `validate_configuration` 또는 `dry_run=true`로 먼저 확인한다.
5. **등록.** `register_visitors_from_text`(또는 `_from_file`, 1명이면 `register_visitor`). 반환 요약과 상태별 상세를 그대로 보고한다.
   - `UNKNOWN`이 하나라도 있으면 **어떤 행도 다시 호출하지 않는다.** 사용자에게 센터필드 앱/사이트 확인을 요청한다.
   - `FAILED` 행만 원인을 고쳐 **새 preview → 사용자 승인** 뒤 그 행만 다시 등록한다. 같은 명단 전체를 다시 넘기지 않는다(이미 `SUCCEEDED`인 행이 중복 등록됨).
6. **결과 보고.** 결과 열에는 상태(`SUCCEEDED`/`FAILED`/`UNKNOWN`/`NOT_SUBMITTED`/센터필드 미등록(수동 처리 필요))를 쓴다.

| # | 방문자 | 소속 | 방문일시 | 층 | 결과 |
|---|---|---|---|---|---|

## 실패 유형

- `센터필드 MCP 설정이 비어 있어…` → 서버 `.env`(`CF_COMPANY_NAME`, `CF_PERSON_IN_CHARGE_MOBILE`) 미설정. 사용자에게 설정 안내.
- `PIC verification rejected` / `No company found` → 입주사명·담당자 번호가 센터필드 등록값과 다름. `validate_configuration` 결과를 보여주고 수정 요청.
- `Floor 18 not offered` → 해당 입주사에 층이 없음. 다른 층으로 재확인.
- `행 N: visitor_mobile …` → 휴대폰 누락/형식 오류. 값 요청. 해외 번호뿐이면 위 "해외 방문자" 절차.
- `visit … has already passed (Asia/Seoul)` / `is in the past (Asia/Seoul)` → 서울 시각 기준으로 이미 지난 방문 일시. 사용자에게 일시를 다시 확인.
- `Reservation outcome unknown: …` → `UNKNOWN`. 재시도 금지, 센터필드 앱/사이트 확인.
- 예약 취소 API는 없음. 잘못 등록했으면 센터필드 앱/사이트에서 수동 취소하도록 안내.

## 하지 말 것

- 사용자 확인 없이 `register_*` 호출
- `UNKNOWN`/`NOT_SUBMITTED` 결과 뒤 확인 없이 같은 명단을 다시 등록
- `success=true` 응답이 없는데 성공으로 보고
- 센터필드 사이트를 직접 HTTP/브라우저로 조작 (MCP 도구만 사용)
- 휴대폰이나 이메일이 없는 방문자를 임의 값으로 채워 등록
- 결과 표에 방문자 개인정보를 필요 이상으로 반복 노출
