"""The models package stays content-neutral and dependency-free."""

import ast
import sys
from pathlib import Path

import pytest

import muteinous.models as models


@pytest.mark.portable
def test_models_imports_are_stdlib_or_within_models_package() -> None:
    package_dir = Path(models.__file__).parent
    violations: list[str] = []

    for path in sorted(package_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative_parts = path.relative_to(package_dir).with_suffix("").parts
        package_parts = relative_parts[:-1]
        current_package = ".".join(("muteinous", "models", *package_parts))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base_parts = current_package.split(".")
                    base_parts = base_parts[: max(0, len(base_parts) - node.level + 1)]
                    if node.module:
                        base_parts.extend(node.module.split("."))
                    imported_modules = [".".join(base_parts)]
                elif node.module:
                    imported_modules = [node.module]
                else:
                    continue
            else:
                continue

            for module in imported_modules:
                top_level = module.partition(".")[0]
                if top_level in sys.stdlib_module_names or (
                    module == "muteinous.models"
                    or module.startswith("muteinous.models.")
                ):
                    continue
                violations.append(f"{path}: imports {module}")

    assert not violations, "\n".join(violations)
