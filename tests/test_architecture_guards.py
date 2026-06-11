import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "app"


def app_python_files() -> list[Path]:
    return sorted(APP_ROOT.rglob("*.py"))


def repo_relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def is_llm_gateway_path(path: Path) -> bool:
    return path.relative_to(APP_ROOT).as_posix().startswith("suite/llm_gateway/")


def is_kms_adapter_path(path: Path) -> bool:
    return path.relative_to(APP_ROOT).as_posix().startswith("suite/kms/")


def is_provider_composition_root(path: Path) -> bool:
    return repo_relative(path) == "app/main.py"


def parse_python(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_product_modules_do_not_import_llm_providers_directly() -> None:
    violations: list[str] = []
    for path in app_python_files():
        if is_llm_gateway_path(path) or is_provider_composition_root(path):
            continue
        tree = parse_python(path)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("suite.llm_gateway.providers")
            ):
                violations.append(f"{repo_relative(path)}:{node.lineno} imports {node.module}")

    assert violations == []


def test_product_modules_do_not_call_llm_provider_complete_directly() -> None:
    violations: list[str] = []
    for path in app_python_files():
        if is_llm_gateway_path(path):
            continue
        tree = parse_python(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "complete":
                violations.append(f"{repo_relative(path)}:{node.lineno} calls .complete() directly")

    assert violations == []


def test_product_modules_do_not_import_crypto_provider_primitives_directly() -> None:
    forbidden_import_roots = {
        "boto3",
        "botocore",
        "cryptography",
        "nacl",
        "OpenSSL",
        "Crypto",
    }
    violations: list[str] = []
    for path in app_python_files():
        if is_kms_adapter_path(path):
            continue
        tree = parse_python(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_name = alias.name.split(".", maxsplit=1)[0]
                    if root_name in forbidden_import_roots:
                        violations.append(f"{repo_relative(path)}:{node.lineno} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                root_name = node.module.split(".", maxsplit=1)[0]
                if root_name in forbidden_import_roots:
                    violations.append(f"{repo_relative(path)}:{node.lineno} imports {node.module}")

    assert violations == []
