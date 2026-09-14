"""
Agentic SDLC Automation Platform — Requirement to PR
=====================================================

Orchestration layer for the 6-scenario pipeline:
  1. Requirement -> Template-filled document (RAG + guardrail rules, via MCP)
  2. Document -> Jira epics/stories/tasks
  3. Figma design -> React components               [validate/regenerate loop]
  4. FRD -> FastAPI route + Pydantic model scaffolding
  5. UI + acceptance criteria -> Playwright tests    [validate/regenerate loop]
  6. SonarQube quality gate -> PR -> HUMAN APPROVAL  [interrupt / resume]

WHY LANGGRAPH (not a linear RAG chain):
  - Steps 3 and 5 are not "generate once" — they're generate -> validate ->
    regenerate, bounded by a max retry count. That's a cycle in the graph,
    which a linear chain of prompts can't express cleanly.
  - State (requirement text, filled doc schema, Jira IDs, Figma node tree,
    generated code, test results, coverage %) has to flow through all six
    steps without each step inventing its own hand-off format.
  - Step 6 needs a genuine pause-and-wait-for-a-human checkpoint that
    survives a process restart. LangGraph's checkpointer + interrupt() give
    you that; a custom loop means you build persistence/resume yourself.

Everything marked "# TODO(real integration)" is a stub. The control flow
around it (state shape, retry logic, conditional routing, human gate) is
real and runs as-is with `python sdlc_pipeline.py`.
"""

from __future__ import annotations

import random
from typing import Literal, Optional, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command


# ---------------------------------------------------------------------------
# 1. Shared pipeline state
# ---------------------------------------------------------------------------
# One typed dict threaded through every node. Each scenario reads what it
# needs from earlier scenarios and writes its own output back in.

class PipelineState(TypedDict, total=False):
    # Input
    requirement_text: str

    # Scenario 1 — template-filled document
    template_type: str                 # e.g. "user_story", "frd"
    guardrail_rules: list[dict]        # retrieved rule chunks per field
    filled_document: dict              # schema-validated field -> value

    # Scenario 2 — Jira
    jira_issue_keys: list[str]

    # Scenario 3 — Figma -> React (retry loop)
    figma_file_id: str
    figma_node_tree: dict
    react_code: dict                   # {component_name: source}
    figma_cycle: int
    figma_validation_passed: bool
    figma_validation_notes: str

    # Scenario 4 — FastAPI scaffolding
    fastapi_code: dict                 # {route_module: source}

    # Scenario 5 — Playwright (retry loop)
    playwright_tests: dict             # {test_file: source}
    playwright_cycle: int
    playwright_validation_passed: bool
    playwright_validation_notes: str

    # Scenario 6 — quality gate + PR + human approval
    sonarqube_coverage_pct: float
    sonarqube_quality_ok: bool
    pr_url: Optional[str]
    human_decision: Optional[Literal["approve", "reject", "request_changes"]]


MAX_FIGMA_CYCLES = 3
MAX_PLAYWRIGHT_CYCLES = 3
COVERAGE_THRESHOLD = 90.0


# ---------------------------------------------------------------------------
# 2. Scenario 1 — Guardrail-driven document generation
# ---------------------------------------------------------------------------

def retrieve_template_and_rules(state: PipelineState) -> PipelineState:
    """Two-stage retrieval: (a) which of the 6 templates applies, (b) the
    guardrail rule chunks for that template's sections."""
    # TODO(real integration):
    #   - MCP client call to the SharePoint-backed MCP server to fetch the
    #     template list / resolve which template applies to this requirement
    #   - Azure AI Search query #1: classify requirement -> template_type
    #   - Azure AI Search query #2: fetch guardrail-rule chunks scoped to
    #     that template (chunked by rule block, per your design)
    template_type = "user_story"  # stub classification
    guardrail_rules = [
        {"section": "Acceptance Criteria", "rule": "derive from requirement verbs"},
        {"section": "Impacted Systems", "rule": "match against system registry"},
    ]
    return {**state, "template_type": template_type, "guardrail_rules": guardrail_rules}


def generate_filled_document(state: PipelineState) -> PipelineState:
    """Structured generation (function-calling / JSON schema) grounded in the
    requirement text + the specific guardrail rule chunk per field."""
    # TODO(real integration):
    #   - Azure OpenAI call with response_format tied to the template's JSON
    #     schema; each field's prompt includes only its own guardrail chunk
    #   - Write the completed document back to SharePoint via the MCP server
    filled_document = {
        "title": "Sample generated story",
        "acceptance_criteria": ["Given/When/Then derived from requirement"],
        "impacted_systems": ["PaymentGateway"],
    }
    return {**state, "filled_document": filled_document}


# ---------------------------------------------------------------------------
# 3. Scenario 2 — Jira auto-creation
# ---------------------------------------------------------------------------

def create_jira_issues(state: PipelineState) -> PipelineState:
    """Map the schema-validated document straight onto Jira's issue schema,
    storing source section IDs as custom fields for traceability."""
    # TODO(real integration): Jira REST API — create epic/story/task, set
    # custom field `source_section_id` = filled_document section reference
    jira_issue_keys = ["PROJ-101", "PROJ-102"]
    return {**state, "jira_issue_keys": jira_issue_keys}


# ---------------------------------------------------------------------------
# 4. Scenario 3 — Figma -> React (generate/validate/regenerate loop)
# ---------------------------------------------------------------------------

def fetch_figma_node_tree(state: PipelineState) -> PipelineState:
    # TODO(real integration): Figma REST API using file ID + PAT, pull the
    # node tree (frames, auto-layout props, component instances, style tokens)
    node_tree = {"frames": ["Header", "Card", "Footer"], "tokens": {"color.primary": "#0055FF"}}
    return {**state, "figma_node_tree": node_tree, "figma_cycle": 0}


def generate_react_code(state: PipelineState) -> PipelineState:
    """Walk the node tree -> React components. Style tokens go into a shared
    theme file (not inlined), repeated instances generated once and reused."""
    # TODO(real integration): code-generation model call, or deterministic
    # tree-walker mapping auto-layout -> flex/grid, tokens -> theme file
    cycle = state.get("figma_cycle", 0) + 1
    react_code = {f.lower(): f"// generated component for {f} (cycle {cycle})"
                  for f in state["figma_node_tree"]["frames"]}
    return {**state, "react_code": react_code, "figma_cycle": cycle}


def validate_react_code(state: PipelineState) -> PipelineState:
    """Checks the generated components against the Figma node tree: every
    frame produced a component, tokens used (not hardcoded colors), etc."""
    # TODO(real integration): structural diff between node_tree and
    # generated JSX/theme file; optionally a visual regression check
    # (render + screenshot diff) for a stronger signal than structure alone
    expected = set(f.lower() for f in state["figma_node_tree"]["frames"])
    got = set(state["react_code"].keys())
    passed = expected == got  # stub check
    # simulate a flaky first pass so the retry path actually exercises
    if state["figma_cycle"] < 2:
        passed = random.random() > 0.4
    notes = "all frames matched" if passed else f"missing/mismatched components: {expected ^ got}"
    return {**state, "figma_validation_passed": passed, "figma_validation_notes": notes}


def route_figma_validation(state: PipelineState) -> str:
    if state["figma_validation_passed"]:
        return "generate_fastapi_code"
    if state["figma_cycle"] >= MAX_FIGMA_CYCLES:
        # Exhausted retries -> don't loop forever, surface for human triage
        return "human_gate"
    return "generate_react_code"


# ---------------------------------------------------------------------------
# 5. Scenario 4 — FastAPI backend scaffolding
# ---------------------------------------------------------------------------

def generate_fastapi_code(state: PipelineState) -> PipelineState:
    """Parse API-relevant FRD sections (endpoints, payload fields, validation
    rules) into FastAPI routes + Pydantic models matching org conventions."""
    # TODO(real integration): LLM call grounded in filled_document's API
    # section + guardrail rules; emit routes matching your existing
    # PayerIQ-style FastAPI + Pydantic + Uvicorn conventions
    fastapi_code = {"routes.py": "# generated FastAPI routes + Pydantic models"}
    return {**state, "fastapi_code": fastapi_code}


# ---------------------------------------------------------------------------
# 6. Scenario 5 — Playwright test generation (generate/validate/regenerate loop)
# ---------------------------------------------------------------------------

def generate_playwright_tests(state: PipelineState) -> PipelineState:
    """Selectors derived from the same component tree Scenario 3 produced,
    assertions derived from the filled document's acceptance criteria."""
    # TODO(real integration): LLM call grounded in filled_document
    # ["acceptance_criteria"] + state["react_code"] component structure
    cycle = state.get("playwright_cycle", 0) + 1
    tests = {f"{name}.spec.ts": f"// test for {name} (cycle {cycle})"
             for name in state["react_code"]}
    return {**state, "playwright_tests": tests, "playwright_cycle": cycle}


def run_playwright_tests(state: PipelineState) -> PipelineState:
    """Actually execute the generated suite (e.g. via `npx playwright test
    --reporter=json`) and capture pass/fail, not just a structural check."""
    # TODO(real integration): shell out to Playwright, parse the JSON
    # reporter output; on failure, feed the failing assertions back into the
    # next generate_playwright_tests call as extra grounding context
    passed = random.random() > 0.35 if state["playwright_cycle"] < 2 else True
    notes = "all tests passed" if passed else "N assertions failed against rendered DOM"
    return {**state, "playwright_validation_passed": passed, "playwright_validation_notes": notes}


def route_playwright_validation(state: PipelineState) -> str:
    if state["playwright_validation_passed"]:
        return "run_sonarqube_gate"
    if state["playwright_cycle"] >= MAX_PLAYWRIGHT_CYCLES:
        return "human_gate"
    return "generate_playwright_tests"


# ---------------------------------------------------------------------------
# 7. Scenario 6 — Quality gate, PR, human approval
# ---------------------------------------------------------------------------

def run_sonarqube_gate(state: PipelineState) -> PipelineState:
    # TODO(real integration): trigger a SonarQube scan of fastapi_code +
    # react_code, poll the SonarQube API for the quality-gate result and
    # coverage %
    coverage = round(random.uniform(85, 97), 1)
    return {
        **state,
        "sonarqube_coverage_pct": coverage,
        "sonarqube_quality_ok": coverage >= COVERAGE_THRESHOLD,
    }


def route_quality_gate(state: PipelineState) -> str:
    if state["sonarqube_quality_ok"]:
        return "open_pull_request"
    # Coverage/quality short of the bar -> loop back to regenerate rather
    # than opening a PR at all (per your design: never open a sub-bar PR)
    return "generate_fastapi_code"


def open_pull_request(state: PipelineState) -> PipelineState:
    """Bundle generated code + tests + a link back to the source FRD/story
    section for context."""
    # TODO(real integration): GitHub/Azure DevOps REST API — create branch,
    # commit fastapi_code + react_code + playwright_tests, open PR with a
    # description linking filled_document's section IDs and jira_issue_keys
    pr_url = "https://example.com/org/repo/pull/123"
    return {**state, "pr_url": pr_url}


def human_gate(state: PipelineState) -> PipelineState:
    """The one checkpoint with real blast radius. interrupt() pauses graph
    execution and persists state via the checkpointer; execution resumes
    when the caller invokes the graph again with a Command(resume=...)."""
    decision = interrupt({
        "message": "Human review required before merge.",
        "pr_url": state.get("pr_url"),
        "figma_validation_notes": state.get("figma_validation_notes"),
        "playwright_validation_notes": state.get("playwright_validation_notes"),
        "sonarqube_coverage_pct": state.get("sonarqube_coverage_pct"),
    })
    return {**state, "human_decision": decision}


def route_human_decision(state: PipelineState) -> str:
    decision = state.get("human_decision")
    if decision == "approve":
        return END
    if decision == "reject":
        return END
    # "request_changes" -> send back to the earliest thing worth retrying
    return "generate_react_code"


# ---------------------------------------------------------------------------
# 8. Build the graph
# ---------------------------------------------------------------------------

def build_pipeline() -> StateGraph:
    graph = StateGraph(PipelineState)

    graph.add_node("retrieve_template_and_rules", retrieve_template_and_rules)
    graph.add_node("generate_filled_document", generate_filled_document)
    graph.add_node("create_jira_issues", create_jira_issues)
    graph.add_node("fetch_figma_node_tree", fetch_figma_node_tree)
    graph.add_node("generate_react_code", generate_react_code)
    graph.add_node("validate_react_code", validate_react_code)
    graph.add_node("generate_fastapi_code", generate_fastapi_code)
    graph.add_node("generate_playwright_tests", generate_playwright_tests)
    graph.add_node("run_playwright_tests", run_playwright_tests)
    graph.add_node("run_sonarqube_gate", run_sonarqube_gate)
    graph.add_node("open_pull_request", open_pull_request)
    graph.add_node("human_gate", human_gate)

    graph.add_edge(START, "retrieve_template_and_rules")
    graph.add_edge("retrieve_template_and_rules", "generate_filled_document")
    graph.add_edge("generate_filled_document", "create_jira_issues")
    graph.add_edge("create_jira_issues", "fetch_figma_node_tree")
    graph.add_edge("fetch_figma_node_tree", "generate_react_code")
    graph.add_edge("generate_react_code", "validate_react_code")

    # --- Figma retry loop ---
    graph.add_conditional_edges(
        "validate_react_code",
        route_figma_validation,
        {
            "generate_react_code": "generate_react_code",
            "generate_fastapi_code": "generate_fastapi_code",
            "human_gate": "human_gate",
        },
    )

    graph.add_edge("generate_fastapi_code", "generate_playwright_tests")
    graph.add_edge("generate_playwright_tests", "run_playwright_tests")

    # --- Playwright retry loop ---
    graph.add_conditional_edges(
        "run_playwright_tests",
        route_playwright_validation,
        {
            "generate_playwright_tests": "generate_playwright_tests",
            "run_sonarqube_gate": "run_sonarqube_gate",
            "human_gate": "human_gate",
        },
    )

    # --- Quality gate loop ---
    graph.add_conditional_edges(
        "run_sonarqube_gate",
        route_quality_gate,
        {
            "open_pull_request": "open_pull_request",
            "generate_fastapi_code": "generate_fastapi_code",
        },
    )

    graph.add_edge("open_pull_request", "human_gate")

    # --- Human decision routing ---
    graph.add_conditional_edges(
        "human_gate",
        route_human_decision,
        {
            END: END,
            "generate_react_code": "generate_react_code",
        },
    )

    return graph


# ---------------------------------------------------------------------------
# 9. Run it
# ---------------------------------------------------------------------------

def main():
    checkpointer = MemorySaver()
    app = build_pipeline().compile(checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "req-2026-09-14-001"}}
    initial_state: PipelineState = {
        "requirement_text": "As a payer-ops user, I need duplicate-claim detection surfaced in the review UI.",
        "figma_file_id": "FIGMA_FILE_ID_HERE",
    }

    result = app.invoke(initial_state, config=config)

    # If the graph hit human_gate, invoke() returns with an __interrupt__ key
    # instead of running to completion.
    if "__interrupt__" in result:
        payload = result["__interrupt__"][0].value
        print("=== PAUSED FOR HUMAN APPROVAL ===")
        print(payload)

        # In a real deployment this resume call happens from a UI/Slack
        # action days later, on a fresh process, using the same thread_id.
        decision = "approve"  # simulate the human's choice
        result = app.invoke(Command(resume=decision), config=config)

    print("=== FINAL STATE ===")
    for key in ("jira_issue_keys", "figma_cycle", "playwright_cycle",
                "sonarqube_coverage_pct", "pr_url", "human_decision"):
        print(f"{key}: {result.get(key)}")


if __name__ == "__main__":
    main()
