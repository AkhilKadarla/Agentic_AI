"""FinSight web UI (Streamlit). Start it with: uv run finsight ui

Streamlit re-runs this whole script top to bottom on every interaction (a click, a
message). Anything that must survive between runs - the agent and its memory, the chat
as displayed, the latest note - lives in `st.session_state`.
"""

import json

import anthropic
import streamlit as st

from finsight.agent import Done, ResearchAgent, TextDelta, ToolCall, ToolResult
from finsight.charts import chart_rows, metric_chart
from finsight.config import MODEL
from finsight.notes import ResearchNote, format_value, render_markdown, save_note

EXAMPLES = [
    "How has NVIDIA's revenue and net income changed over the last 3 years?",
    "Compare Visa and Mastercard operating margins over 3 years",
    "Is Costco converting its earnings into free cash flow?",
]


def init_state() -> None:
    if "agent" not in st.session_state:
        st.session_state.agent = ResearchAgent()
    st.session_state.setdefault("chat", [])  # what we show: {"role", "text", "tools"}
    st.session_state.setdefault("note", None)


def tool_label(name: str, tool_input: dict) -> str:
    args = ", ".join(f"{key}={value}" for key, value in tool_input.items())
    return f"`{name}({args})`"


def show_message(message: dict) -> None:
    with st.chat_message(message["role"]):
        if message.get("tools"):
            with st.expander(f"🔍 Used {len(message['tools'])} data lookups"):
                for label, is_error in message["tools"]:
                    st.markdown(f"{'⚠️' if is_error else '✅'} {label}")
        st.markdown(message["text"])


def run_agent(prompt: str) -> None:
    """Stream one agent answer into the page, rendering events as they arrive."""
    agent: ResearchAgent = st.session_state.agent
    with st.chat_message("assistant"):
        tools_box = st.container()  # tool calls appear above the answer
        answer_box = st.empty()
        status, text, tools, after_tools = None, "", [], False
        try:
            for event in agent.send(prompt):
                match event:
                    case TextDelta(delta):
                        if after_tools and text:  # start the answer in a new paragraph
                            text += "\n\n"
                        after_tools = False
                        text += delta
                        answer_box.markdown(text + "▌")  # the cursor shows it's still writing
                    case ToolCall(name, tool_input):
                        if status is None:
                            status = tools_box.status("Fetching SEC data...", expanded=True)
                        tools.append([tool_label(name, tool_input), False])
                        status.write(f"🔍 {tools[-1][0]}")
                    case ToolResult(is_error=is_error):
                        tools[-1][1] = is_error
                        after_tools = True
                    case Done():
                        answer_box.markdown(text)
            if status is not None:
                status.update(label=f"Used {len(tools)} data lookups", state="complete")
        except anthropic.APIError as e:
            text += f"\n\n**Error from the Claude API:** {e.message}"
            answer_box.markdown(text)
    st.session_state.chat.append(
        {"role": "assistant", "text": text, "tools": [tuple(t) for t in tools]}
    )


def show_note(note: ResearchNote) -> None:
    st.header(note.title)
    st.caption(
        f"{', '.join(note.tickers)} · data as of {note.data_as_of} · "
        f"confidence: **{note.confidence}**"
    )
    st.write(note.summary)

    rows = chart_rows(note)
    if rows:
        companies = note.tickers[:4]  # the palette has 4 fixed company colors
        columns = st.columns(2)
        for i, (name, metric_rows) in enumerate(rows.items()):
            metric_rows = [r for r in metric_rows if r["company"] in companies]
            columns[i % 2].altair_chart(metric_chart(name, metric_rows, companies), width="stretch")

    st.subheader("Key metrics")
    st.dataframe(
        [
            {
                "Company": m.company,
                "Metric": m.name + (" (derived)" if m.derived else ""),
                "Period": m.period,
                "Value": format_value(m.value, m.unit),
            }
            for m in note.key_metrics
        ],
        hide_index=True,
        width="stretch",
    )
    findings, risks = st.columns(2)
    findings.subheader("Findings")
    findings.markdown("\n".join(f"- {f}" for f in note.findings))
    risks.subheader("Risks & caveats")
    risks.markdown("\n".join(f"- {r}" for r in note.risks))
    st.subheader("Sources")
    for source in note.sources:
        link = f" ([link]({source.url}))" if source.url else ""
        st.markdown(f"- {source.description}{link}")
    st.caption("Educational analysis, not investment advice.")

    json_col, md_col = st.columns(2)
    json_col.download_button(
        "Download JSON", json.dumps(note.model_dump(), indent=2), "research-note.json"
    )
    md_col.download_button("Download Markdown", render_markdown(note), "research-note.md")


def sidebar() -> None:
    agent: ResearchAgent = st.session_state.agent
    with st.sidebar:
        st.title("📊 FinSight")
        st.caption("AI research agent · live SEC EDGAR data")

        if st.button("📝 Generate research note", width="stretch", type="primary"):
            with st.spinner("Writing a structured note from this conversation..."):
                try:
                    note, _usage = agent.write_note()
                    st.session_state.note = note
                    save_note(note)
                except (ValueError, anthropic.APIError) as e:
                    st.error(str(e))
        if st.button("🗑️ New conversation", width="stretch"):
            agent.reset()
            st.session_state.chat = []
            st.session_state.note = None
            st.rerun()

        st.divider()
        usage = agent.total_usage
        cost = usage.cost_usd()
        st.metric("Session cost (est.)", f"${cost:.3f}" if cost is not None else "n/a")
        st.caption(
            f"Model: `{MODEL}`  \n"
            f"Input: {usage.input_tokens:,} new · {usage.cache_write_tokens:,} cache-write · "
            f"{usage.cache_read_tokens:,} cache-read  \n"
            f"Output: {usage.output_tokens:,}"
        )


def main() -> None:
    st.set_page_config(page_title="FinSight", page_icon="📊", layout="wide")
    init_state()
    sidebar()

    chat_tab, note_tab = st.tabs(["💬 Research chat", "📝 Research note"])
    with chat_tab:
        if not st.session_state.chat:
            st.markdown("Ask about any US-listed company. For example:")
            for example in EXAMPLES:
                st.markdown(f"- *{example}*")
        for message in st.session_state.chat:
            show_message(message)
    with note_tab:
        if st.session_state.note:
            show_note(st.session_state.note)
        else:
            st.info("Research a question in the chat, then click **Generate research note**.")

    if prompt := st.chat_input("Ask a research question..."):
        st.session_state.chat.append({"role": "user", "text": prompt})
        with chat_tab:
            show_message(st.session_state.chat[-1])
            run_agent(prompt)
        st.rerun()  # refresh the sidebar's cost and token counts


main()
