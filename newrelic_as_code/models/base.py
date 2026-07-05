"""
Serialization foundation for the model tree.

Every model renders to the JSON shape NerdGraph expects. Two concerns recur
everywhere and are handled here so the per-model classes stay declarative:

- **camelCase.** We write Pythonic ``snake_case`` fields but NerdGraph JSON is
  ``camelCase`` (``yAxisLeft``, ``nrqlQueries``, ...). ``NrModel.as_nr_dict()``
  aliases automatically, so no per-field alias noise.
- **raw escape hatch.** ``rawConfiguration`` is an untyped scalar in NerdGraph
  (New Relic validates it server-side, but its full shape is only de-facto
  known). We model the keys we know as typed fields, but every config also
  accepts a ``raw`` dict that is merged over the typed output — so a valid but
  unmodeled key is always expressable and the type system is never *wrong*.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict


def _snake_to_camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(word.capitalize() for word in tail)


class NrModel(BaseModel):
    """Base for every model that serializes to NerdGraph JSON.

    ``as_nr_dict()`` emits camelCased keys and drops ``None`` values (NerdGraph
    treats an absent key and a null key differently for some inputs; omitting
    keeps payloads minimal and matches what the UI produces).
    """

    model_config = ConfigDict(populate_by_name=True)

    def as_nr_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, value in self:
            if value is None:
                continue
            result[_snake_to_camel(name)] = _render(value)
        return result


class NrConfigModel(NrModel):
    """Base for ``rawConfiguration`` config models — adds the raw escape hatch.

    ``raw`` is merged over the typed fields, so callers can set any key we don't
    model yet (or override one we do). Typed fields win only where ``raw`` is
    silent; ``raw`` always takes precedence on conflict, since it is the explicit
    override.
    """

    raw: dict[str, Any] = {}

    def as_nr_dict(self) -> dict[str, Any]:
        result = {k: v for k, v in super().as_nr_dict().items() if k != "raw"}
        result.update(self.raw)
        return result


def _render(value: Any) -> Any:
    """Recursively render nested models / collections to plain JSON values."""
    if isinstance(value, NrModel):
        return value.as_nr_dict()
    if isinstance(value, list):
        return [_render(v) for v in value]
    if isinstance(value, dict):
        return {k: _render(v) for k, v in value.items()}
    return value
