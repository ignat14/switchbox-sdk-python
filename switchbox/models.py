from dataclasses import dataclass, field
from typing import Any


@dataclass
class Rule:
    attribute: str
    operator: str  # equals | not_equals | contains | ends_with | in_list | gt | lt
    value: Any


@dataclass
class Flag:
    key: str
    enabled: bool
    rollout_pct: int
    flag_type: str  # boolean | string | number | json
    default_value: Any
    rules: list[Rule] = field(default_factory=list)


@dataclass
class FlagConfig:
    version: str  # ISO timestamp
    flags: dict[str, Flag] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> FlagConfig:
        """Parse the CDN JSON into a FlagConfig object."""
        flags = {}
        for key, flag_data in data.get("flags", {}).items():
            rules = [
                Rule(
                    attribute=r["attribute"],
                    operator=r["operator"],
                    value=r["value"],
                )
                for r in flag_data.get("rules", [])
            ]
            flags[key] = Flag(
                key=key,
                enabled=flag_data["enabled"],
                rollout_pct=flag_data.get("rollout_pct", 0),
                flag_type=flag_data.get("flag_type", "boolean"),
                default_value=flag_data.get("default_value"),
                rules=rules,
            )
        return cls(version=data.get("version", ""), flags=flags)
