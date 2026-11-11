import os
import argparse
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from anthropic import Anthropic
from google import genai

load_dotenv()

MODELS = {
    "gpt": {
        "id": "gpt-6-astra",
        "key": "OPENAI_API_KEY"
    },
    "claude": {
        "id": "claude-opus-5-5",
        "key": "ANTHROPIC_API_KEY"
    },
    "gemini": {
        "id": "gemini-3.8-flash",
        "key": "GOOGLE_API_KEY"
    }
}


def generate_program(provider, problem):
    model = MODELS[provider]

    api_key = os.getenv(model["key"])
    if not api_key:
        raise ValueError(
            f"Missing {model['key']} in .env"
        )

    prompt = (
        "You are an expert Python programmer.\n"
        "Write a correct Python 3 solution to this problem.\n"
        "Return only executable Python code. "
        "Do not use Markdown code fences.\n\n"
        f"Problem:\n{problem}"
    )

    if provider == "gpt":
        client = OpenAI(api_key=api_key)

        response = client.responses.create(
            model=model["id"],
            input=prompt
        )
        return response.output_text

    elif provider == "claude":
        client = Anthropic(api_key=api_key)

        response = client.messages.create(
            model=model["id"],
            max_tokens=4096,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        return "\n".join(
            block.text
            for block in response.content
            if block.type == "text"
        )

    elif provider == "gemini":
        client = genai.Client(api_key=api_key)

        response = client.models.generate_content(
            model=model["id"],
            contents=prompt
        )

        return response.text or ""


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--model",
        choices=MODELS.keys(),
        required=True
    )

    args = parser.parse_args()

    problem = (
        "Write a Python function named two_sum "
        "that takes a list of integers and a target. "
        "Return the indices of two different elements "
        "whose sum equals the target. "
        "If no pair exists, return an empty list."
    )

    print(f"Generating with {args.model}...")

    program = generate_program(
        args.model, problem
    )

    if not program.strip():
        raise RuntimeError("Model returned no code.")

    output_dir = Path("generated")
    output_dir.mkdir(exist_ok=True)

    # Store the raw response for later inspection.
    filename = output_dir / f"{args.model}_solution.txt"
    filename.write_text(program, encoding="utf-8")

    print("\nGenerated program:\n")
    print(program)
    print(f"\nSaved to: {filename}")
