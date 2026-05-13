"""Pydantic schema for SnakeMake docking workflow configuration.

Validates docking_config.yml to catch errors early (before Snakemake DAG build).
"""
from pathlib import Path
from typing import Literal, Optional

try:
    from pydantic import BaseModel, Field, field_validator, ValidationError
    _HAVE_PYDANTIC = True
except ImportError:
    _HAVE_PYDANTIC = False

    class BaseModel:  # type: ignore
        pass

    class Field:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass

    class ValidationError(Exception):  # type: ignore
        pass

    def field_validator(*args, **kwargs):
        def decorator(func):
            return func
        return decorator


class ReceptorConfig(BaseModel):
    id: str = Field(..., min_length=4, max_length=12,
                    description="PDB ID (4 chars) or UniProt/structure identifier")

    @field_validator('id')
    @classmethod
    def id_must_be_alphanumeric(cls, v: str) -> str:
        if not v.replace('_', '').replace('-', '').isalnum():
            raise ValueError('receptor.id must be alphanumeric (allow _ -)')
        return v


class LigandLibraryConfig(BaseModel):
    path: str = Field(..., description="Path to ligand CSV/TSV library")
    name_column: str = Field(default="compound",
                              description="Column name for compound identifiers")
    smiles_column: Optional[str] = Field(default="smiles",
                                          description="Column name for SMILES strings")
    max_count: int = Field(default=100, ge=1, le=10000,
                           description="Max number of ligands to dock")

    @field_validator('path')
    @classmethod
    def path_must_exist(cls, v: str) -> str:
        if not Path(v).exists():
            raise ValueError(f'ligand_library.path does not exist: {v}')
        return v


class DockingParamsConfig(BaseModel):
    center: list[float] = Field(..., min_length=3, max_length=3,
                                 description="Grid box center (x, y, z) in Angstroms")
    box_size: list[float] = Field(..., min_length=3, max_length=3,
                                   description="Grid box size (x, y, z) in Angstroms")
    exhaustiveness: int = Field(default=32, ge=1, le=64,
                                 description="Vina Monte Carlo sampling depth")
    n_poses: int = Field(default=10, ge=1, le=50,
                          description="Number of poses to generate per ligand")
    seed: Optional[int] = Field(default=None,
                                 description="Random seed (None = random)")

    @field_validator('center', 'box_size')
    @classmethod
    def coords_must_be_numeric(cls, v: list) -> list:
        if not all(isinstance(x, (int, float)) for x in v):
            raise ValueError('center/box_size must be numeric [x, y, z]')
        return v

    @field_validator('box_size')
    @classmethod
    def box_size_positive(cls, v: list) -> list:
        if any(x <= 0 for x in v):
            raise ValueError('box_size values must be positive')
        return v


class PostDockConfig(BaseModel):
    mmpbsa: bool = Field(default=False,
                          description="Run MM/PBSA re-scoring after docking")
    mmpbsa_method: Literal['gb', 'pb'] = Field(default='gb',
                                                description="MM/PBSA method")
    amber_protocol: Literal['quick', 'short', 'medium', 'full'] = Field(
        default='quick',
        description="Amber MD protocol length")
    render_2d: bool = Field(default=True,
                             description="Generate 2D interaction diagrams")
    top_n: int = Field(default=20, ge=1, le=500,
                        description="Number of top hits to analyze post-dock")


class DockingConfig(BaseModel):
    receptor: ReceptorConfig
    ligand_library: LigandLibraryConfig
    docking: DockingParamsConfig
    post_dock: PostDockConfig = Field(default_factory=PostDockConfig)


def validate_config(config: dict) -> dict:
    """Validate raw config dict and return validated dict.

    Raises:
        ValueError: If validation fails (with human-readable message).
    """
    if not _HAVE_PYDANTIC:
        # Pydantic not installed — skip validation with warning
        import warnings
        warnings.warn("pydantic not installed; skipping config validation. "
                      "Install with: pip install pydantic")
        return config

    try:
        validated = DockingConfig(**config)
        return validated.model_dump()
    except ValidationError as e:
        # Format pydantic errors into human-readable lines
        lines = [" docking_config.yml validation failed:"]
        for err in e.errors():
            loc = ' -> '.join(str(x) for x in err['loc'])
            lines.append(f"   [{loc}] {err['msg']}")
        raise ValueError('\n'.join(lines))
