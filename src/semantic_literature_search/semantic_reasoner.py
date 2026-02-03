import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_community.llms import LlamaCpp

DEFAULT_MAX_TOKENS = 256
DEFAULT_TEMPERATURE = 0.0


class SemanticReasoner:
    def __init__(
        self,
        model_path: Optional[str] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> None:
        resolved_path = model_path or self._default_model_path()
        self._llm = LlamaCpp(
            model_path=resolved_path,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._parser = StrOutputParser()
        self._prompt = PromptTemplate(
            input_variables=["title", "abstract", "keywords"],
            template=(
                "You are a research assistant. Use ONLY the provided inputs.\n"
                "Return JSON with keys: expanded_keywords (list of strings),\n"
                "queries (list of 2-3 academic search queries), domain (string),\n"
                "intent (string).\n"
                "Rules:\n"
                "- Do not add validation steps.\n"
                "- Do not normalize or clean text.\n"
                "- Keep outputs concise and relevant.\n"
                "- Return valid JSON only.\n\n"
                "Title: {title}\n"
                "Abstract: {abstract}\n"
                "Keywords: {keywords}\n"
            ),
        )

    @staticmethod
    def _default_model_path() -> str:
        env_path = os.getenv("LLM_MODEL_PATH")
        if env_path:
            return env_path
        project_root = Path(__file__).resolve().parents[2]
        return str(project_root / "models" / "llama" / "llama-3.2-1b-q4.gguf")

    def run(
        self,
        title: str,
        abstract: str,
        keywords: List[str],
    ) -> Dict[str, Any]:
        chain = self._prompt | self._llm | self._parser
        raw = chain.invoke(
            {
                "title": title,
                "abstract": abstract,
                "keywords": ", ".join(keywords),
            }
        )
        return self._parse_output(raw)

    @staticmethod
    def _parse_output(raw: str) -> Dict[str, Any]:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {
                "expanded_keywords": [],
                "queries": [],
                "domain": "",
                "intent": "",
            }

        expanded = parsed.get("expanded_keywords", [])
        queries = parsed.get("queries", [])
        domain = parsed.get("domain", "")
        intent = parsed.get("intent", "")

        return {
            "expanded_keywords": expanded if isinstance(expanded, list) else [],
            "queries": queries if isinstance(queries, list) else [],
            "domain": domain if isinstance(domain, str) else "",
            "intent": intent if isinstance(intent, str) else "",
        }


if __name__ == "__main__":
    title_input = input("Enter cleaned title: ").strip()
    abstract_input = input("Enter cleaned abstract: ").strip()
    keywords_input = input("Enter keywords (comma-separated): ").strip()
    keywords_list = [k.strip() for k in keywords_input.split(",") if k.strip()]

    reasoner = SemanticReasoner()
    output = reasoner.run(title_input, abstract_input, keywords_list)
    print(output)
