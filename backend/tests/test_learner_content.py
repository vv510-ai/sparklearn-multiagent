from app.agents import doc_agent, mindmap_agent, quiz_agent
from app.schemas.core import GenerateRequest
from app.services.learner_content import looks_like_source_code, plain_learning_text, without_source_code


PYTHON_BLOCK = """先理解访问顺序。

```python
def inorder(root, out):
    if not root:
        return
    inorder(root.left, out)
```

把过程记成：先左边，再当前，最后右边。
"""


def test_non_code_learning_content_removes_source_code_but_keeps_explanation():
    cleaned = without_source_code(PYTHON_BLOCK)
    assert "def inorder" not in cleaned
    assert "先理解访问顺序" in cleaned
    assert "先左边" in cleaned


def test_mermaid_can_be_kept_as_a_visual_not_exposed_as_program_code():
    text = "```mermaid\nflowchart LR\nA[开始] --> B[结束]\n```\n```python\nprint('hidden')\n```"
    cleaned = without_source_code(text, keep_mermaid=True)
    assert "flowchart LR" in cleaned
    assert "print" not in cleaned


def test_short_artifact_fields_reject_raw_source_code():
    assert plain_learning_text("def inorder(root, out):\n    return out") == ""
    assert doc_agent._plain_excerpt(PYTHON_BLOCK, 100).startswith("先理解访问顺序")  # noqa: SLF001
    assert mindmap_agent._clean_point("- def inorder(root, out):") == ""  # noqa: SLF001
    assert looks_like_source_code("inorder(root.left, out)\nout.append(root.val)")
    assert without_source_code("if ready:\n    return result") == ""


def test_quiz_validator_rejects_program_source_in_learner_fields():
    question = {
        "type": "single",
        "stem": "def inorder(root, out): 的下一行是什么？",
        "options": ["A return", "B stop"],
        "answer": "A",
    }
    assert quiz_agent._validate(question, "binary_tree") is None  # noqa: SLF001


def test_default_generation_plan_does_not_request_code():
    assert "code" not in GenerateRequest().kinds


def test_ppt_prompt_does_not_forward_source_code():
    query = doc_agent._ppt_query(  # noqa: SLF001
        "二叉树",
        "复习遍历",
        "零基础",
        PYTHON_BLOCK,
        source_bound=True,
    )
    assert "def inorder" not in query
    assert "先理解访问顺序" in query
    assert "不展示源码" in query
