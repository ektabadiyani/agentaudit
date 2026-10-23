"""Grade AI support answers against the help centre using Claude as the judge."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic

from .models import Article, Confidence, Conversation, Grade, Verdict

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"

INSTRUCTIONS = """\
You are auditing answers given by a company's AI support agent. Judge each answer \
ONLY against the help-centre articles provided below - not against general knowledge, \
and not against what the policy "should" be.

Assign exactly one verdict, using this precedence when more than one applies:
1. "incorrect" - the answer contradicts an article (wrong price, wrong steps, wrong \
eligibility, a promise the policy does not allow).
2. "unsupported" - the answer states a material fact, number, feature or commitment \
that no article contains, even if it sounds plausible.
3. "partial" - everything stated is supported, but the answer leaves out a condition, \
limit or step the customer needs in order to act correctly.
4. "correct" - every material claim is supported and the question is answered.

Handing the customer to a human is "correct" when the articles say the request needs \
support staff, and "partial" when the articles contain the answer the agent should have given.

Ignore tone, greetings and formatting. Cite the ids of the articles you relied on. \
List each unsupported or contradicted claim briefly in the agent's own words. Keep the \
explanation to one or two sentences that a support manager could act on. Set confidence \
to "low" when the articles are ambiguous or the verdict is borderline."""

GRADE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": [v.value for v in Verdict]},
        "confidence": {"type": "string", "enum": [c.value for c in Confidence]},
        "cited_articles": {"type": "array", "items": {"type": "string"}},
        "unsupported_claims": {"type": "array", "items": {"type": "string"}},
        "explanation": {"type": "string"},
    },
    "required": ["verdict", "confidence", "cited_articles", "unsupported_claims", "explanation"],
    "additionalProperties": False,
}


def format_knowledge_base(articles: Iterable[Article]) -> str:
    return "\n\n".join(
        f'<article id="{a.id}">\n<title>{a.title}</title>\n{a.body}\n</article>' for a in articles
    )


class Grader:
    """Grades one answer per API call. The help centre sits in a cached system block,
    so after the first call each grade only pays full price for the question and answer."""

    def __init__(
        self,
        articles: list[Article],
        client: anthropic.Anthropic | None = None,
        model: str = DEFAULT_MODEL,
        effort: str = DEFAULT_EFFORT,
    ):
        self.articles = articles
        self.article_ids = {a.id for a in articles}
        self.client = client or anthropic.Anthropic()
        self.model = model
        self.effort = effort
        self.system = [
            {"type": "text", "text": INSTRUCTIONS},
            {
                "type": "text",
                "text": "<help_centre>\n" + format_knowledge_base(articles) + "\n</help_centre>",
                "cache_control": {"type": "ephemeral"},
            },
        ]

    def grade(self, conversation: Conversation) -> Grade:
        prompt = (
            f"<customer_question>\n{conversation.question}\n</customer_question>\n\n"
            f"<ai_agent_answer>\n{conversation.ai_answer}\n</ai_agent_answer>"
        )
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=self.system,
            messages=[{"role": "user", "content": prompt}],
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": GRADE_SCHEMA},
            },
            # If a safety classifier declines, retry server-side on Anthropic's recommended model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            return Grade(conversation.id, None, model=response.model, error="model declined to grade")
        if response.stop_reason == "max_tokens":
            return Grade(conversation.id, None, model=response.model, error="response truncated")

        text = next(block.text for block in response.content if block.type == "text")
        data = json.loads(text)
        # Drop citations to articles that don't exist, so the report never points at a phantom.
        cited = [a for a in data["cited_articles"] if a in self.article_ids]
        return Grade(
            conversation_id=conversation.id,
            verdict=Verdict(data["verdict"]),
            confidence=Confidence(data["confidence"]),
            cited_articles=cited,
            unsupported_claims=data["unsupported_claims"],
            explanation=data["explanation"].strip(),
            model=response.model,
        )

    def grade_all(
        self,
        conversations: list[Conversation],
        workers: int = 4,
        on_result: Callable[[Grade], None] | None = None,
    ) -> list[Grade]:
        """Grade in parallel. A failure on one conversation is recorded on its Grade and
        the run continues; authentication and permission errors stop the run."""
        results = []

        def safe_grade(conversation: Conversation) -> Grade:
            try:
                return self.grade(conversation)
            except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
                raise
            except anthropic.APIStatusError as e:
                return Grade(conversation.id, None, model=self.model, error=f"API error {e.status_code}: {e.message}")
            except anthropic.APIConnectionError:
                return Grade(conversation.id, None, model=self.model, error="network error")
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                return Grade(conversation.id, None, model=self.model, error=f"unreadable grade: {e}")

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(safe_grade, c) for c in conversations]
            for future in as_completed(futures):
                grade = future.result()
                results.append(grade)
                if on_result:
                    on_result(grade)
        order = {c.id: i for i, c in enumerate(conversations)}
        return sorted(results, key=lambda g: order[g.conversation_id])
