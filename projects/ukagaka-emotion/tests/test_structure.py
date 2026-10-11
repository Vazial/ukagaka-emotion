import ast
from pathlib import Path


ROOT = Path(__file__).parents[1] / "ukagaka_emotion"


def imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}


def test_core_does_not_depend_on_cli_or_embedding_implementation():
    core_imports = imports(ROOT / "core.py")
    assert "__main__" not in core_imports
    assert "sentence_transformers" not in core_imports


def test_cli_does_not_own_domain_labels_or_similarity():
    source = (ROOT / "__main__.py").read_text(encoding="utf-8")
    assert "cosine(" not in source
    assert '"喜び"' not in source
