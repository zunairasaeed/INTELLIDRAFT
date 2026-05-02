import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from groq import Groq

load_dotenv(Path(__file__).resolve().parent / ".env")

_client: Optional[Groq] = None
def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _client


def call_gpt(
    prompt: str = "",
    max_tokens: int = 512,
    temperature: float = 0.2,
    stop: Optional[list] = None,
    system_prompt: Optional[str] = None,
    user_prompt: Optional[str] = None,
    model: str = "llama-3.3-70b-versatile",
) -> str:
    if system_prompt or user_prompt:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt or prompt})
    else:
        messages = [{"role": "user", "content": prompt}]

    response = _get_client().chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        stop=stop,
    )
    return response.choices[0].message.content or ""


if __name__ == "__main__":
    user_input = input("Enter prompt: ").strip()
    print(call_gpt(prompt=user_input))