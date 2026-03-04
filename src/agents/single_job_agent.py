from pathlib import Path

from langchain_ollama import ChatOllama
from langgraph.graph import END, StateGraph

from agents.types import RankingOutput, ScoringInput, SingleJobState

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_SYSTEM_PROMPT = (_PROMPTS_DIR / "scoring_system_prompt.txt").read_text(
    encoding="utf-8"
)
_USER_MESSAGE_TEMPLATE = (_PROMPTS_DIR / "scoring_user_message_template.txt").read_text(
    encoding="utf-8"
)


def _build_user_message(scoring_input: ScoringInput) -> str:
    """Formats a ScoringInput into a single user message string.

    Args:
        scoring_input (ScoringInput): The structured LLM input for one job.

    Returns:
        str: A formatted prompt string combining all scoring input fields.
    """
    document_categories_text = "\n".join(
        f"- {dc.category}: {dc.description}" for dc in scoring_input.document_categories
    )
    return _USER_MESSAGE_TEMPLATE.format(
        job_description=scoring_input.job_description,
        document_categories=document_categories_text,
        profile=scoring_input.profile,
        preferences=scoring_input.preferences,
    )


def build_single_job_graph(model_name: str = "llama3") -> StateGraph:
    """Builds and compiles a LangGraph agent that scores a single job offering.

    The graph contains a single node that calls the LLM with structured output
    to produce a RankingOutput from the provided ScoringInput.

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
            state (SingleJobState): Current graph state holding the ScoringInput.

        Returns:
            SingleJobState: Updated state with the 'ranking' field populated.
        """
        messages = [
            ("system", _SYSTEM_PROMPT),
            ("human", _build_user_message(state["scoring_input"])),
        ]
        return {**state, "ranking": structured_llm.invoke(messages)}

    graph = StateGraph(SingleJobState)
    graph.add_node("score", score_node)
    graph.set_entry_point("score")
    graph.add_edge("score", END)
    return graph.compile()
