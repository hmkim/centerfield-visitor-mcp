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

## 방문자 1명당 필수 정보

| 필드 | 필수 | 형식 |
|---|---|---|
| `visitor_name` | ✅ | |
| `visitor_company_name` | ✅ | 없으면 "개인" |
| `visitor_mobile` | ✅ | 한국 휴대폰(010…). 하이픈/공백/+82 자동 정리. **없으면 등록 불가 → 사용자에게 요청** |
| `visitor_email` | ✅ | 유효한 이메일 |
| `visit_date` | ✅ | `YYYY-MM-DD`, 오늘 이후 |
| `visit_time` | ✅ | `HH:MM`, 30분 단위, 08:00~20:00 |
| `visit_purpose` | 선택 | `meeting`(기본) `visit_business` `interview` `tour` `construction` `others` |
| `floor` | 선택 | `12`/`18`, 생략 시 서버 기본 층 |

## 절차

1. **입력 정리.** 파일 경로(절대경로)나 텍스트를 받는다. 참석 신청 설문 export처럼 **방문일·방문시간 컬럼이 없는 명단**이면 사용자에게 행사 일시·층을 확인하고 `default_visit_date` / `default_visit_time` / `default_floor` 인자로 넘긴다(행마다 채우지 않아도 됨). 헤더는 한/영·설문 헤더(`Full Name`, `연락처(…)`, `소속/회사 (…)`) 모두 자동 인식된다.
2. **필터.** 설문 명단이면 `participation="오프라인"` 인자로 오프라인(현장) 참석자만 남긴다(0.2.1+; 참석 형태 컬럼이 없으면 등록 도구가 중단하므로 그때는 사용자에게 확인). 주최자·내부 직원 행은 여전히 사람이 골라 제외한다. 상대 표현("다음 주 화요일")은 실제 날짜로 바꿔 확인한다.
3. **preview.** `preview_visitors_from_text` / `preview_visitors_from_file`로 파싱 결과를 받아 표로 보여준다. 오류 행(휴대폰 누락 등)은 **사용자에게 값을 요청**하거나 제외 여부를 묻는다. 중복 행은 서버가 자동으로 건너뛴다.
4. **확인.** "N명을 M월 D일 HH:MM, F층으로 등록합니다" 를 사용자가 승인하기 전에는 `register_*`를 호출하지 않는다. 처음 쓰는 환경이면 `validate_configuration` 또는 `dry_run=true`로 먼저 확인한다.
5. **등록.** `register_visitors_from_text`(또는 `_from_file`, 1명이면 `register_visitor`). 반환 요약 "총 N명 중 X명 성공, Y명 실패"와 실패 상세를 그대로 보고한다. 부분 실패는 해당 행만 교정해 재호출한다.
6. **결과 보고.**

| # | 방문자 | 소속 | 방문일시 | 층 | 결과 |
|---|---|---|---|---|---|

## 실패 유형

- `센터필드 MCP 설정이 비어 있어…` → 서버 `.env`(`CF_COMPANY_NAME`, `CF_PERSON_IN_CHARGE_MOBILE`) 미설정. 사용자에게 설정 안내.
- `PIC verification rejected` / `No company found` → 입주사명·담당자 번호가 센터필드 등록값과 다름. `validate_configuration` 결과를 보여주고 수정 요청.
- `Floor 18 not offered` → 해당 입주사에 층이 없음. 다른 층으로 재확인.
- `행 N: visitor_mobile …` → 휴대폰 누락/형식 오류. 값 요청.
- 예약 취소 API는 없음. 잘못 등록했으면 센터필드 앱/사이트에서 수동 취소하도록 안내.

## 하지 말 것

- 사용자 확인 없이 `register_*` 호출
- 센터필드 사이트를 직접 HTTP/브라우저로 조작 (MCP 도구만 사용)
- 휴대폰이나 이메일이 없는 방문자를 임의 값으로 채워 등록
- 결과 표에 방문자 개인정보를 필요 이상으로 반복 노출
