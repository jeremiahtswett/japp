"""Experience corpus: parsing a master resume (+ optional supplemental context
document) into a structured, user-editable YAML file (spec §3).

The corpus is the ONLY pool of facts the tailoring engine may draw from
(ground rule 1). Extraction here is pure transcription of the user's own
documents — no fabrication risk. IDs are assigned in code, never trusted
from the model, so later stages can safely reference and validate them.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import yaml

from japp.config import Config, ConfigError

RESUME_EXTENSIONS = (".pdf", ".docx")

CORPUS_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "contact": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "location": {"type": "string"},
                "email": {"type": "string"},
                "links": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["name", "location", "email", "links"],
            "additionalProperties": False,
        },
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "institution": {"type": "string"},
                    "detail": {"type": "string", "description": "degree/major/GPA line"},
                    "dates": {"type": "string"},
                    "highlights": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["institution", "detail", "dates", "highlights"],
                "additionalProperties": False,
            },
        },
        "sections": {
            "type": "array",
            "description": "work experience, projects, and leadership entries, in one list",
            "items": {
                "type": "object",
                "properties": {
                    "section_type": {"type": "string", "enum": ["experience", "project", "leadership"]},
                    "name": {"type": "string", "description": "company, or project/org name"},
                    "title": {"type": "string", "description": "role title; empty string for projects"},
                    "location": {"type": "string"},
                    "dates": {"type": "string"},
                    "bullets": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "source": {
                                    "type": "string",
                                    "enum": ["master_resume", "supplemental_context"],
                                },
                            },
                            "required": ["text", "source"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["section_type", "name", "title", "location", "dates", "bullets"],
                "additionalProperties": False,
            },
        },
        "skills": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["contact", "education", "sections", "skills"],
    "additionalProperties": False,
}

EXTRACTION_SYSTEM_PROMPT = """You extract a structured "experience corpus" from a \
person's resume (and optionally a supplemental context document) for use by a \
resume-tailoring tool.

Rules:
- Extract only what is actually written in the provided document(s). Never invent, \
infer, or embellish employers, titles, dates, degrees, metrics, or accomplishments.
- Preserve each bullet's original wording as closely as possible - this is a \
transcription task, not a rewrite. Fix only obvious OCR/formatting artifacts.
- Every bullet gets source "master_resume" unless it came only from the supplemental \
context document, in which case source "supplemental_context".
- section_type is "experience" for jobs/internships, "project" for personal/academic \
projects, "leadership" for leadership/volunteer/extracurricular activities.
- If a field genuinely isn't present (e.g. no email listed), use an empty string \
(or empty list for highlights/links) - never a placeholder."""


def find_master_resume(corpus_dir: Path) -> Path:
    candidates = sorted(
        p for p in corpus_dir.glob("*") if p.suffix.lower() in RESUME_EXTENSIONS
    )
    if not candidates:
        raise ConfigError(
            f"No resume found in {corpus_dir}. Drop your master resume "
            f"(.pdf or .docx) into that folder, then run `japp parse-resume`."
        )
    if len(candidates) > 1:
        raise ConfigError(
            f"Found multiple resume files in {corpus_dir}: "
            f"{[c.name for c in candidates]}. Keep only one master resume there."
        )
    return candidates[0]


def find_supplemental_context(corpus_dir: Path) -> str | None:
    for name in ("supplemental_context.md", "supplemental_context.txt"):
        path = corpus_dir / name
        if path.exists():
            return path.read_text(encoding="utf-8")
    return None


def _docx_text(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _resume_content_block(path: Path) -> dict:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}
    if suffix == ".docx":
        return {"type": "text", "text": _docx_text(path)}
    raise ConfigError(f"Unsupported resume format: {suffix} (use .pdf or .docx)")


def assign_ids(raw: dict) -> dict:
    """Attach deterministic, code-controlled IDs to every education/section/bullet."""
    for i, edu in enumerate(raw.get("education", []), start=1):
        edu["id"] = f"edu-{i}"
    for i, sec in enumerate(raw.get("sections", []), start=1):
        sec["id"] = f"sec-{i}"
        for j, bullet in enumerate(sec.get("bullets", []), start=1):
            bullet["id"] = f"sec-{i}-b{j}"
    return raw


def extract_corpus(client, model: str, resume_path: Path, supplemental_text: str | None) -> dict:
    """One structured-output call: resume (+ optional supplemental doc) -> raw corpus dict."""
    content: list[dict] = [_resume_content_block(resume_path)]
    if supplemental_text:
        content.append({
            "type": "text",
            "text": ("Supplemental context document (extra truthful detail the resume "
                      f"doesn't fully capture):\n\n{supplemental_text}"),
        })
    content.append({"type": "text", "text": "Extract the structured experience corpus from the document(s) above."})

    response = client.messages.create(
        model=model,
        max_tokens=8192,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
        output_config={"format": {"type": "json_schema", "schema": CORPUS_EXTRACTION_SCHEMA}},
    )
    text = next(b.text for b in response.content if b.type == "text")
    return assign_ids(json.loads(text))


def corpus_path(cfg: Config) -> Path:
    return cfg.home / "corpus" / "experience_corpus.yaml"


def load_corpus(cfg: Config) -> dict:
    path = corpus_path(cfg)
    if not path.exists():
        raise ConfigError("No experience corpus found. Run `japp parse-resume` first.")
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ConfigError(f"{path} is empty or not valid YAML.")
    return data


def save_corpus(cfg: Config, corpus: dict, force: bool = False) -> Path:
    path = corpus_path(cfg)
    if path.exists() and not force:
        raise ConfigError(
            f"{path} already exists (you may have hand-edited it to add extra truthful "
            f"bullets). Use --force to overwrite and re-extract from scratch, which "
            f"discards those edits."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(corpus, f, sort_keys=False, allow_unicode=True, width=100)
    return path


def total_bullet_budget(corpus: dict) -> int:
    """Rough one-page proxy: bullet count across experience+project sections."""
    return sum(
        len(sec["bullets"]) for sec in corpus.get("sections", [])
        if sec.get("section_type") != "leadership"
    )


def find_bullet(corpus: dict, bullet_id: str) -> tuple[dict, dict] | None:
    """-> (section, bullet) for a given bullet id, or None if not found."""
    for sec in corpus.get("sections", []):
        for bullet in sec.get("bullets", []):
            if bullet["id"] == bullet_id:
                return sec, bullet
    return None


def find_section(corpus: dict, section_id: str) -> dict | None:
    for sec in corpus.get("sections", []):
        if sec["id"] == section_id:
            return sec
    return None
