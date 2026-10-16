# 논문 → 설명 영상 자동 생성: 요구사항 명세서 루프 (1번 파트)

논문 PDF와 사용자의 강조 포인트를 받아, 영상에 들어가야 할 내용의 체크리스트를
LLM과 반복 다듬은 뒤 JSON 명세서로 확정하는 도구입니다. 확정된 `spec.json`이
2번 파트(영상 생성 에이전트)의 입력이 됩니다.

## 흐름

1. 논문 PDF 업로드 + 강조 포인트 입력 (자유 텍스트)
2. LLM이 마크다운 체크리스트 초안 생성 — 사용자 항목은 `[사용자 강조]` 태그, 나머지는 LLM 보강
3. 수정 요청 박스에 추가·삭제·수정 사항 입력 → LLM이 논문을 참고해 새 체크리스트로 업데이트 (반복)
4. 확정 → `spec-schema.json` 스키마대로 `spec.json` export

## 실행

```bash
python3 -m venv .venv
.venv/bin/pip install streamlit anthropic pypdf
export ANTHROPIC_API_KEY=sk-ant-...   # 또는 UI 사이드바에 입력
.venv/bin/streamlit run app.py        # 웹 UI
# 또는 CLI: .venv/bin/python spec_loop.py 논문.pdf
```

## 파일

- `spec_loop.py` — 프롬프트·LLM 호출·루프 로직 (CLI 포함)
- `app.py` — Streamlit UI (spec_loop 재사용)
- `prompts.md` — 프롬프트 설계 문서
- `spec-schema.json` / `spec-example.json` — 최종 export JSON 스키마와 예시 (2번 파트 인터페이스)
