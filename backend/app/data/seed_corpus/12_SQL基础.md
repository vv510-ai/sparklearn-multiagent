---
source: 《SQL 入门》讲义
chapter: 第12章 SQL 基础
kp: sql_basic
license: 自编开源讲义(CC BY-SA 4.0)
type: lecture
tags: SQL,SELECT,WHERE,ORDER BY,GROUP BY,JOIN
---

## 示例数据表

本章始终使用三张表。学生表 `students(id, name, class_name)` 保存学生；课程表 `courses(id, name, teacher)` 保存课程；选课表 `enrollments(student_id, course_id, score)` 连接学生和课程，并记录成绩。

```sql
CREATE TABLE students (id INT PRIMARY KEY, name VARCHAR(50), class_name VARCHAR(50));
CREATE TABLE courses (id INT PRIMARY KEY, name VARCHAR(100), teacher VARCHAR(50));
CREATE TABLE enrollments (
  student_id INT,
  course_id INT,
  score DECIMAL(5,2),
  PRIMARY KEY (student_id, course_id)
);
```

## SELECT：选择要看的列

`SELECT` 决定查询结果显示哪些列，`FROM` 决定数据来自哪张表。尽量写出需要的列，不要习惯性使用 `SELECT *`。

```sql
SELECT id, name, class_name
FROM students;
```

这个例子返回每名学生的编号、姓名和班级。

## WHERE：过滤行

`WHERE` 在分组前过滤原始记录。可以使用比较运算符以及 `AND`、`OR`、`IN`、`LIKE` 等条件。

```sql
SELECT name, class_name
FROM students
WHERE class_name = '软件一班';
```

这个例子只保留软件一班的学生。字符串需要使用单引号，判断是否为空应使用 `IS NULL`，不能写 `= NULL`。

## ORDER BY：排序结果

`ORDER BY` 对最终结果排序；`ASC` 是升序且可省略，`DESC` 是降序。多个排序键从左到右依次生效。

```sql
SELECT student_id, course_id, score
FROM enrollments
ORDER BY score DESC, student_id ASC;
```

这个例子先按成绩从高到低排列，成绩相同时再按学生编号升序排列。

## GROUP BY：分组聚合

`GROUP BY` 把具有相同分组键的行放在一组，常与 `COUNT`、`AVG`、`SUM`、`MAX`、`MIN` 一起使用。`WHERE` 过滤分组前的行，`HAVING` 过滤聚合后的组。

```sql
SELECT course_id, COUNT(*) AS student_count, AVG(score) AS avg_score
FROM enrollments
WHERE score IS NOT NULL
GROUP BY course_id
HAVING COUNT(*) >= 2
ORDER BY avg_score DESC;
```

这个例子统计每门至少有两名学生选修的课程人数和平均分，并按平均分降序排列。查询中没有聚合的输出列通常必须出现在 `GROUP BY` 中。

## 多表连接：把相关记录拼起来

`JOIN ... ON ...` 按关联条件连接表。`INNER JOIN` 只保留两边都匹配的记录；`LEFT JOIN` 保留左表全部记录，右表没有匹配时对应列为 `NULL`。连接时必须写清表别名和连接条件，遗漏 `ON` 可能产生笛卡尔积。

```sql
SELECT
  s.name AS student_name,
  c.name AS course_name,
  e.score
FROM enrollments AS e
JOIN students AS s ON s.id = e.student_id
JOIN courses AS c ON c.id = e.course_id
WHERE e.score >= 60
ORDER BY e.score DESC;
```

这个例子从选课表出发，通过学生编号和课程编号连接另外两张表，列出及格学生、课程和成绩。

## 综合例子与执行顺序

查询“每门课程的选课人数和平均分”可以写成：

```sql
SELECT c.id, c.name, COUNT(e.student_id) AS student_count, AVG(e.score) AS avg_score
FROM courses AS c
LEFT JOIN enrollments AS e ON e.course_id = c.id
GROUP BY c.id, c.name
ORDER BY avg_score DESC;
```

理解查询时可以按逻辑顺序阅读：`FROM/JOIN → WHERE → GROUP BY → HAVING → SELECT → ORDER BY`。书写顺序与逻辑执行顺序不同，是初学者最容易混淆的地方之一。

## 易错点

1. `WHERE` 不能直接筛选 `AVG(score)` 等聚合结果，应使用 `HAVING`。
2. 多表都有 `id`、`name` 等同名列时，要写 `s.name`、`c.name` 这样的表别名。
3. `LEFT JOIN` 后若在 `WHERE` 中强制右表列满足条件，可能把它意外变成类似 `INNER JOIN` 的效果。
4. `COUNT(*)` 统计结果行；`COUNT(column)` 不统计该列为 `NULL` 的行。
5. 没有明确 `ORDER BY` 时，数据库不保证返回顺序。
