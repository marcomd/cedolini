"""CCNL configuration loader and detector."""

import yaml
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from scripts.models import Cedolino

CONFIG_DIR = Path(__file__).parent.parent / "config" / "ccnl"


@dataclass
class ContributionRule:
    """Rule for validating a single contribution."""
    name: str = ""
    rate: Decimal = Decimal("0")
    type: str = "rate"  # "rate" or "fixed"
    amount: Decimal = Decimal("0")  # for fixed-type contributions
    tolerance: Decimal = Decimal("0.02")
    use_own_imponibile: bool = False
    aliases: list[str] = field(default_factory=list)


@dataclass
class CCNLConfig:
    """Configuration for a CCNL."""
    id: str = ""
    name: str = ""
    aliases: list[str] = field(default_factory=list)
    detect_patterns: list[str] = field(default_factory=list)
    contributions: list[ContributionRule] = field(default_factory=list)


def load_all_ccnl(config_dir: Path | None = None) -> dict[str, CCNLConfig]:
    """Load all CCNL YAML configs from the config directory.

    Returns a dict keyed by CCNL id (filename stem).
    """
    base = config_dir or CONFIG_DIR
    configs = {}
    if not base.exists():
        return configs

    for yaml_path in sorted(base.glob("*.yaml")):
        try:
            config = _load_yaml(yaml_path)
            configs[config.id] = config
        except Exception as e:
            print(f"  WARNING: Cannot load CCNL config {yaml_path}: {e}")

    return configs


def load_ccnl(name: str, config_dir: Path | None = None) -> CCNLConfig | None:
    """Load a specific CCNL config by id."""
    configs = load_all_ccnl(config_dir)
    return configs.get(name)


def detect_ccnl(cedolino: Cedolino, configs: dict[str, CCNLConfig]) -> CCNLConfig | None:
    """Detect CCNL from cedolino fields, matching against config patterns.

    Checks contratto and ragione_sociale against detect_patterns.
    """
    # If ccnl is already set on the cedolino, look it up directly
    if cedolino.ccnl:
        return configs.get(cedolino.ccnl)

    text_fields = [
        cedolino.contratto,
        cedolino.ragione_sociale,
    ]

    for ccnl_id, config in configs.items():
        for pattern in config.detect_patterns:
            pattern_lower = pattern.lower()
            for text in text_fields:
                if text and pattern_lower in text.lower():
                    return config

    return None


def _load_yaml(yaml_path: Path) -> CCNLConfig:
    """Load a single CCNL YAML file."""
    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    config = CCNLConfig(
        id=yaml_path.stem,
        name=data.get("name", ""),
        aliases=data.get("aliases", []),
        detect_patterns=data.get("detect_patterns", []),
    )

    for contrib_name, contrib_data in data.get("contributions", {}).items():
        rule = ContributionRule(name=contrib_name)
        rule.type = contrib_data.get("type", "rate")
        if "rate" in contrib_data:
            rule.rate = Decimal(str(contrib_data["rate"]))
        if "amount" in contrib_data:
            rule.amount = Decimal(str(contrib_data["amount"]))
        if "tolerance" in contrib_data:
            rule.tolerance = Decimal(str(contrib_data["tolerance"]))
        rule.use_own_imponibile = contrib_data.get("use_own_imponibile", False)
        rule.aliases = contrib_data.get("aliases", [])
        config.contributions.append(rule)

    return config
