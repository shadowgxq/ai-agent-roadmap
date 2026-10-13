"""Citation membership is deterministic; claim support needs a separate audit."""

from dataclasses import dataclass
import re


ABSTENTION = "无法从当前知识库确认。"


@dataclass(frozen=True)
class CitationValidation:
    text: str
    cited_ids: tuple[str, ...]
    invalid_ids: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return bool(self.cited_ids) and not self.invalid_ids


def validate_citations(text: str, allowed_ids: set[str]) -> CitationValidation:
    # The draft contract reserves square brackets for citation IDs.
    supplied = tuple(dict.fromkeys(re.findall(r"\[([^\[\]\n]+)\]", text)))
    invalid = tuple(value for value in supplied if value not in allowed_ids)
    clean = re.sub(r"\[([^\[\]\n]+)\]",
                   lambda match: match[0] if match[1] in allowed_ids else "", text)
    return CitationValidation(clean.strip(), tuple(value for value in supplied if value in allowed_ids), invalid)
