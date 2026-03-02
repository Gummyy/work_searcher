from pathlib import Path

from langchain_ollama import ChatOllama
from langgraph.graph import END, StateGraph

from agents.types import RankingOutput, SingleJobState

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_SYSTEM_PROMPT = (_PROMPTS_DIR / "scoring_system_prompt.txt").read_text(
    encoding="utf-8"
)
_USER_MESSAGE_TEMPLATE = (_PROMPTS_DIR / "scoring_user_message_template.txt").read_text(
    encoding="utf-8"
)


def _build_user_message(job_offering: str, profile: str, preferences: str) -> str:
    """Formats the three input texts into a single user message.

    Args:
        job_offering (str): Text description of the job offering.
        profile (str): Candidate's profile text.
        preferences (str): Candidate's preference text.

    Returns:
        str: A formatted prompt string combining all three inputs.
    """
    return _USER_MESSAGE_TEMPLATE.format(
        job_offering=job_offering, profile=profile, preferences=preferences
    )


def build_single_job_graph(model_name: str = "llama3") -> StateGraph:
    """Builds and compiles a LangGraph agent that scores a single job offering.

    The graph contains a single node that calls the LLM with structured output
    to produce a RankingOutput from the provided texts.

    Args:
        model_name (str): Ollama model identifier to use for inference.
            Defaults to "llama3".

    Returns:
        StateGraph: The compiled LangGraph application ready to invoke.
    """
    structured_llm = ChatOllama(model=model_name).with_structured_output(RankingOutput)

    def score_node(state: SingleJobState) -> SingleJobState:
        """Calls the LLM and stores the ranking result in the state.

        Args:
            state (SingleJobState): Current graph state holding the input texts.

        Returns:
            SingleJobState: Updated state with the 'ranking' field populated.
        """
        messages = [
            ("system", _SYSTEM_PROMPT),
            (
                "human",
                _build_user_message(
                    state["job_offering"], state["profile"], state["preferences"]
                ),
            ),
        ]
        return {**state, "ranking": structured_llm.invoke(messages)}

    graph = StateGraph(SingleJobState)
    graph.add_node("score", score_node)
    graph.set_entry_point("score")
    graph.add_edge("score", END)
    return graph.compile()
