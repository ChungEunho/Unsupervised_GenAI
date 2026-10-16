"""요구사항 명세서 생성 루프 — Streamlit UI.

실행: .venv/bin/streamlit run app.py
로직·프롬프트는 spec_loop.py 재사용.
"""
import json
import re

import streamlit as st

import spec_loop as sl

st.set_page_config(page_title="영상 요구사항 명세서", layout="wide")
st.title("논문 → 영상 요구사항 체크리스트")

ss = st.session_state
ss.setdefault("paper", None)
ss.setdefault("pdf_name", "")
ss.setdefault("blocks", "")
ss.setdefault("spec", None)

api_key = st.sidebar.text_input("ANTHROPIC_API_KEY (비우면 환경변수 사용)", type="password")


def client():
    import anthropic
    return anthropic.Anthropic(api_key=api_key or None)


pdf = st.file_uploader("논문 PDF", type="pdf")
if pdf and ss.pdf_name != pdf.name:
    with st.spinner("PDF 텍스트 추출 중..."):
        ss.paper = sl.extract_pdf(pdf)
    ss.pdf_name = pdf.name
    ss.pop("checklist", None)
    ss.blocks, ss.spec = "", None

if ss.paper and "checklist" not in ss:
    points = st.text_area("강조 포인트 (자유 텍스트, 여러 줄)", height=150,
                          placeholder="- 노이즈를 점점 넣었다 빼는 큰 그림\n- 손실함수가 단순해진다는 거")
    if st.button("초안 생성", type="primary", disabled=not points.strip()):
        with st.spinner("초안 생성 중..."):
            ss.checklist = sl.call(
                client(), sl.PROMPT_DRAFT.format(points=points, rules=sl.FORMAT_RULES), ss.paper)
        st.rerun()

if "checklist" in ss:
    st.subheader("현재 체크리스트")
    st.markdown(ss.checklist)
    if ss.blocks:
        with st.expander("지난 턴 적용 내역·지적", expanded=True):
            st.markdown(ss.blocks)
    st.divider()

    # 버튼을 입력창보다 먼저 처리해야 반영 후 입력창을 비울 수 있음
    col1, col2 = st.columns(2)
    if col1.button("수정 요청 반영"):
        requests = ss.get("requests", "").strip()
        if not requests:
            st.warning("수정 요청을 먼저 입력하세요.")
        else:
            with st.spinner("논문 참고해 반영 중..."):
                out = sl.call(client(), sl.PROMPT_REVIEW.format(
                    checklist=ss.checklist, requests=requests, rules=sl.FORMAT_RULES), ss.paper)
            ss.checklist, ss.blocks = sl.split_review(out)
            ss.requests = ""
            st.rerun()
    if col2.button("확정 → JSON export", type="primary"):
        with st.spinner("JSON 변환 중..."):
            raw = sl.call(client(), sl.PROMPT_EXPORT.format(
                checklist=ss.checklist, schema=sl.SCHEMA.read_text(encoding="utf-8"),
                title=ss.pdf_name.removesuffix(".pdf"), file=ss.pdf_name))
        raw = re.sub(r"^```(json)?\s*|\s*```$", "", raw.strip(), flags=re.M)
        ss.spec = json.loads(raw)

    st.text_area("수정 요청 (추가·삭제·수정할 내용)", key="requests", height=150,
                 placeholder="- 대표 Experiments 항목 추가\n- R3 삭제\n- R5를 더 간단하게")

if ss.spec:
    st.success(f"확정 완료 — {len(ss.spec['items'])}개 항목")
    data = json.dumps(ss.spec, ensure_ascii=False, indent=2)
    st.download_button("spec.json 다운로드", data, file_name="spec.json", mime="application/json")
    with st.expander("spec.json 미리보기"):
        st.json(ss.spec)
