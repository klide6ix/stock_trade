---
name: readme-sync
description: Use at the start and end of any work session in the stock_trader project. At the start, read README.md to understand current progress (특히 "진행 상태" 및 "다음 작업 후보" 섹션). After finishing work, update README.md — check completed items in "진행 상태" and add a new entry describing what was done this session. Trigger when the user begins a task in this project or reports that a task is complete.
---

# readme-sync

stock_trader 프로젝트의 README.md는 작업 진행 상태를 추적하는 단일 소스이다. 모든 작업 세션은 README.md를 읽는 것으로 시작하고, README.md를 갱신하는 것으로 끝나야 한다.

## 작업 시작 시

1. `README.md`를 Read 도구로 전체 확인한다.
2. 특히 다음 섹션을 파악한다:
   - **진행 상태**: 이미 완료된 항목 (`[x]`) 과 미완 항목 (`[ ]`)
   - **다음 작업 후보**: 사용자가 고려 중인 다음 단계
3. 사용자의 요청이 기존 항목과 어떻게 연결되는지 맥락을 잡은 뒤 작업을 시작한다.

## 작업 완료 시

1. 이번 세션에서 실제로 변경/추가된 내용을 정리한다.
2. `README.md`의 **진행 상태** 섹션을 Edit 도구로 갱신한다:
   - 완료된 작업은 `- [x] ...` 형태로 추가하거나, 미완 항목이 있었다면 `[ ]` → `[x]`로 변경.
   - 한 줄 설명은 구체적이되 간결하게 (예: "Strategy 디렉터리 `buy/` · `sell/` 로 분리").
3. 필요하다면 **다음 작업 후보** 섹션도 조정한다 (완료된 항목 제거, 새로 발견된 후보 추가).
4. 코드 변경이 없는 순수 조사/질문 응답이었다면 README는 건드리지 않는다.

## 주의

- README.md의 기존 어조(한국어, 간결한 체크리스트)를 유지한다.
- 진행 상태 항목을 함부로 삭제하거나 재정렬하지 않는다 — 기존 기록은 보존.
- 불확실하면 갱신 전에 사용자에게 어떤 항목을 추가할지 확인한다.
