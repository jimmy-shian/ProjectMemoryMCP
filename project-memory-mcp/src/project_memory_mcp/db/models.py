"""SQLAlchemy models for Project Memory Knowledge Graph."""

from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class FileType(PyEnum):
    """File type classification."""
    SOURCE = "source"
    TEST = "test"
    CONFIG = "config"
    ENTRYPOINT = "entrypoint"
    DOCUMENTATION = "documentation"
    DATA = "data"
    OTHER = "other"


class SymbolType(PyEnum):
    """Symbol type classification."""
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    VARIABLE = "variable"
    CONSTANT = "constant"
    PARAMETER = "parameter"
    IMPORT = "import"
    TYPE_ALIAS = "type_alias"
    ENUM = "enum"
    INTERFACE = "interface"
    TRAIT = "trait"
    STRUCT = "struct"
    UNKNOWN = "unknown"


class EquationType(PyEnum):
    """Equation type classification."""
    CONTROL = "control"           # PID, state-space, etc.
    LOSS = "loss"                 # Loss functions
    MATRIX = "matrix"             # Matrix operations
    OPTIMIZATION = "optimization" # Gradient descent, etc.
    STATISTICAL = "statistical"   # Statistical formulas
    PHYSICS = "physics"           # Physical equations
    MATHEMATICAL = "mathematical" # Pure math formulas
    ALGORITHMIC = "algorithmic"   # Algorithm pseudocode
    NEURAL_NETWORK = "neural_network"  # NN layers, activations
    UNKNOWN = "unknown"


class EdgeType(PyEnum):
    """Graph edge type classification."""
    CONTAINS = "contains"
    IMPORTS = "imports"
    IMPORTED_BY = "imported_by"
    DEFINES = "defines"
    DEFINED_IN = "defined_in"
    CALLS = "calls"
    CALLED_BY = "called_by"
    READS = "reads"
    WRITES = "writes"
    MODIFIES = "modifies"
    USES = "uses"
    RETURNS = "returns"
    DEPENDS_ON = "depends_on"
    AFFECTS = "affects"
    TESTS = "tests"
    TESTED_BY = "tested_by"
    CONFIGURES = "configures"
    CONFIGURED_BY = "configured_by"
    IMPLEMENTS = "implements"
    INHERITS = "inherits"
    OVERRIDES = "overrides"
    USES_EQUATION = "uses_equation"
    EQUATION_INPUT = "equation_input"
    EQUATION_OUTPUT = "equation_output"
    EQUATION_INTERMEDIATE = "equation_intermediate"
    EQUATION_DEPENDS_ON = "equation_depends_on"
    HAS_ASSUMPTION = "has_assumption"
    HAS_RISK = "has_risk"
    DOCUMENTS = "documents"
    UPDATED_BY_OPERATION = "updated_by_operation"


class AnalysisStatus(PyEnum):
    """LLM analysis status."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    VERIFIED = "verified"


class OperationType(PyEnum):
    """Operation type for history tracking."""
    INDEX = "index"
    RESCAN = "rescan"
    ANALYZE_FILE = "analyze_file"
    ANALYZE_SYMBOL = "analyze_symbol"
    ANALYZE_EQUATION = "analyze_equation"
    EDIT = "edit"
    DELETE = "delete"
    IMPACT_ANALYSIS = "impact_analysis"
    GENERATE_MANUAL = "generate_manual"


class File(Base):
    """Source file metadata."""
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(String(500), unique=True, nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    extension: Mapped[str | None] = mapped_column(String(50), nullable=True)
    language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    file_type: Mapped[str] = mapped_column(String(50), default=FileType.OTHER.value)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    last_modified: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_source: Mapped[bool] = mapped_column(default=False)
    is_test: Mapped[bool] = mapped_column(default=False)
    is_config: Mapped[bool] = mapped_column(default=False)
    is_entrypoint: Mapped[bool] = mapped_column(default=False)
    is_core: Mapped[bool] = mapped_column(default=False)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    analysis_status: Mapped[str] = mapped_column(
        String(50), default=AnalysisStatus.PENDING.value
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    symbols: Mapped[list["Symbol"]] = relationship(
        "Symbol", back_populates="file", cascade="all, delete-orphan"
    )
    equations: Mapped[list["Equation"]] = relationship(
        "Equation", back_populates="file", cascade="all, delete-orphan"
    )
    variables: Mapped[list["Variable"]] = relationship(
        "Variable", back_populates="file", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_files_language_type", "language", "file_type"),
        Index("ix_files_hash_modified", "hash", "last_modified"),
    )


class Symbol(Base):
    """Code symbol (function, class, variable, etc.)."""
    __tablename__ = "symbols"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_symbol_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("symbols.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    qualified_name: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    symbol_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    visibility: Mapped[str | None] = mapped_column(String(50), nullable=True)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    start_byte: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_byte: Mapped[int | None] = mapped_column(Integer, nullable=True)
    docstring: Mapped[str | None] = mapped_column(Text, nullable=True)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    responsibility: Mapped[str | None] = mapped_column(Text, nullable=True)
    side_effects: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    file: Mapped["File"] = relationship("File", back_populates="symbols")
    parent: Mapped[Optional["Symbol"]] = relationship(
        "Symbol", back_populates="children", remote_side="Symbol.id"
    )
    children: Mapped[list["Symbol"]] = relationship(
        "Symbol", back_populates="parent", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_symbols_file_type", "file_id", "symbol_type"),
        Index("ix_symbols_qualified_name", "qualified_name"),
        Index("ix_symbols_name_type", "name", "symbol_type"),
    )


class Equation(Base):
    """Mathematical equation or formula."""
    __tablename__ = "equations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("symbols.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    equation_type: Mapped[str] = mapped_column(
        String(50), default=EquationType.UNKNOWN.value, index=True
    )
    expression: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_expression: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    start_byte: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_byte: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inputs_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array of input vars
    outputs_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array of output vars
    intermediate_variables_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    constants_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    units_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    mathematical_meaning: Mapped[str | None] = mapped_column(Text, nullable=True)
    physical_meaning: Mapped[str | None] = mapped_column(Text, nullable=True)
    algorithmic_role: Mapped[str | None] = mapped_column(Text, nullable=True)
    assumptions: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    inferred: Mapped[bool] = mapped_column(default=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)  # Source code snippet
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    file: Mapped["File"] = relationship("File", back_populates="equations")
    symbol: Mapped[Optional["Symbol"]] = relationship("Symbol")

    __table_args__ = (
        Index("ix_equations_file_type", "file_id", "equation_type"),
        Index("ix_equations_name_type", "name", "equation_type"),
    )


class Variable(Base):
    """Variable or constant in code."""
    __tablename__ = "variables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=True, index=True
    )
    symbol_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("symbols.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    variable_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    role: Mapped[str | None] = mapped_column(String(100), nullable=True)  # input, output, state, param, constant
    inferred_meaning: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    shape: Mapped[str | None] = mapped_column(String(100), nullable=True)  # For tensors/arrays
    initial_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    read_locations_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    write_locations_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    file: Mapped[Optional["File"]] = relationship("File", back_populates="variables")
    symbol: Mapped[Optional["Symbol"]] = relationship("Symbol")

    __table_args__ = (
        Index("ix_variables_file_name", "file_id", "name"),
        Index("ix_variables_symbol_name", "symbol_id", "name"),
    )


class GraphEdge(Base):
    """Graph edge connecting nodes in the knowledge graph."""
    __tablename__ = "graph_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    edge_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_edges_source", "source_type", "source_id"),
        Index("ix_edges_target", "target_type", "target_id"),
        Index("ix_edges_type", "edge_type"),
        UniqueConstraint(
            "source_type", "source_id", "target_type", "target_id", "edge_type",
            name="uq_edge_unique"
        ),
    )


class LLMAnalysisRecord(Base):
    """Record of LLM analysis performed on code elements."""
    __tablename__ = "llm_analysis_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # file, symbol, equation
    target_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    prompt_name: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    input_context_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_json: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), default=AnalysisStatus.PENDING.value
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_llm_analysis_target", "target_type", "target_id"),
        Index("ix_llm_analysis_model", "model_name"),
    )


class OperationsHistory(Base):
    """History of operations performed on the knowledge graph."""
    __tablename__ = "operations_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False, index=True
    )
    operation_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    user_request: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    affected_files_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    affected_symbols_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    affected_equations_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_hashes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_hashes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    impact_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_operations_timestamp", "timestamp"),
        Index("ix_operations_type", "operation_type"),
    )


class ManualEntry(Base):
    """Entry in the PROJECT_AGENT_MANUAL."""
    __tablename__ = "manual_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    section: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    order: Mapped[int] = mapped_column(Integer, default=0)
    file_paths_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # Related files
    symbol_names_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # Related symbols
    equation_names_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # Related equations
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_manual_section_order", "section", "order"),
    )


class UnresolvedItem(Base):
    """Items that couldn't be resolved during analysis."""
    __tablename__ = "unresolved_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # import, call, type, symbol
    source_file_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("files.id", ondelete="SET NULL"), nullable=True
    )
    source_symbol_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("symbols.id", ondelete="SET NULL"), nullable=True
    )
    target_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    target_module: Mapped[str | None] = mapped_column(String(500), nullable=True)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    resolved: Mapped[bool] = mapped_column(default=False)
    resolved_target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolved_target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_unresolved_type_name", "item_type", "target_name"),
        Index("ix_unresolved_source", "source_file_id", "source_symbol_id"),
    )


class ProjectConfig(Base):
    """Project-specific configuration stored in the database."""
    __tablename__ = "project_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
