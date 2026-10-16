"""논문 PDF → 영상 요구사항 명세서 생성 루프 (1번 파트).

사용법:
  pip install anthropic pypdf
  export ANTHROPIC_API_KEY=...   # 또는 ant auth login
  python spec_loop.py paper.pdf

흐름: 강조 포인트 입력 → checklist.md 초안 → (수정 요청 입력 → LLM이 반영)* → y 확정 → spec.json
자가 테스트: python spec_loop.py --test
"""
import json
import re
import sys
from pathlib import Path

MODEL = "claude-opus-5-5"
CHECKLIST = Path("checklist.md")
SPEC = Path("spec.json")
SCHEMA = Path(__file__).parent / "spec-schema.json"

FORMAT_RULES = """\
[체크리스트 포맷 규약]
- 섹션은 ## 헤더 (Intro / Related Work / Method / Experiment / Result / Conclusion / Other)
- 항목: `- [ ] **R<n>** [사용자 강조]? 내용 — 근거: p.<페이지>, <그림/표/수식>`
- 항목 ID R<n>은 한번 부여되면 불변, 삭제된 번호 재사용 금지
- [사용자 강조] 태그가 없는 항목은 LLM 보강 항목으로 간주
- 이것은 논문 요약이 아니라 영상 요구사항 목록이다. 항목 내용은 "영상에서 무엇을
  다뤄야 하는지"를 지정하는 한 문장으로 쓴다 (예: "forward/reverse process의 큰 그림을
  Figure 2로 시각화"). 세부 설명, 수식 전개, 수치 나열, 하위 불릿은 금지 —
  세부 내용은 영상 생성 단계에서 논문을 직접 참조한다.
- 근거는 해당 내용이 있는 대표 위치 1~2곳만 적는다."""

PROMPT_DRAFT = """\
당신은 논문 설명 영상의 요구사항 명세서를 작성하는 어시스턴트다.

[사용자 강조 포인트] (자유 텍스트)
{points}

다음 규칙으로 마크다운 체크리스트 초안을 작성하라:
1. 사용자 강조 포인트는 전부 항목화하고 각 항목에 [사용자 강조] 태그를 붙인다.
   사용자의 표현과 의도를 보존하되, 모호하면 영상에서 다룰 대상(개념·수식·그림)을
   특정하는 수준까지만 구체화한다.
2. 논문을 훑어 사용자가 놓친 핵심 내용(기여, 방법 핵심, 주요 결과)을
   태그 없는 항목으로 보강한다.
3. 모든 항목에 영상 소재 탐색용 근거(페이지, 그림/표/수식 번호)를 단다.
   논문에서 확인되지 않는 내용은 "(근거 미확인)"으로 표시한다.
4. {rules}

체크리스트만 출력하고 다른 설명은 붙이지 마라."""

PROMPT_REVIEW = """\
당신은 논문 설명 영상의 요구사항 체크리스트를 업데이트하는 어시스턴트다.

[현재 체크리스트]
{checklist}

[사용자 수정 요청]
{requests}

{rules}

논문을 참고해 수정 요청을 반영한 새 체크리스트 전체를 출력하라. 규칙:
1. 수정 요청에 있는 변경만 반영한다. 요청되지 않은 항목의 추가·삭제·수정 금지.
   요청에서 언급되지 않은 기존 항목은 그대로 복사한다.
2. 추가 요청된 내용은 [사용자 강조] 태그를 붙인 새 항목으로 만들고, 아직 안 쓰인
   다음 번호의 ID(R<n>)와 논문에서 찾은 근거를 단다. 내용에 맞는 섹션에 넣되,
   맞는 섹션이 없으면 새 ## 섹션을 만든다.
3. 삭제·수정 요청은 해당 항목에 그대로 적용한다. 수정 시 ID는 유지한다.
4. 체크리스트 아래에 두 블록을 덧붙인다:

   ### 적용한 변경
   - 요청별로 어떻게 반영했는지 한 줄씩. 반영할 수 없으면(해당 항목 없음 등) 사유.

   ### 지적
   - 중복 쌍(ID로 지칭), 상호 모순, 근거가 논문과 불일치하는 항목.
     수정은 하지 말고 지적만 한다. 없으면 "없음"."""

PROMPT_EXPORT = """\
아래 마크다운 체크리스트를 JSON으로 변환하라.

[확정 체크리스트]
{checklist}

규칙:
- 스키마:
{schema}
- 논문 제목은 "{title}", 파일명은 "{file}"로 채운다.
- 내용을 추가·삭제·요약하지 말고 1:1 변환만 한다.
- [사용자 강조] → "source": "user", 그 외 → "source": "llm"
- 근거 꼬리를 evidence.pages / evidence.figures로 파싱한다. 근거 미확인 항목은 evidence 생략.
- JSON만 출력한다 (코드펜스 없이)."""


def call(client, user_prompt: str, paper: str | None = None) -> str:
    kwargs = dict(
        model=MODEL,
        max_tokens=16000,
        messages=[{"role": "user", "content": user_prompt}],
    )
    if paper:
        # 논문 전문을 system에 고정 → 턴 간 prompt cache 재사용
        kwargs["system"] = [{
            "type": "text",
            "text": "다음은 논문 전문이다.\n\n" + paper,
            "cache_control": {"type": "ephemeral"},
        }]
    with client.messages.stream(**kwargs) as stream:
        msg = stream.get_final_message()
    return "".join(b.text for b in msg.content if b.type == "text")


def split_review(output: str) -> tuple[str, str]:
    """검토 출력을 (체크리스트 본문, 추가·변경/지적 블록)으로 분리."""
    m = re.search(r"^### ", output, flags=re.M)
    if m:
        return output[: m.start()].rstrip(), output[m.start():].rstrip()
    return output.rstrip(), ""


def read_multiline(prompt: str) -> str:
    print(prompt + " (여러 줄 입력, 빈 줄로 종료)")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip():
            break
        lines.append(line)
    return "\n".join(lines)


def extract_pdf(path: Path) -> str:
    from pypdf import PdfReader
    pages = []
    for i, page in enumerate(PdfReader(path).pages, 1):
        pages.append(f"[p.{i}]\n{page.extract_text() or ''}")
    return "\n\n".join(pages)


def main(pdf_path: str) -> None:
    import anthropic

    client = anthropic.Anthropic()
    pdf = Path(pdf_path)
    print(f"PDF 텍스트 추출 중: {pdf.name}")
    paper = extract_pdf(pdf)

    points = read_multiline("강조 포인트를 입력하세요")
    print("초안 생성 중...")
    draft = call(client, PROMPT_DRAFT.format(points=points, rules=FORMAT_RULES), paper)
    CHECKLIST.write_text(draft + "\n", encoding="utf-8")
    print(f"\n{CHECKLIST} 생성됨.\n{draft}\n")

    while True:
        cmd = input("[Enter]=수정 요청 입력 / y=확정 / q=종료: ").strip().lower()
        if cmd == "q":
            return
        current = CHECKLIST.read_text(encoding="utf-8")
        if cmd == "y":
            break
        requests = read_multiline("수정 요청 (추가·삭제·수정할 내용)")
        if not requests.strip():
            continue
        print("논문 참고해 반영 중...")
        out = call(client, PROMPT_REVIEW.format(
            checklist=current, requests=requests, rules=FORMAT_RULES), paper)
        body, blocks = split_review(out)
        CHECKLIST.write_text(body + "\n", encoding="utf-8")
        print(f"\n{CHECKLIST} 갱신됨.\n{body}\n\n{blocks}\n")

    print("JSON export 중...")
    raw = call(client, PROMPT_EXPORT.format(
        checklist=current, schema=SCHEMA.read_text(encoding="utf-8"),
        title=pdf.stem, file=pdf.name,
    ))
    raw = re.sub(r"^```(json)?\s*|\s*```$", "", raw.strip(), flags=re.M)
    spec = json.loads(raw)  # 파싱 실패 시 그대로 죽는 게 맞음 (불량 spec 전달 방지)
    SPEC.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"완료: {SPEC} ({len(spec['items'])}개 항목)")


def _test() -> None:
    out = ("## Method\n- [ ] **R1** [사용자 강조] a — 근거: p.2\n\n"
           "### 적용한 변경\n- R2 추가\n\n### 지적\n- 없음")
    body, blocks = split_review(out)
    assert body == "## Method\n- [ ] **R1** [사용자 강조] a — 근거: p.2"
    assert blocks.startswith("### 적용한 변경") and "### 지적" in blocks
    assert split_review("## A\n- [ ] **R1** x") == ("## A\n- [ ] **R1** x", "")
    print("ok")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("사용법: python spec_loop.py <논문.pdf> | --test")
    _test() if sys.argv[1] == "--test" else main(sys.argv[1])
