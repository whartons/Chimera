"""Assemble the on-brand positive/negative prompt from a manifest + subject."""
from .manifest import BrandManifest


def build_prompt(m: BrandManifest, subject: str) -> tuple[str, str]:
    parts = []
    if m.prompt_prefix:
        parts.append(m.prompt_prefix.strip())
    parts.append(subject.strip())
    if m.style:
        parts.append(m.style.strip())
    if m.palette:
        parts.append("brand palette " + ", ".join(str(c) for c in m.palette))
    pos = ", ".join(p for p in parts if p)
    if m.prompt_suffix:
        # suffix may start with its own comma/space; normalize
        pos = pos + (m.prompt_suffix if m.prompt_suffix.startswith((",", " ")) else ", " + m.prompt_suffix)
    return pos.strip(), m.negative.strip()


def build_audio_prompt(m: BrandManifest, subject: str, mode: str) -> tuple[str, str]:
    """Audio prompt assembly. music: brand sonic identity (music_tags) + the brief, no text
    negative (ACE-Step zeroes the positive). foley: the subject IS the SFX description; the
    negative comes from the brand's foley_negative."""
    subject = (subject or "").strip()
    if mode == "foley":
        return subject, m.audio.foley_negative.strip()
    parts = [p for p in (m.audio.music_tags.strip(), subject) if p]
    return ", ".join(parts), ""
