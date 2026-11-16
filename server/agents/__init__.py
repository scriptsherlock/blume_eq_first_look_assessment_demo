from pathlib import Path

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"


def prompt(name: str, **kw) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8").format(**kw)
