"""Keep historical snapshots; prevent platform exercises posing as course texts."""
import copy
from fastapi import HTTPException


def publisher_path(course: dict) -> bool:
    from .study_paths import course_key
    return bool(course_key(course))


def trusted_textbook(course: dict) -> bool:
    book = course.get("textbook") or {}
    return bool(book and str(book.get("url", "")).startswith("https://docs.python.org/")
                and book.get("source_kind") != "platform_original")


def active_sources(course: dict) -> dict:
    result = copy.deepcopy(course)
    if publisher_path(course):
        result["bank"] = []
        result["practice_bank"] = []
        result["lessons"] = {}
        if not trusted_textbook(course):
            result.pop("textbook", None)
            result["evidence"] = {}
        result["source_policy"] = "publisher_materials"
        result["boundary"] = "按当前章节使用原教材与机构题目。外部链接不是已读原文；讲解时请提供原题、截图或上传资料。"
    return result


def require_default_practice(course: dict | None) -> None:
    if course and publisher_path(course):
        raise HTTPException(409, "本课程已改为原教材与真题学习，请在左侧点击继续课程学习，完成当前章节的原题并记录订正。")
