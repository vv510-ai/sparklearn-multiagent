"""RAG source-grounding acceptance for the data-structures course.

Run from backend:
    .venv\\Scripts\\python.exe tests\\acceptance_rag_grounding.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.rag.ingest import ingest_corpus  # noqa: E402
from app.rag.retriever import COURSE_SOURCE, retrieve  # noqa: E402

QUESTIONS = [
    ("binary_tree", "二叉树的定义是什么，每个节点最多有几个孩子？"),
    ("binary_tree", "满二叉树和完全二叉树有什么区别？"),
    ("binary_tree", "完全二叉树为什么适合用数组存储？"),
    ("binary_tree", "n 个节点的二叉树高度最小和最大分别是什么量级？"),
    ("binary_tree", "二叉树前序遍历的访问顺序是什么？"),
    ("binary_tree", "二叉树中序遍历的访问顺序是什么？"),
    ("binary_tree", "二叉树后序遍历的访问顺序是什么？"),
    ("binary_tree", "层序遍历为什么需要队列？"),
    ("binary_tree", "哪些遍历序列组合可以唯一重建二叉树？"),
    ("bst", "二叉搜索树 BST 的核心性质是什么？"),
    ("bst", "为什么 BST 的中序遍历得到递增序列？"),
    ("bst", "BST 查找的平均和最坏时间复杂度是多少？"),
    ("bst", "BST 插入时如何选择左子树或右子树？"),
    ("bst", "BST 删除节点分哪三种情况？"),
    ("bst", "为什么按有序序列插入会让 BST 退化？"),
    ("bst", "验证一棵树是 BST 时为什么不能只比较父子节点？"),
    ("recursion", "递归算法必须具备哪三个要素？"),
    ("recursion", "递归调用栈如何工作，空间复杂度由什么决定？"),
    ("complexity", "遍历一棵有 n 个节点的二叉树时间复杂度是多少？"),
    ("complexity", "递归遍历二叉树的辅助空间与树高有什么关系？"),
    ("heap", "堆为什么既是完全二叉树又适合用数组存储？"),
    ("heap", "堆和二叉搜索树的有序性质有什么区别？"),
    ("heap", "数组表示的堆中父节点和孩子下标如何计算？"),
    ("array", "数组的随机访问复杂度是什么，它与树的顺序存储有什么联系？"),
    ("graph_basic", "图由哪些基本元素组成，顶点和边分别表示什么？"),
    ("graph_basic", "有向图与无向图的边在方向上有什么区别？"),
    ("graph_basic", "邻接矩阵和邻接表各适合什么规模的图？"),
    ("graph_basic", "简单无向完全图的边数怎样计算？"),
    ("graph_traverse", "图的遍历为什么需要 visited 访问标记？"),
    ("graph_traverse", "BFS 为什么使用队列并按层扩展？"),
    ("graph_traverse", "DFS 为什么可以用递归或显式栈实现？"),
    ("graph_traverse", "非连通图怎样保证每个顶点都被遍历？"),
    ("sorting_adv", "快速排序的划分操作怎样把元素放到基准两侧？"),
    ("sorting_adv", "快速排序在哪些输入下可能退化为平方复杂度？"),
    ("sorting_adv", "归并排序为什么稳定并需要线性辅助空间？"),
    ("sorting_adv", "堆排序、快速排序和归并排序怎样比较稳定性？"),
    ("shortest_path", "Dijkstra 算法为什么要求所有边权非负？"),
    ("shortest_path", "无权图的单源最短路径为什么可以使用 BFS？"),
    ("dp", "动态规划中的状态、转移和边界分别是什么？"),
    ("dp", "0-1 背包一维数组为什么必须倒序遍历容量？"),
]


def _contains_kp(hit: dict, expected_kp: str) -> bool:
    values = re.split(r"[,，、;；\s]+", str(hit.get("kp", "")).strip())
    return expected_kp in {value for value in values if value}


def main() -> None:
    total_chunks = ingest_corpus()
    rows = []
    failures = []
    for index, (kp, question) in enumerate(QUESTIONS, start=1):
        hits = retrieve(question, top_k=20, final_k=5, kp=kp)
        relevant_rank = next(
            (rank for rank, hit in enumerate(hits, start=1) if _contains_kp(hit, kp)),
            None,
        )
        hit_at_5 = relevant_rank is not None and relevant_rank <= 5
        reciprocal_rank = 1.0 / relevant_rank if relevant_rank else 0.0
        source_grounded = bool(hits) and all(hit.get("source") == COURSE_SOURCE for hit in hits)
        accepted = source_grounded and hit_at_5
        item = {
            "index": index,
            "kp": kp,
            "question": question,
            "accepted": accepted,
            "source_grounded": source_grounded,
            "hit_at_5": hit_at_5,
            "first_relevant_rank": relevant_rank,
            "reciprocal_rank": round(reciprocal_rank, 4),
            "hits": [
                {
                    "rank": rank,
                    "source": hit.get("source", ""),
                    "source_id": hit.get("source_id", ""),
                    "chapter": hit.get("chapter", ""),
                    "page": hit.get("page", 0),
                    "kp": hit.get("kp", ""),
                    "citation": hit.get("citation", ""),
                    "score": round(float(hit.get("score", 0)), 4),
                    "preview": str(hit.get("text", ""))[:160],
                }
                for rank, hit in enumerate(hits, start=1)
            ],
        }
        rows.append(item)
        if not accepted:
            failures.append(item)
        print(
            f"[{index:02d}] {'PASS' if accepted else 'FAIL'} "
            f"kp={kp} hits={len(hits)} sources="
            f"{sorted({str(hit.get('source', '')) for hit in hits})}"
        )

    report = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "course_source": COURSE_SOURCE,
        "index_chunks": total_chunks,
        "question_count": len(QUESTIONS),
        "passed": len(QUESTIONS) - len(failures),
        "failed": len(failures),
        "hit_at_5": round(sum(bool(row["hit_at_5"]) for row in rows) / len(rows), 4),
        "mrr": round(sum(float(row["reciprocal_rank"]) for row in rows) / len(rows), 4),
        "items": rows,
    }
    out_dir = BACKEND_DIR / "runs" / "rag-governance-20260625"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "retrieval_acceptance.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report={out_path}")
    if failures:
        raise SystemExit(f"RAG acceptance failed: {len(failures)} questions")
    print(
        f"RAG acceptance passed: {len(QUESTIONS)}/{len(QUESTIONS)}; "
        f"Hit@5={report['hit_at_5']:.4f}; MRR={report['mrr']:.4f}"
    )


if __name__ == "__main__":
    main()
