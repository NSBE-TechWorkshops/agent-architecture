"""Terminal UI (Textual). This is a *client* of the REST API: it never touches the agent directly.

    [ this TUI ]  --HTTP-->  [ FastAPI server ]  -->  [ LangGraph agent ]  -->  [ Gmail / mock ]

Every button press becomes an HTTP request, exactly like a web or mobile app would send.
Run it with:  python -m tui.app
"""

import json
import os
from typing import ClassVar

import httpx
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import DataTable, Footer, Header, Markdown, RichLog

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")

URGENCY_STYLE = {"high": "bold red", "medium": "yellow", "low": "green"}
CATEGORY_LABEL = {
    "new_posting": "New posting",
    "application_update": "App update",
    "interview": "Interview",
    "assessment": "Assessment",
    "offer": "OFFER",
    "rejection": "Rejection",
    "deadline_reminder": "Deadline",
    "event": "Event",
    "other": "Other",
}

WELCOME = """# Internship Agent

Press **r** to run the agent.

Watch the *Agent trace* at the bottom: each line is one step (node) of the LangGraph workflow
finishing, streamed to this screen over HTTP.

Other keys: **h** check the API, **s** show digest, **g** show the agent graph, **q** quit.
"""


class InternshipApp(App):
    TITLE = "Internship Agent"
    SUB_TITLE = f"API: {API_URL}"

    CSS = """
    #top { height: 2fr; }
    #table { width: 2fr; height: 100%; border: round $primary; }
    #detail-box { width: 1fr; height: 100%; border: round $secondary; padding: 0 1; }
    #trace { height: 1fr; border: round $accent; padding: 0 1; }
    """

    BINDINGS: ClassVar = [
        ("r", "run_agent", "Run agent"),
        ("h", "health", "Health check"),
        ("s", "digest", "Show digest"),
        ("g", "graph", "Show graph"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict] = []
        self.summary = ""
        self.busy = False
        self._skip_first_highlight = False

    # ------------------------------------------------------------------ layout
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="top"):
            yield DataTable(id="table", cursor_type="row", zebra_stripes=True)
            with VerticalScroll(id="detail-box"):
                yield Markdown(WELCOME, id="detail")
        yield RichLog(id="trace", wrap=True, markup=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.border_title = "Internship updates (most urgent first)"
        table.add_columns("Urgency", "Company", "Role", "Type", "Deadline")
        self.query_one("#detail-box").border_title = "Details"
        trace = self.query_one(RichLog)
        trace.border_title = "Agent trace (live)"
        self.check_health()

    # ------------------------------------------------------------------ actions
    def action_run_agent(self) -> None:
        if self.busy:
            self.notify("The agent is already running.", severity="warning")
            return
        self.stream_agent()

    def action_health(self) -> None:
        self.check_health()

    def action_graph(self) -> None:
        self.show_graph()

    async def action_digest(self) -> None:
        if self.summary:
            await self.show_summary()

    # ------------------------------------------------------------------ HTTP calls (run in background workers)
    @work(exclusive=True, group="health")
    async def check_health(self) -> None:
        log = self.query_one(RichLog)
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                data = (await client.get(f"{API_URL}/health")).json()
            self.sub_title = (
                f"API: {API_URL}  |  mode: {data['mode']}  |  source: {data['source']}"
            )
            log.write(f"[green]GET /health -> {data}[/green]")
        except httpx.HTTPError as exc:
            self.sub_title = f"API: {API_URL}  |  OFFLINE"
            log.write(
                f"[red]GET /health failed: {type(exc).__name__}. Is the API server running?[/red]"
            )

    @work(exclusive=True, group="graph")
    async def show_graph(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                edges = (await client.get(f"{API_URL}/agent/edges")).json()
        except httpx.HTTPError as exc:
            self.notify(f"Could not load graph: {type(exc).__name__}", severity="error")
            return
        lines = []
        for e in edges:
            note = "   (only if the condition is met)" if e["conditional"] else ""
            lines.append(f"- `{e['from']}` -> `{e['to']}`{note}")
        body = (
            "# Agent graph\n\nEach arrow is an edge between two nodes:\n\n"
            + "\n".join(lines)
        )
        await self.query_one(Markdown).update(body)

    @work(exclusive=True, group="agent")
    async def stream_agent(self) -> None:
        self.busy = True
        log = self.query_one(RichLog)
        table = self.query_one(DataTable)
        log.clear()
        table.clear()
        await self.query_one(Markdown).update(
            "# Running...\n\nThe agent is working. Watch the trace below."
        )
        log.write(f"[bold]POST {API_URL}/agent/stream[/bold]")
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(120, connect=5)
            ) as client:
                async with client.stream("POST", f"{API_URL}/agent/stream") as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        event = json.loads(line)
                        await self.handle_event(event, log)
        except httpx.HTTPError as exc:
            log.write(f"[red]Request failed: {type(exc).__name__}: {exc}[/red]")
            await self.query_one(Markdown).update(
                "# Could not reach the API\n\nStart the server and press **r** again."
            )
        finally:
            self.busy = False

    async def handle_event(self, event: dict, log: RichLog) -> None:
        kind = event["type"]
        if kind == "step":
            for message in event["messages"] or [f"{event['node']}: done"]:
                log.write(f"[cyan]>[/cyan] {message}")
        elif kind == "result":
            data = event["data"]
            self.items = data["internships"]
            self.summary = data["summary"]
            self.fill_table()
            log.write(
                f"[green]Done. {len(self.items)} updates from {data['emails_scanned']} emails.[/green]"
            )
            await self.show_summary()
        elif kind == "error":
            log.write(f"[red]Agent error: {event['message']}[/red]")

    # ------------------------------------------------------------------ rendering
    def fill_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        for index, item in enumerate(self.items):
            table.add_row(
                Text(item["urgency"].upper(), style=URGENCY_STYLE[item["urgency"]]),
                item["company"],
                item["role"],
                CATEGORY_LABEL.get(item["category"], item["category"]),
                item["deadline"] or "-",
                key=str(index),
            )
        if self.items:
            self._skip_first_highlight = (
                True  # adding rows highlights row 0; keep the digest on screen
            )
            table.focus()

    async def show_summary(self) -> None:
        await self.query_one(Markdown).update(
            f"# Your digest\n\n{self.summary}\n\n*Select a row for details.*"
        )

    async def on_data_table_row_highlighted(
        self, event: DataTable.RowHighlighted
    ) -> None:
        if event.row_key is None or event.row_key.value is None:
            return
        if self._skip_first_highlight:
            self._skip_first_highlight = False
            return
        item = self.items[int(event.row_key.value)]
        body = (
            f"# {item['company']}\n\n"
            f"**Role:** {item['role']}  \n"
            f"**Type:** {CATEGORY_LABEL.get(item['category'], item['category'])}  \n"
            f"**Urgency:** {item['urgency']}  \n"
            f"**Deadline:** {item['deadline'] or 'none'}\n\n"
            f"**Next step:** {item['action_needed']}\n\n"
            f"---\n*From:* {item['sender']}  \n*Subject:* {item['subject']}  \n*Date:* {item['date']}"
        )
        await self.query_one(Markdown).update(body)


if __name__ == "__main__":
    InternshipApp().run()
