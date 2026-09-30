from functools import partial

from langgraph.graph import END, START, StateGraph

from app.core.config import Settings
from app.graph.nodes.planner import planner_node
from app.graph.nodes.researcher import PageReader, researcher_node
from app.graph.nodes.reviewer import reviewer_node
from app.graph.nodes.writer import writer_node
from app.graph.routing import route_after_review
from app.graph.state import ResearchState
from app.services.llm import LLMClient
from app.tools.search.base import SearchProvider


def build_research_graph(
    *,
    llm: LLMClient,
    search_provider: SearchProvider,
    page_reader: PageReader,
    settings: Settings,
):
    """组装并编译智能研究工作流。"""

    builder = StateGraph(ResearchState)
    builder.add_node("planner", partial(planner_node, llm=llm))
    builder.add_node(
        "researcher",
        partial(
            researcher_node,
            llm=llm,
            search_provider=search_provider,
            page_reader=page_reader,
            search_limit=settings.search_results_limit,
            max_pages=settings.max_pages_per_step,
        ),
    )
    builder.add_node("reviewer", partial(reviewer_node, llm=llm))
    builder.add_node("writer", partial(writer_node, llm=llm))

    builder.add_edge(START, "planner")
    builder.add_edge("planner", "researcher")
    builder.add_edge("researcher", "reviewer")
    builder.add_conditional_edges(
        "reviewer",
        route_after_review,
        {"researcher": "researcher", "writer": "writer"},
    )
    builder.add_edge("writer", END)
    return builder.compile()
