from langgraph.graph import END, StateGraph

from agents.single_job_agent import build_single_job_graph
from agents.types import PipelineState


def build_pipeline_graph(model_name: str = "llama3") -> StateGraph:
    """Builds and compiles the full pipeline LangGraph agent.

    Nodes run in order: fetch_api_data → score_all.
    For each job offering fetched from external APIs, the single-job agent is
    invoked to produce a RankingOutput, which is collected into 'rankings'.

    Args:
        model_name (str): Ollama model identifier to pass to the single-job
            agent. Defaults to "llama3".

    Returns:
        StateGraph: The compiled LangGraph application ready to invoke.
    """
    single_job_graph = build_single_job_graph(model_name)

    def fetch_api_data_node(state: PipelineState) -> PipelineState:
        """Fetches job offering data from configured external APIs.

        Args:
            state (PipelineState): Current graph state.

        Returns:
            PipelineState: Updated state with 'api_data' populated.
        """
        # TODO: implement LinkedIn and Indeed API calls
        return state

    def score_all_node(state: PipelineState) -> PipelineState:
        """Scores every job offering in api_data using the single-job agent.

        Args:
            state (PipelineState): Current graph state with api_data populated.

        Returns:
            PipelineState: Updated state with 'rankings' populated.
        """
        rankings = [
            single_job_graph.invoke(
                {
                    "job_offering": job_offering,
                    "profile": state["profile"],
                    "preferences": state["preferences"],
                    "ranking": None,
                }
            )["ranking"]
            for job_offering in state["api_data"].get("job_offerings", [])
        ]
        return {**state, "rankings": rankings}

    graph = StateGraph(PipelineState)
    graph.add_node("fetch_api_data", fetch_api_data_node)
    graph.add_node("score_all", score_all_node)
    graph.set_entry_point("fetch_api_data")
    graph.add_edge("fetch_api_data", "score_all")
    graph.add_edge("score_all", END)
    return graph.compile()
