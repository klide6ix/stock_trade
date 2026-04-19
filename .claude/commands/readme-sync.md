---
description: stock_trader README.md 진행 상태 확인/갱신 루틴 실행
---

`readme-sync` 스킬을 실행해줘.

- 인자가 "start" 이거나 비어 있으면: 작업 시작 루틴 (README.md 읽고 진행 상태·다음 작업 후보 파악)
- 인자가 "end" 또는 "done" 이면: 작업 완료 루틴 (이번 세션 변경 사항을 README.md 진행 상태에 반영)

사용자 인자: $ARGUMENTS
