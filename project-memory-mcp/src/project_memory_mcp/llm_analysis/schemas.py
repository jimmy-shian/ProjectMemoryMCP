"""Pydantic schemas for LLM analysis results."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AnalysisStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    VERIFIED = "verified"


class FilePurpose(str, Enum):
    ENTRYPOINT = "entrypoint"
    CORE_LOGIC = "core_logic"
    UTILITY = "utility"
    CONFIGURATION = "configuration"
    TEST = "test"
    DATA_MODEL = "data_model"
    API_INTERFACE = "api_interface"
    UNKNOWN = "unknown"


class SymbolRole(str, Enum):
    MAIN_LOGIC = "main_logic"
    HELPER = "helper"
    DATA_ACCESS = "data_access"
    BUSINESS_RULE = "business_rule"
    VALIDATION = "validation"
    TRANSFORMATION = "transformation"
    CONTROL_FLOW = "control_flow"
    UNKNOWN = "unknown"


class EquationCategory(str, Enum):
    CONTROL = "control"
    LOSS = "loss"
    MATRIX = "matrix"
    OPTIMIZATION = "optimization"
    STATISTICAL = "statistical"
    PHYSICS = "physics"
    MATHEMATICAL = "mathematical"
    ALGORITHMIC = "algorithmic"
    NEURAL_NETWORK = "neural_network"
    UNKNOWN = "unknown"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class VariableRole(str, Enum):
    INPUT = "input"
    OUTPUT = "output"
    STATE = "state"
    PARAMETER = "parameter"
    CONSTANT = "constant"
    INTERMEDIATE = "intermediate"
    CONFIGURATION = "configuration"
    UNKNOWN = "unknown"


# Input context for LLM analysis
class FileContext(BaseModel):
    """Context provided to LLM for file analysis."""
    file_path: str
    language: str
    source_code: str
    imports: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)  # Symbol names in this file


class SymbolContext(BaseModel):
    """Context provided to LLM for symbol analysis."""
    file_path: str
    language: str
    symbol_name: str
    symbol_type: str
    source_code: str
    signature: str | None = None
    docstring: str | None = None
    parent_class: str | None = None
    called_functions: list[str] = Field(default_factory=list)
    calling_functions: list[str] = Field(default_factory=list)


class EquationContext(BaseModel):
    """Context provided to LLM for equation analysis."""
    file_path: str
    language: str
    equation_name: str | None
    expression: str
    surrounding_code: str
    variables_in_scope: list[str] = Field(default_factory=list)
    containing_function: str | None = None
    containing_class: str | None = None


# LLM Output schemas
class FileAnalysisResult(BaseModel):
    """Result of file-level LLM analysis."""
    purpose: FilePurpose = FilePurpose.UNKNOWN
    summary: str = Field(..., description="Concise summary of what this file does")
    is_core: bool = Field(default=False, description="Whether this is a core file")
    key_concepts: list[str] = Field(default_factory=list, description="Key domain concepts in this file")
    risk_notes: list[str] = Field(default_factory=list, description="Potential risks or issues")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in this analysis (0-1)")
    suggested_queries: list[str] = Field(default_factory=list, description="Suggested queries for this file")


class SymbolAnalysisResult(BaseModel):
    """Result of symbol-level LLM analysis."""
    responsibility: str = Field(..., description="What this symbol is responsible for")
    role: SymbolRole = SymbolRole.UNKNOWN
    side_effects: list[str] = Field(default_factory=list, description="Side effects (IO, mutations, etc.)")
    preconditions: list[str] = Field(default_factory=list, description="Preconditions for calling")
    postconditions: list[str] = Field(default_factory=list, description="Postconditions after calling")
    complexity: str = Field(default="unknown", description="Complexity assessment: low/medium/high")
    confidence: float = Field(..., ge=0.0, le=1.0)
    related_equations: list[str] = Field(default_factory=list, description="Equation names used by this symbol")
    data_flow: dict[str, str] = Field(default_factory=dict, description="Input/output data flow description")


class EquationAnalysisResult(BaseModel):
    """Result of equation-level LLM analysis."""
    equation_type: EquationCategory = EquationCategory.UNKNOWN
    name: str | None = Field(default=None, description="Human-readable name for this equation")
    mathematical_meaning: str = Field(..., description="Mathematical meaning of the equation")
    physical_meaning: str | None = Field(default=None, description="Physical interpretation if applicable")
    algorithmic_role: str = Field(..., description="Role in the algorithm (e.g., 'PID control law', 'loss function')")
    inputs: list[str] = Field(default_factory=list, description="Input variable names")
    outputs: list[str] = Field(default_factory=list, description="Output variable names")
    intermediate_variables: list[str] = Field(default_factory=list, description="Intermediate variable names")
    constants: list[str] = Field(default_factory=list, description="Constant names")
    units: dict[str, str] = Field(default_factory=dict, description="Variable -> unit mapping")
    assumptions: list[str] = Field(default_factory=list, description="Mathematical/physical assumptions")
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: str = Field(..., description="Source code snippet that contains this equation")


class VariableAnalysisResult(BaseModel):
    """Result of variable-level LLM analysis."""
    role: VariableRole = VariableRole.UNKNOWN
    inferred_meaning: str = Field(..., description="What this variable represents")
    unit: str | None = Field(default=None, description="Physical unit if applicable")
    shape: str | None = Field(default=None, description="Shape for tensors/arrays (e.g., [batch, seq, hidden])")
    confidence: float = Field(..., ge=0.0, le=1.0)


class DependencyAnalysisResult(BaseModel):
    """Result of dependency analysis."""
    depends_on: list[str] = Field(default_factory=list, description="Symbols/files this depends on")
    affects: list[str] = Field(default_factory=list, description="Symbols/files this affects")
    data_flow_edges: list[dict[str, str]] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)


class ImpactAnalysisResult(BaseModel):
    """Result of impact analysis for proposed changes."""
    affected_files: list[str] = Field(default_factory=list)
    affected_symbols: list[str] = Field(default_factory=list)
    affected_equations: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    risk_summary: str = Field(..., description="Summary of risks")
    suggested_test_files: list[str] = Field(default_factory=list)
    suggested_order: list[str] = Field(default_factory=list, description="Suggested order of modifications")
    confidence: float = Field(..., ge=0.0, le=1.0)


class DeleteSafetyResult(BaseModel):
    """Result of delete safety analysis."""
    can_delete: bool = Field(..., description="Whether it's safe to delete")
    risk_level: RiskLevel = RiskLevel.LOW
    references: list[str] = Field(default_factory=list, description="What references this")
    dependents: list[str] = Field(default_factory=list, description="What depends on this")
    orphaned_code: list[str] = Field(default_factory=list, description="Code that would become orphaned")
    recommendation: str = Field(..., description="Recommendation for deletion")
    confidence: float = Field(..., ge=0.0, le=1.0)


# Task and result containers
class AnalysisTask(BaseModel):
    """A task for LLM analysis."""
    task_id: str
    task_type: str  # file, symbol, equation, variable, dependency
    target_path: str
    target_name: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    schema_class: str  # Name of the schema class to use for output


class AnalysisResult(BaseModel):
    """Result of an LLM analysis task."""
    task_id: str
    task_type: str
    target_path: str
    target_name: str | None = None
    result: dict[str, Any]  # The actual analysis result (validated against schema)
    status: AnalysisStatus = AnalysisStatus.COMPLETED
    confidence: float = Field(..., ge=0.0, le=1.0)
    model_used: str = Field(default="unknown")
    prompt_version: str = Field(default="1.0")
    error: str | None = None


# Prompt templates
class PromptTemplate(BaseModel):
    """A prompt template for LLM analysis."""
    name: str
    version: str
    description: str
    system_prompt: str
    user_prompt_template: str
    output_schema: str  # Schema class name
    examples: list[dict[str, Any]] = Field(default_factory=list)


# Built-in prompt templates
BUILTIN_PROMPTS = {
    "analyze_file": PromptTemplate(
        name="analyze_file",
        version="1.0",
        description="Analyze a source file to understand its purpose and structure",
        system_prompt="""You are an expert software engineer analyzing source code for a knowledge graph system.
Your task is to understand the purpose, structure, and key concepts of the given file.
Return a structured analysis following the provided JSON schema.

Focus on:
1. What is the main purpose of this file?
2. Is it a core file (central to the system) or peripheral?
3. What domain concepts does it deal with?
4. Are there any risks or issues?
5. What queries would be useful for someone exploring this codebase?""",
        user_prompt_template="""Analyze the following {language} file:

**File:** {file_path}
**Language:** {language}

**Source Code:**
```{language}
{source_code}
```

**Imports found:** {imports}
**Symbols found:** {symbols}

Provide your analysis as JSON matching the schema.""",
        output_schema="FileAnalysisResult",
    ),
    "analyze_symbol": PromptTemplate(
        name="analyze_symbol",
        version="1.0",
        description="Analyze a function, class, or method to understand its responsibility",
        system_prompt="""You are an expert software engineer analyzing a specific code symbol (function, class, method, etc.).
Your task is to understand its responsibility, behavior, and relationships.
Return a structured analysis following the provided JSON schema.

Focus on:
1. What is this symbol's single responsibility?
2. What side effects does it have?
3. What are its preconditions and postconditions?
4. What equations or algorithms does it use?
5. What is its complexity level?""",
        user_prompt_template="""Analyze the following symbol in {language}:

**File:** {file_path}
**Symbol:** {symbol_name} ({symbol_type})
**Signature:** {signature}
**Docstring:** {docstring}
**Parent Class:** {parent_class}

**Source Code:**
```{language}
{source_code}
```

**Called Functions:** {called_functions}
**Calling Functions:** {calling_functions}

Provide your analysis as JSON matching the schema.""",
        output_schema="SymbolAnalysisResult",
    ),
    "analyze_equation": PromptTemplate(
        name="analyze_equation",
        version="1.0",
        description="Analyze a mathematical equation/formula in code",
        system_prompt="""You are an expert in mathematical modeling and scientific computing analyzing equations in source code.
Your task is to identify the mathematical meaning, physical interpretation, and algorithmic role of the equation.
Return a structured analysis following the provided JSON schema.

Focus on:
1. What type of equation is this? (control, loss, matrix, optimization, etc.)
2. What is the mathematical formula/meaning?
3. What are the inputs, outputs, and intermediate variables?
4. What are the units and physical interpretation?
5. What assumptions does this equation make?
6. What is its role in the algorithm?""",
        user_prompt_template="""Analyze the following equation in {language} code:

**File:** {file_path}
**Equation Name:** {equation_name}
**Containing Function:** {containing_function}
**Containing Class:** {containing_class}

**Equation Expression:**
```
{expression}
```

**Surrounding Code Context:**
```{language}
{surrounding_code}
```

**Variables in Scope:** {variables_in_scope}

Provide your analysis as JSON matching the schema. Be precise about variable names, mathematical meaning, and algorithmic role.""",
        output_schema="EquationAnalysisResult",
    ),
    "analyze_variable": PromptTemplate(
        name="analyze_variable",
        version="1.0",
        description="Analyze a variable to understand its role and meaning",
        system_prompt="""You are an expert software engineer analyzing a variable in source code.
Your task is to understand what the variable represents, its role, and its characteristics.
Return a structured analysis following the provided JSON schema.""",
        user_prompt_template="""Analyze the following variable in {language}:

**File:** {file_path}
**Variable Name:** {variable_name}
**Context:**
```{language}
{surrounding_code}
```

Provide your analysis as JSON matching the schema.""",
        output_schema="VariableAnalysisResult",
    ),
    "impact_analysis": PromptTemplate(
        name="impact_analysis",
        version="1.0",
        description="Analyze the impact of a proposed change",
        system_prompt="""You are an expert software engineer performing impact analysis for a proposed code change.
Your task is to identify what files, symbols, and equations would be affected, and assess the risk level.
Return a structured analysis following the provided JSON schema.

Consider:
1. Direct dependencies (what calls/uses the target)
2. Transitive dependencies
3. Test files that might need updates
4. Risk level based on coupling and criticality
5. Suggested order of modifications to minimize risk""",
        user_prompt_template="""Perform impact analysis for modifying {target_type} "{target_name}":

**Target Type:** {target_type} (file/symbol/equation)
**Target Name:** {target_name}
**Target Location:** {target_path}

**Direct Dependencies (callers/users):**
{dependencies}

**Transitive Dependencies:**
{transitive_dependencies}

**Related Tests:**
{test_files}

**Operation Type:** {operation_type} (modify/delete/refactor)

Provide your analysis as JSON matching the schema.""",
        output_schema="ImpactAnalysisResult",
    ),
    "delete_safety": PromptTemplate(
        name="delete_safety",
        version="1.0",
        description="Analyze safety of deleting a file, symbol, or equation",
        system_prompt="""You are an expert software engineer analyzing the safety of deleting code.
Your task is to identify all references, dependents, and potential issues from deletion.
Return a structured analysis following the provided JSON schema.

Consider:
1. Direct references (what imports/calls/uses this)
2. Transitive dependents
3. Code that would become orphaned/unreachable
4. Test files that test this
5. Configuration that references this""",
        user_prompt_template="""Analyze delete safety for {target_type} "{target_name}":

**Target Type:** {target_type}
**Target Name:** {target_name}
**Target Location:** {target_path}

**Direct References:**
{references}

**Dependents (what depends on this):**
{dependents}

**Test Files:**
{test_files}

**Configuration References:**
{config_references}

Provide your analysis as JSON matching the schema.""",
        output_schema="DeleteSafetyResult",
    ),
}
