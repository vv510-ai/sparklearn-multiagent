# Manim 预渲染素材

这两段动画是小云雀视频不可用时的固定教学视频。运行时只读取生成后的 MP4，不执行大模型返回的 Python 代码。

环境要求：Python 3.11、FFmpeg、`manim==0.18.1`。

```powershell
cd backend
python -m pip install -r requirements-manim.txt
python -m manim -ql scripts/manim/binary_tree_traversal.py SceneBinaryTreeTraversal
python -m manim -ql scripts/manim/bst_insertion.py SceneBstInsertion
```

验收后的文件放入 `app/static/gen/`，文件名固定为：

- `manim_binary_tree_traversal.mp4`
- `manim_bst_insertion.mp4`
