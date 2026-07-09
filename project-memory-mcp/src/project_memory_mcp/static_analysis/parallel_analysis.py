"""Parallel analysis module for Project Memory MCP.

This module provides:
1. Dependency graph building via static analysis
2. Topological sorting for dependent files
3. Parallel processing for independent files
4. Integration with existing workflows
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Union

from project_memory_mcp.static_analysis.file_scanner import FileInfo, FileScanner
from project_memory_mcp.static_analysis.static_locator import StaticLocator

logger = logging.getLogger(__name__)


@dataclass
class FileDependency:
    """Represents a dependency between files."""
    source_file: str
    target_file: str
    dependency_type: str  # "import", "call", "inherit"
    confidence: float = 1.0


@dataclass
class AnalysisGroup:
    """A group of files that can be analyzed in parallel."""
    files: list[FileInfo]
    level: int  # Topological level (0 = no dependencies)
    dependencies: list[str] = field(default_factory=list)  # Files this group depends on


@dataclass
class ParallelAnalysisConfig:
    """Configuration for parallel analysis."""
    max_workers: int = 4
    max_llm_concurrent: int = 2
    batch_size: int = 10
    enable_parallel_static: bool = True
    enable_parallel_llm: bool = True


class DependencyGraphBuilder:
    """Builds a dependency graph from static analysis results."""

    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()
        self.locator = StaticLocator()
        self._file_imports: dict[str, list[str]] = {}
        self._file_calls: dict[str, list[str]] = {}
        self._file_symbols: dict[str, list[str]] = {}

    def build_from_files(self, file_infos: list[FileInfo]) -> dict[str, list[FileDependency]]:
        """Build dependency graph from a list of file infos."""
        dependencies: dict[str, list[FileDependency]] = {f.relative_path: [] for f in file_infos}

        # First pass: extract imports and symbols from all files
        for file_info in file_infos:
            if not file_info.is_source:
                continue

            try:
                analysis = self.locator.analyze_file(file_info.path)

                # Store imports
                imports = [imp.metadata.get("module", "") for imp in analysis.imports if imp.metadata.get("module")]
                self._file_imports[file_info.relative_path] = imports

                # Store symbols (qualified names)
                symbols = [func.qualified_name for func in analysis.functions if func.qualified_name]
                symbols += [cls.qualified_name for cls in analysis.classes if cls.qualified_name]
                self._file_symbols[file_info.relative_path] = symbols

                # Store calls
                calls = [call.metadata.get("function", "") for call in analysis.calls if call.metadata.get("function")]
                self._file_calls[file_info.relative_path] = calls

            except Exception as e:
                logger.error(f"Error analyzing {file_info.relative_path}: {e}")

        # Second pass: resolve dependencies
        path_to_info = {f.relative_path: f for f in file_infos}

        for file_info in file_infos:
            if not file_info.is_source:
                continue

            rel_path = file_info.relative_path
            deps = []

            # Resolve import dependencies
            for imp in self._file_imports.get(rel_path, []):
                target = self._resolve_import(imp, path_to_info)
                if target and target != rel_path:
                    deps.append(FileDependency(
                        source_file=rel_path,
                        target_file=target,
                        dependency_type="import",
                        confidence=0.9
                    ))

            # Resolve call dependencies (symbol -> file)
            for call in self._file_calls.get(rel_path, []):
                target = self._resolve_symbol_to_file(call, path_to_info)
                if target and target != rel_path:
                    deps.append(FileDependency(
                        source_file=rel_path,
                        target_file=target,
                        dependency_type="call",
                        confidence=0.7
                    ))

            dependencies[rel_path] = deps

        return dependencies

    def _resolve_import(self, import_name: str, path_to_info: dict[str, FileInfo]) -> str | None:
        """Resolve an import name to a file path."""
        # Try direct path match
        for path, info in path_to_info.items():
            if info.language == "python":
                # Python: convert path to module name
                module_path = path.replace("/", ".").replace(".py", "")
                if module_path == import_name or module_path.endswith("." + import_name):
                    return path
            elif info.language in ("typescript", "javascript"):
                # TypeScript/JS: check relative imports
                if import_name.startswith("."):
                    # Relative import - would need more context
                    pass

        return None

    def _resolve_symbol_to_file(self, symbol_name: str, path_to_info: dict[str, FileInfo]) -> str | None:
        """Resolve a symbol name to the file that defines it."""
        for path, symbols in self._file_symbols.items():
            if symbol_name in symbols:
                return path
        return None


class TopologicalSorter:
    """Performs topological sorting on file dependencies."""

    @staticmethod
    def sort(dependencies: dict[str, list[FileDependency]]) -> list[AnalysisGroup]:
        """Sort files into parallelizable groups using Kahn's algorithm."""
        # Build adjacency list and in-degree count
        graph: dict[str, list[str]] = {f: [] for f in dependencies}
        in_degree: dict[str, int] = {f: 0 for f in dependencies}

        for source, deps in dependencies.items():
            for dep in deps:
                if dep.target_file in graph:
                    graph[dep.target_file].append(source)
                    in_degree[source] += 1

        # Kahn's algorithm
        queue = [f for f in in_degree if in_degree[f] == 0]
        result: list[AnalysisGroup] = []
        level = 0

        while queue:
            current_level_files = queue[:]
            queue = []

            group = AnalysisGroup(
                files=[],  # Will be populated with FileInfo objects
                level=level,
                dependencies=[]
            )

            for file_path in current_level_files:
                group.files.append(file_path)
                group.dependencies = [d.target_file for d in dependencies[file_path] if d.target_file in dependencies]

                # Process outgoing edges
                for dependent in graph[file_path]:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        queue.append(dependent)

            result.append(group)
            level += 1

        # Check for cycles
        if any(in_degree[f] > 0 for f in in_degree):
            logger.warning("Cycle detected in dependency graph, some files may not be sorted correctly")

        return result


class ParallelStaticAnalyzer:
    """Performs parallel static analysis on files."""

    def __init__(self, config: ParallelAnalysisConfig):
        self.config = config
        self.locator = StaticLocator()
        self._executor = ThreadPoolExecutor(max_workers=config.max_workers)

    async def analyze_files_parallel(self, file_infos: list[FileInfo]) -> dict[str, Any]:
        """Analyze multiple files in parallel."""
        results = {}

        # Split into batches
        batches = [file_infos[i:i + self.config.batch_size]
                   for i in range(0, len(file_infos), self.config.batch_size)]

        for batch in batches:
            batch_results = await self._analyze_batch(batch)
            results.update(batch_results)

        return results

    async def _analyze_batch(self, file_infos: list[FileInfo]) -> dict[str, Any]:
        """Analyze a batch of files in parallel."""
        loop = asyncio.get_event_loop()

        tasks = [
            loop.run_in_executor(self._executor, self._analyze_single, file_info)
            for file_info in file_infos
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        batch_results = {}
        for file_info, result in zip(file_infos, results):
            if isinstance(result, Exception):
                logger.error(f"Error analyzing {file_info.relative_path}: {result}")
                batch_results[file_info.relative_path] = {"error": str(result)}
            else:
                batch_results[file_info.relative_path] = result

        return batch_results

    def _analyze_single(self, file_info: FileInfo) -> dict[str, Any]:
        """Analyze a single file (runs in thread pool)."""
        try:
            analysis = self.locator.analyze_file(file_info.path)
            return {
                "imports": [imp.metadata.get("module", "") for imp in analysis.imports],
                "functions": [
                    {
                        "name": func.name,
                        "qualified_name": func.qualified_name,
                        "signature": func.metadata.get("parameters", ""),
                        "docstring": func.metadata.get("docstring", ""),
                        "start_line": func.start_line,
                        "end_line": func.end_line,
                    }
                    for func in analysis.functions
                ],
                "classes": [
                    {
                        "name": cls.name,
                        "qualified_name": cls.qualified_name,
                        "docstring": cls.metadata.get("docstring", ""),
                        "start_line": cls.start_line,
                        "end_line": cls.end_line,
                    }
                    for cls in analysis.classes
                ],
                "calls": [call.metadata.get("function", "") for call in analysis.calls],
                "variables": [var.name for var in analysis.variables],
                "errors": analysis.errors,
            }
        except Exception as e:
            return {"error": str(e)}

    def shutdown(self):
        """Shutdown the thread pool."""
        self._executor.shutdown(wait=True)


class ParallelLLMAnalyzer:
    """Performs parallel LLM analysis with dependency awareness."""

    def __init__(self, config: ParallelAnalysisConfig):
        self.config = config
        self._semaphore = asyncio.Semaphore(config.max_llm_concurrent)

    async def analyze_files_by_groups(
        self,
        groups: list[AnalysisGroup],
        file_infos_map: dict[str, FileInfo],
        analyze_func: callable,
    ) -> dict[str, Any]:
        """Analyze files group by group (respecting dependencies)."""
        results = {}

        for group in groups:
            logger.info(f"Processing analysis group level {group.level} with {len(group.files)} files")

            # Process files in this group in parallel
            group_results = await self._analyze_group_parallel(
                group.files,
                file_infos_map,
                analyze_func,
            )
            results.update(group_results)

        return results

    async def _analyze_group_parallel(
        self,
        file_paths: list[str],
        file_infos_map: dict[str, FileInfo],
        analyze_func: callable,
    ) -> dict[str, Any]:
        """Analyze a group of independent files in parallel."""
        async def analyze_with_semaphore(file_path: str):
            async with self._semaphore:
                file_info = file_infos_map.get(file_path)
                if file_info:
                    return await analyze_func(file_info)
                return {"error": "File not found"}

        tasks = [analyze_with_semaphore(fp) for fp in file_paths]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        group_results = {}
        for file_path, result in zip(file_paths, results):
            if isinstance(result, Exception):
                logger.error(f"Error in LLM analysis for {file_path}: {result}")
                group_results[file_path] = {"error": str(result)}
            else:
                group_results[file_path] = result

        return group_results


class ParallelAnalysisOrchestrator:
    """Orchestrates the complete parallel analysis pipeline."""

    def __init__(
        self,
        project_root: str,
        config: ParallelAnalysisConfig | None = None,
    ):
        self.project_root = project_root
        self.config = config or ParallelAnalysisConfig()
        self.scanner = FileScanner(project_root)
        self.dep_builder = DependencyGraphBuilder(project_root)
        self.static_analyzer = ParallelStaticAnalyzer(self.config)
        self.llm_analyzer = ParallelLLMAnalyzer(self.config)

    async def run_full_analysis(
        self,
        analyze_file_func: Callable[..., Any] | None = None,
    ) -> dict[str, Any]:
        """Run the complete parallel analysis pipeline."""
        results = {
            "files_scanned": 0,
            "static_analysis": {},
            "llm_analysis": {},
            "dependency_graph": {},
            "groups": [],
            "errors": [],
        }

        # Step 1: Scan files
        logger.info("Step 1: Scanning files...")
        file_infos = self.scanner.scan()
        results["files_scanned"] = len(file_infos)

        # Step 2: Build dependency graph
        logger.info("Step 2: Building dependency graph...")
        dependencies = self.dep_builder.build_from_files(file_infos)
        results["dependency_graph"] = {
            k: [{"source": d.source_file, "target": d.target_file, "type": d.dependency_type}
                for d in v]
            for k, v in dependencies.items()
        }

        # Step 3: Topological sort
        logger.info("Step 3: Topological sorting...")
        groups = TopologicalSorter.sort(dependencies)
        results["groups"] = [
            {"level": g.level, "files": g.files, "dependencies": g.dependencies}
            for g in groups
        ]

        # Step 4: Parallel static analysis
        if self.config.enable_parallel_static:
            logger.info("Step 4: Running parallel static analysis...")
            static_results = await self.static_analyzer.analyze_files_parallel(file_infos)
            results["static_analysis"] = static_results
        else:
            # Sequential fallback
            results["static_analysis"] = {}
            for f in file_infos:
                results["static_analysis"][f.relative_path] = self.static_analyzer._analyze_single(f)

        # Step 5: Parallel LLM analysis (if function provided)
        if analyze_file_func and self.config.enable_parallel_llm:
            logger.info("Step 5: Running parallel LLM analysis...")
            file_map = {f.relative_path: f for f in file_infos}
            llm_results = await self.llm_analyzer.analyze_files_by_groups(
                groups, file_map, analyze_file_func
            )
            results["llm_analysis"] = llm_results
        elif analyze_file_func:
            # Sequential fallback
            results["llm_analysis"] = {}
            for f in file_infos:
                results["llm_analysis"][f.relative_path] = await analyze_file_func(f)

        # Cleanup
        self.static_analyzer.shutdown()

        return results


def create_parallel_analysis_config(
    max_workers: int = 4,
    max_llm_concurrent: int = 2,
    batch_size: int = 10,
    enable_parallel_static: bool = True,
    enable_parallel_llm: bool = True,
) -> ParallelAnalysisConfig:
    """Create a parallel analysis configuration."""
    return ParallelAnalysisConfig(
        max_workers=max_workers,
        max_llm_concurrent=max_llm_concurrent,
        batch_size=batch_size,
        enable_parallel_static=enable_parallel_static,
        enable_parallel_llm=enable_parallel_llm,
    )


async def run_parallel_indexing(
    project_path: str,
    config: ParallelAnalysisConfig | None = None,
    llm_analyze_func: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Convenience function to run parallel indexing."""
    orchestrator = ParallelAnalysisOrchestrator(project_path, config)
    return await orchestrator.run_full_analysis(llm_analyze_func)