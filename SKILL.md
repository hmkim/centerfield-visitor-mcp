---
name: centerfield-visitor-registration
display_name: 센터필드 방문자 등록
description: "센터필드 빌딩(www.centerfield.co.kr) 방문자 사전등록을 자동화합니다. 로컬 MCP 서버(centerfield-visitor-mcp)의 도구로 단건/일괄(엑셀·CSV·텍스트) 등록을 처리합니다. '센터필드 방문 등록', '방문자 등록', '방문 예약', 'visitor registration', 'centerfield reservation' 등의 요청 시 이 스킬을 로드할 것."
icon: "🏢"
trigger: 센터필드 방문 등록
inputs:
  - name: visitor_info
    description: "방문자 정보 — 엑셀/CSV 파일(.xlsx/.csv) 또는 텍스트(이름, 소속 회사, 휴대폰, 이메일, 방문일, 방문시간). 한 명만 텍스트로 알려줘도 됨."
    type: string
    required: true
  - name: floor
    description: "방문 층 ('12' 또는 '18'). 생략 시 서버의 CF_DEFAULT_FLOOR 값(기본 '12')을 사용."
    type: string
    required: false
tools: [register_visitor, register_visitors_from_file, register_visitors_from_text, preview_visitors_from_file]
---

## Overview

센터필드 빌딩 방문자 사전등록을 로컬 MCP 서버(`centerfield-visitor-mcp`)를 통해 자동 처리합니다.
CSRF/세션/담당자(person in charge) 검증·입주사 매핑은 모두 MCP가 처리하므로, 이 스킬은 방문자 정보만 전달합니다.

- 인원수에 비례해 순차 처리됩니다(1명당 약 0.5초, `CF_REQUEST_DELAY`로 조정).
- 담당자·입주사·빌딩 정보는 MCP 환경변수에 설정되어 있으므로 매 호출마다 보낼 필요가 없습니다.

사용자가 방문자 정보를 주면(파일 또는 텍스트) 필요한 정보를 확인한 뒤 등록합니다.

## MCP 정보

| 항목 | 값 |
|------|-----|
| MCP 서버 | `centerfield-visitor` (`uvx centerfield-visitor-mcp`) |
| 단건 등록 | `register_visitor(visitor_name, visitor_company_name, visitor_mobile, visitor_email, visit_date, visit_time, visit_purpose, floor)` |
| 파일 일괄 등록 | `register_visitors_from_file(file_path)` — `.xlsx`/`.csv` **절대경로** (헤더 한/영 자동 매핑) |
| 텍스트 일괄 등록 | `register_visitors_from_text(text)` — 헤더 포함 CSV/TSV 텍스트 |
| 미리보기 | `preview_visitors_from_file(file_path)` — 등록 없이 파싱 결과만 확인 |
| 담당자·입주사·빌딩·기본 층 | MCP 환경변수(`CF_COMPANY_NAME`, `CF_PERSON_IN_CHARGE_MOBILE`, `CF_BUILDING`, `CF_BUILDING_KEY`, `CF_DEFAULT_FLOOR`)에 설정됨 — 클라이언트 입력 불필요 |

> ✅ **일괄 등록은 동기 순차 처리입니다.** 도구가 결과 요약("총 N명 중 X명 성공, Y명 실패" + 실패 상세)을 **즉시 반환**합니다. job_id/폴링 없음. 호출당 최대 인원은 `CF_BULK_MAX_VISITORS`(기본 200명), 호출 간 지연은 `CF_REQUEST_DELAY`(기본 0.5초).
>
> **권장 순서**: `preview_visitors_from_file`로 파싱 확인 → `register_visitors_from_file`로 등록.

## 필수 정보

방문자 1명 기준 최소 필요 정보:

| 필드 | 필수 | 형식/비고 |
|------|------|-----------|
| 이름 (`visitor_name`) | ✅ | |
| 소속 회사 (`visitor_company_name`) | ✅ | 방문자의 소속 회사명 |
| 휴대폰 (`visitor_mobile`) | ✅ | 숫자만 (MCP가 하이픈 자동 제거) |
| 이메일 (`visitor_email`) | ✅ | 유효한 이메일 주소 |
| 방문일 (`visit_date`) | ✅ | `YYYY-MM-DD` |
| 방문시간 (`visit_time`) | ✅ | `HH:MM`, 30분 단위, 08:00~20:00 |
| 방문 목적 (`visit_purpose`) | 선택 | 기본값 `meeting` |
| 층 (`floor`) | 선택 | `12` 또는 `18`, 생략 시 `CF_DEFAULT_FLOOR` |

**이메일 또는 휴대폰이 없으면 반드시 사용자에게 물어볼 것** — 둘 다 없이는 등록할 수 없습니다.

## Workflow

### Step 1: 방문자 정보 파싱 및 확인
- **Mode**: `agentic`
- **Input**: 사용자가 제공한 방문자 정보 (엑셀/CSV 파일 또는 텍스트)
- **Output**: 정리된 방문자 리스트 [{name, company, mobile, email, date, time, purpose, floor}]
- **Validate**: 각 방문자의 이름·소속·휴대폰·이메일·방문일·방문시간이 모두 있는지
- **On failure**: 누락 정보를 사용자에게 요청

날짜는 "다음주 화요일" 같은 표현이면 실제 날짜(`YYYY-MM-DD`)로 변환해 확인합니다.
방문 목적 기본값은 `meeting`입니다.

> 💡 MCP의 `register_visitors_from_file`이 엑셀/CSV를 직접 읽으므로, 파일이 있으면 별도 파싱 없이 **파일 절대경로를 그대로** 넘겨도 됩니다. 등록 전 `preview_visitors_from_file`로 파싱 결과를 먼저 확인하는 것을 권장합니다.

### Step 2: 센터필드 등록 (MCP 도구 호출)
- **Mode**: `deterministic`
- **Tool**: `register_visitors_from_file` / `register_visitors_from_text` / `register_visitor`
- **Output**: MCP가 반환한 요약 문자열(총/성공/실패 + 실패 상세)
- **Validate**: 반환 문자열에서 "실패 0명" 확인. 실패 건은 메시지의 행 번호·필드를 확인해 교정 후 재등록
- **On failure**: 회사/담당자 불일치면 MCP 환경변수 설정값 확인; 입력값 오류면 해당 필드 교정 후 재호출 (CSRF·세션·재시도는 MCP가 내부 처리)

**도구 선택 기준:**
- 엑셀/CSV 파일이 있으면 → `preview_visitors_from_file(file_path)`로 먼저 확인 → `register_visitors_from_file(file_path)` (둘 다 **절대경로**)
- 텍스트(복사/붙여넣기)면 → `register_visitors_from_text(text)` (첫 줄 헤더 필수: `이름,회사,전화번호,이메일,방문일,방문시간`)
- 1명만이면 → `register_visitor(visitor_name=..., visitor_company_name=..., visitor_mobile=..., visitor_email=..., visit_date=..., visit_time=..., visit_purpose=..., floor=...)`

**층(floor) 처리:** MCP 도구는 `floor`가 생략되면 `CF_DEFAULT_FLOOR`(기본 `12`)를 적용합니다. 특정 방문이 다른 층이면 단건은 `floor="18"`처럼 명시하고, 파일/텍스트 일괄 등록은 입력 데이터에 `층`/`floor` 컬럼을 포함하세요.

**visit_purpose 옵션**: `visit_business`(업무) | `meeting`(미팅) | `interview`(면접) | `tour`(투어) | `construction`(공사) | `others`(기타)

### Step 3: 결과 보고
- **Mode**: `agentic`
- **Output**: 등록 결과 테이블

## File / Text format

헤더 행(한글 또는 영문, 자동 매핑)을 포함한 CSV/TSV 또는 엑셀:

```
이름,회사,전화번호,이메일,방문일,방문시간,층
홍길동,ABC주식회사,01012345678,hong@abc.com,2026-01-15,10:00,12
김영희,XYZ코퍼레이션,01087654321,kim@xyz.com,2026-01-15,10:30,18
```

> 위 이름·회사·연락처는 형식 설명을 위한 가상의 예시입니다.

## Output

| # | 방문자 | 소속 | 방문일시 | 층 | 결과 |
|---|--------|------|----------|----|------|
| 1 | 이름 | 회사 | YYYY-MM-DD HH:MM | 12/18 | ✅/❌ |

## Lessons Learned

### Do
- 일괄은 `register_visitors_from_file`/`register_visitors_from_text`, 단건은 `register_visitor` 사용
- 등록 전 `preview_visitors_from_file`로 파싱 결과 확인
- `visitor_email` 필수, `visitor_mobile`은 숫자만(MCP가 하이픈 자동 제거)
- `floor`는 `12`/`18` — 기본 층과 다르면 명시(단건) 또는 데이터에 층 컬럼 포함(일괄)
- 담당자·입주사·빌딩은 MCP 환경변수 설정값 사용 — 클라이언트가 보낼 필요 없음
- 일부 실패 시 반환된 실패 상세에서 해당 방문자만 교정하여 재등록

### Don't
- 센터필드를 브라우저(`fetch`/CSRF 직접 처리)나 직접 HTTP 호출로 제어하지 말 것 — 반드시 MCP 도구 사용
- 이메일 없이 등록하지 말 것 (이메일 필수)
- 방문시간을 30분 단위·08:00~20:00 범위 밖으로 넣지 말 것 (검증 실패)

### Common Failures
- **회사/담당자 불일치로 등록 실패**: MCP 환경변수(`CF_COMPANY_NAME`, `CF_PERSON_IN_CHARGE_MOBILE`)가 센터필드에 등록된 입주사명·승인 담당자 휴대폰과 일치하는지 확인. (별도 검증 엔드포인트 없음 — 1명 등록 또는 preview로 확인.)
- **`uvx`로 MCP 실행 실패 / 도구가 안 보임**: MCP 클라이언트가 서버를 로드했는지 확인(세션 재시작), `uvx centerfield-visitor-mcp` 설치 가능 여부 확인.
- **네트워크 egress/DNS 실패 (`www.centerfield.co.kr` 접속 불가)**: MCP는 로컬에서 센터필드 사이트에 직접 접속하므로, 외부 인터넷이 가능한 환경에서 실행해야 함.
- **입력값 검증 실패 (이메일/휴대폰/시간/층 등)**: 반환 메시지의 행 번호·필드 확인 → 교정 후 재호출. 이메일·휴대폰 누락 시 사용자에게 요청.

### When to Ask the User
- 이메일 또는 휴대폰이 누락된 경우 (등록 시 필수)
- 방문 날짜/시간이 불명확한 경우
- 방문 층이 기본값과 다른지 불명확한 경우
