import os
from pathlib import Path
from typing import Optional

from llama_cpp import Llama

_LLM_INSTANCE: Optional[Llama] = None


def _get_model_path() -> str:
    env_path = os.getenv("LLM_MODEL_PATH")
    if env_path:
        return env_path
    project_root = Path(__file__).resolve().parent
    return str(project_root / "models" / "llama" / "llama-3.2-1b-q4.gguf")


def _get_llm() -> Llama:
    global _LLM_INSTANCE
    if _LLM_INSTANCE is None:
        model_path = _get_model_path()
        _LLM_INSTANCE = Llama(model_path=model_path)
    return _LLM_INSTANCE


def call_gpt(
    prompt: str,
    max_tokens: int = 256,
    temperature: float = 0.2,
    stop: Optional[list[str]] = None,
) -> str:
    llm = _get_llm()
    response = llm(
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        stop=stop,
    )
    return response["choices"][0]["text"].strip()


if __name__ == "__main__":
    user_prompt = input("Enter prompt: ").strip()
    print(call_gpt(user_prompt))
