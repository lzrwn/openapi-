from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")


def render(template: str, **variables: str) -> str:
    for key, value in variables.items():
        template = template.replace("{{" + key + "}}", value)
    return template
