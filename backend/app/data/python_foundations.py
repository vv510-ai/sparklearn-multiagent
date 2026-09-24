"""Original, finite beginner curriculum. Example code runs only in content tests.
Official source text is kept separately with its original license and hash.
No student code is executed by the server.
"""
from __future__ import annotations

# id, title, objective, official anchors, explanation, runnable example, output,
# independent task, observable criteria, two unseen output exercises.
LESSONS = [
("start", "运行第一个程序", "能区分代码与输出，运行并修改一段 Python 程序", ["invoking-the-interpreter", "numbers"],
"""程序是一组按顺序执行的指令。把代码交给 Python 解释器，解释器才会计算并产生输出。编辑器里写下代码，与真正运行它，是两件事。

### 先完成一次运行
安装 Python 3 后，在终端输入 `python --version`（部分系统使用 `python3` 或 Windows 的 `py`）。看到版本号后，建立 `hello.py`，把下面的代码保存进去，再运行 `python hello.py`。命令名要与刚才成功的命令一致。使用已有在线 Python 环境也可以，先确认支持 Python 3；不要输入个人敏感信息。

### 看清输入和输出
`print(...)` 把括号里的值显示出来。引号表示字符串，也就是文字；没有引号的 `2 + 3` 是计算。交互环境里的 `>>>` 是提示符，复制到 .py 文件时不需要它。报错时先看最后一行，再核对引号、括号和拼写。""",
"print('Hello, Python')\nprint(2 + 3)", "Hello, Python\n5",
"自己写一个程序，分两行显示你的课程代号和 7 乘 4 的结果。把代号换成另一段文字后再次运行，说明哪一行输出发生了变化。",
["有两个 print 调用", "文字使用引号，乘法作为表达式计算", "记录两次真实运行结果，并说明区别"],
[("print('3 + 4')\nprint(3 + 4)", "3 + 4\n7", ["7\n7", "3 + 4\n3 + 4", "报错"], "带引号的内容原样输出；第二行先计算再输出。"),
 ("print('Hi')\nprint(8 - 3)", "Hi\n5", ["Hi 5", "5\nHi", "Hi\n8 - 3"], "两个 print 按顺序各输出一行，8 - 3 的结果是 5。")]),
("values", "变量、类型与输入", "能逐行追踪赋值，并正确转换数字文本", ["numbers", "text"],
"""变量名可以指向一个值。执行赋值时先算右边，再把结果交给左边。以后修改另一个变量，并不会自动重算先前的结果。

### 数字和文字不同
`'12'` 是字符串，`12` 是整数。`'1' + '2'` 得到 `'12'`，而 `1 + 2` 得到 `3`。`input('提示')` 读到的也是字符串；确定输入是整数时可用 `int(...)` 转换。遇到非数字文字会报 ValueError，后面的异常课会处理它。

### 运算时先问两个问题
输入的类型是什么？输出需要什么类型？`/` 是除法，`//` 是向下取整的除法，`%` 是余数。不要把赋值号 `=` 当成判断相等的 `==`。""",
"price = 6\nquantity_text = '3'\ncost = price * int(quantity_text)\nprice = 9\nprint(cost)", "18",
"写一个两种文具的预算程序：数量先以字符串保存，转换后分别计算费用，再求总价。修改一个单价并重新运行，解释结果为什么改变。",
["明确区分数量文本与数字", "算出两项费用和总价", "给出初次和修改后的真实输出"],
[("a = 5\nb = a + 4\na = 20\nprint(b)", "9", ["24", "20", "5"], "b 在赋值时得到 9，后来给 a 赋值不会重算 b。"),
 ("text = '4'\nprint(text + '2')\nprint(int(text) + 2)", "42\n6", ["6\n6", "42\n42", "报错"], "第一行拼接字符串，第二行先把字符串转换为整数。")]),
("branches", "条件与边界", "能编写互斥分支，并检查临界值", ["if-statements", "more-on-conditions"],
"""条件表达式产生 True 或 False。`if / elif / else` 从上向下检查，只执行第一个成立的分支。缩进表示某个分支包含哪些语句，建议每层使用四个空格。

### 用边界检查规则
“满 60 分通过”对应 `score >= 60`，所以 59、60、61 都值得检查。如果把 `> 60` 写错，恰好 60 的人就会被误判。多个独立的 if 会分别判断，与一个 if/elif 结构不同。

### 条件组合
`and` 要求两边都成立，`or` 只需至少一边成立，`not` 取反。先用白话说规则，再写条件。比较文字是否相等也使用 `==`。""",
"score = 60\nif score >= 85:\n    result = '优秀'\nelif score >= 60:\n    result = '通过'\nelse:\n    result = '继续练习'\nprint(result)", "通过",
"为借阅天数写一个提示：不超过 7 天显示“按时”，超过 7 天显示“请续借”。分别测试 6、7、8 天，再解释等号应放在哪个分支。",
["7 天进入按时分支", "三个测试结果与规则一致", "缩进正确，并解释了临界值"],
[("x = 8\nif x > 3:\n    print('A')\nelif x > 6:\n    print('B')", "A", ["B", "A\nB", "无输出"], "第一个条件成立后，整个结构不再执行 elif。"),
 ("n = 7\nif n >= 7 and n < 10:\n    print('yes')\nelse:\n    print('no')", "yes", ["no", "yes\nno", "报错"], "7 同时满足大于等于 7 和小于 10。")]),
("loops", "循环与逐步追踪", "能遍历列表、累加，并说明每轮状态", ["for-statements", "the-range-function", "first-steps-towards-programming"],
"""循环用相同规则处理多个元素。`for n in [2, 4, 6]` 会让 n 依次取这三个值；每一轮运行缩进的代码。`range(4)` 给出 0、1、2、3，不包含停止值。

### 累加器放在哪里
把 total = 0 放在循环前，只初始化一次。如果放到循环里面，每轮都把已有结果清空。检查程序时画两列：本轮元素、执行后 total。这样能把“看起来懂了”变成逐步核对。

### 循环结束条件
`while` 在条件为真时重复，循环内要让状态逐步靠近结束条件。例如倒计时需要减小计数；忘记更新可能一直运行。先用很小的输入测试。""",
"total = 0\nfor cost in [2, 4, 6]:\n    total += cost\n    print(total)", "2\n6\n12",
"统计 [3, 8, 5, 10] 中偶数的总和。自己组合条件和循环，先手写每轮的累计值，再运行核对。随后用空列表测试。",
["只累加偶数", "累加器初始化在循环前", "原列表结果为 18，空列表结果为 0"],
[("total = 0\nfor n in range(4):\n    total += n\nprint(total)", "6", ["10", "4", "3"], "遍历的是 0、1、2、3，它们的和是 6。"),
 ("n = 3\nwhile n > 0:\n    n -= 1\nprint(n)", "0", ["1", "3", "-1"], "n 到 0 时条件为假，循环停止。")]),
("containers", "列表、字典与可变对象", "能按位置和按名称组织数据，识别列表别名", ["lists", "dictionaries", "tuples-and-sequences", "sets"],
"""单个值不足以记录一组数据时，可以使用容器。列表保存有顺序的元素，索引从 0 开始；字典保存键和值的对应关系，例如课程名与分数。

### 选择访问方式
`scores[0]` 取列表第一项，`scores[-1]` 取最后一项。字典用 `record['数学']` 按键找值；键不存在会报错，可用 `record.get('数学', 0)` 设置缺失时的默认值。集合适合去重，不要依赖它的展示顺序。元组适合表达固定的一组位置，不能像列表那样原地改某个元素。

### 两个名字可能指向同一个列表
`b = a` 不会复制列表。通过 b 修改元素时，a 也能看到变化。需要新的浅层列表时可用 `a.copy()`；嵌套容器仍需理解内部对象是否共享。""",
"record = {'数学': 80, '英语': 75}\nrecord['英语'] = 82\nprint(record['英语'])\nitems = [1, 2]\nalias = items\nalias.append(3)\nprint(items)", "82\n[1, 2, 3]",
"用字典保存三门课程的分数，修改其中一门，输出它的新分数。再从 [2, 2, 5, 5, 8] 构造集合，输出不同元素的个数；不要假设集合的打印顺序。",
["使用课程名作为字典键", "修改和读取同一个键", "去重后元素个数为 3"],
[("a = [4, 5]\nb = a\nb.append(6)\nprint(a[-1])", "6", ["4", "5", "报错"], "a 与 b 指向同一个列表，append 后最后一项是 6。"),
 ("d = {'x': 2}\nprint(d.get('y', 0) + d['x'])", "2", ["0", "报错", "y2"], "缺失的 y 使用默认值 0，x 对应 2。")]),
("functions", "函数、参数与返回值", "能把重复计算写成函数，并区分返回和打印", ["defining-functions", "default-argument-values"],
"""函数为一段操作命名。定义函数时并不立即执行函数体；调用时，实参传给参数，再执行具体计算。`return` 把值交给调用者并结束本次执行。

### print 和 return
print 是在屏幕显示内容，return 是把结果交还给调用处。需要后续参与计算的结果应返回。函数没有执行带值的 return 时，返回 None；它不是数字 0。

### 默认参数
未提供参数时可采用默认值，显式传参会覆盖本次默认值。可变对象作为默认值容易在多次调用间共享；先用数字、文字或 None 做默认值，避免无意积累状态。

先写清函数输入和输出，再用两个普通输入及一个边界输入测试。""",
"def cost(count, unit=6):\n    return count * unit\n\nprint(cost(3))\nprint(cost(3, 8))", "18\n24",
"编写 sum_even(numbers)，返回列表中偶数的总和，函数内部不要打印。分别调用它处理 [2, 3, 4] 和 []，在调用处打印返回值。",
["函数接收列表并使用 return", "结果依次是 6 和 0", "调用方可以继续使用返回值参与计算"],
[("def twice(x):\n    return x * 2\nprint(twice(4) + 1)", "9", ["8", "5", "None"], "twice(4) 返回 8，调用处再加 1。"),
 ("def greet():\n    print('hi')\nvalue = greet()\nprint(value)", "hi\nNone", ["hi", "None", "hi\nhi"], "函数先打印 hi，没有带值 return，所以 value 是 None。")]),
("modules", "模块与标准库", "能导入标准库，并把函数放入另一个文件", ["modules"],
"""模块通常是一个 .py 文件，里面可以定义函数、变量等。把相关操作放到模块里，可让主程序更容易阅读和复用。

### 先用自带的标准库
`import math` 后，通过 `math.sqrt(...)` 使用平方根函数。这里的 math 来自 Python 标准库，不需要另外安装。第三方包和标准库不同，只有确实需要时再安装，并核对来源。

### 拆成两个文件
在 helpers.py 写 `def double(n): return n * 2`，在同目录 main.py 写 `from helpers import double`，再调用 double(5)。不要把自己的文件叫 math.py，否则可能遮住标准库。

导入时模块顶层代码可能执行；把直接运行时才做的演示放在 `if __name__ == '__main__':` 下面，有助于避免导入就运行整段演示。""",
"import math\nprint(math.isqrt(25))\nprint(math.ceil(2.3))", "5\n3",
"把上一课的 sum_even 放到 helpers.py，再在 main.py 导入并调用。给 helpers.py 加一个只在直接运行时打印的测试，比较直接运行与导入的区别。",
["主文件能导入并调用函数", "文件名没有遮住使用的标准库", "主入口条件下的测试在导入时不执行"],
[("import math\nprint(math.isqrt(36) + 1)", "7", ["6", "37", "6.0"], "整数平方根为 6，之后加 1 得到 7。"),
 ("from math import ceil\nprint(ceil(3.2))", "4", ["3", "3.2", "报错"], "ceil 返回不小于输入的最小整数。")]),
("files", "读写文本与保存数据", "能使用 with 读写自己的文本文件，说明覆盖与追加", ["reading-and-writing-files"],
"""程序结束后，内存里的变量不会自动变成文件。保存文本需要明确选择文件路径、打开模式和编码。

### 从一个自己的练习文件开始
`with open('notes.txt', 'w', encoding='utf-8') as f:` 会创建文件；同名文件已存在时，w 会清空旧内容，因此只对自己的练习文件使用它。需要保留旧内容并在末尾添加时使用 a。读取使用 r。with 会在离开代码块时关闭文件。

### 文件里的数字是文本
读取一行会得到字符串，通常需要去掉换行或空白，再根据目标转成数字。不同工作目录会改变相对路径对应的位置；找不到文件时先核对运行位置。

下面用内存中的文本流演示相同的写入/读取方式，不会改动你的磁盘。真正保存时把 StringIO 换成上面的 open。""",
"from io import StringIO\nwith StringIO() as f:\n    f.write('first\\nsecond\\n')\n    f.seek(0)\n    print(f.readline().strip())\n    print(f.readline().strip())", "first\nsecond",
"在自己的练习目录创建 study_notes.txt，写入两条学习记录，再用读取模式逐行打印。另加一次追加写入，确认旧内容保留。提交代码与实际输出，不要使用重要文件测试 w 模式。",
["明确使用 UTF-8 和 with", "能够解释 w 与 a 的区别", "实际读取结果包含追加前后的记录"],
[("from io import StringIO\nf = StringIO('a\\nb\\n')\nprint(len(f.readlines()))", "2", ["1", "3", "4"], "readlines 得到两行，末尾换行不会额外形成第三行。"),
 ("from io import StringIO\nf = StringIO('12\\n')\nprint(int(f.readline().strip()) + 3)", "15", ["123", "12", "报错"], "先读取字符串、清理空白、转成整数，再加 3。")]),
("errors", "异常与定位问题", "能区分语法错误与运行异常，处理可预期的错误", ["handling-exceptions", "syntax-errors"],
"""报错是一条定位线索。SyntaxError 往往表示代码结构不能被解析，例如括号或冒号缺失；ValueError 等异常则可能在运行某条语句时出现。

### 从最后一行开始读
错误类型说明问题类别，调用栈里的文件名和行号帮助找到位置。先用最小输入复现，再修改一个原因；不要把所有报错都当成“软件坏了”。

### 只处理预期的异常
把可能失败的一小段转换放到 try 中，用 `except ValueError:` 处理非数字输入。不要用一个空的 except 把所有错误吞掉；意料之外的错误应继续暴露，便于修复。异常发生后，try 中尚未执行的语句不会继续执行。""",
"raw = 'abc'\ntry:\n    value = int(raw)\n    print(value * 2)\nexcept ValueError:\n    print('请输入整数')", "请输入整数",
"写一个将数量文本转换为整数的函数。合法输入返回整数，非数字输入返回 None。分别测试 '12'、'abc' 和 '0'，解释为什么 None 和 0 不能混为一谈。",
["只捕获预期的 ValueError", "三个输入分别得到 12、None、0", "能够区分合法零值与转换失败"],
[("try:\n    n = int('oops')\n    print('ok')\nexcept ValueError:\n    print('retry')", "retry", ["ok", "ok\nretry", "None"], "转换抛出 ValueError，跳过后面的 print('ok') 并进入处理分支。"),
 ("try:\n    print(int('0'))\nexcept ValueError:\n    print('bad')", "0", ["bad", "None", "0\nbad"], "'0' 是合法整数文本，转换成功，不执行 except。")]),
("project", "综合任务：学习记录统计", "能组合容器、条件、循环和函数，保存并解释学习记录", ["lists", "for-statements", "defining-functions", "reading-and-writing-files", "handling-exceptions"],
"""现在把前面的知识组合起来：记录每次学习的科目和分钟数，计算总时长，找出达到目标的记录，并保存到自己的文本文件。

### 先拆任务，再写程序
输入是什么？用列表保存多条记录，每条记录用字典表示。怎样检查？分钟数不能是负数；非法输入给出清楚提示。怎样计算？把汇总逻辑写进函数，通过 return 返回结果。怎样保存？用 UTF-8 文本，并说明文件模式会不会覆盖旧内容。

### 分别验证各部分
先用两条合法记录检查汇总，再试空列表、零分钟和非法文本。每次只增加一个功能。示例只演示内存中的统计，你的独立任务要补上输入检查和文件保存。

完成这个任务说明你练习了本课程列出的基础，不代表已经学完面向对象、网络开发、数据分析或所有大学 Python 课程。""",
"def total_minutes(records):\n    return sum(item['minutes'] for item in records)\n\nrecords = [{'subject': 'Python', 'minutes': 20}, {'subject': '英语', 'minutes': 15}]\nprint(total_minutes(records))", "35",
"独立完成一个学习记录程序：至少三条科目/分钟记录；用函数汇总；列出不少于 20 分钟的记录；验证非法分钟文本；保存到自己的 study_log.txt 并读回。提交实现、测试输入输出和一个你修复过的问题。",
["三条记录且字段清楚", "汇总函数可被独立调用", "条件筛选包含恰好 20 分钟", "测试空列表、零值及非数字输入", "文件读回与保存内容一致，并说明覆盖/追加选择"],
[("records = [{'minutes': 12}, {'minutes': 18}, {'minutes': 20}]\nprint(sum(r['minutes'] for r in records if r['minutes'] >= 18))", "38", ["50", "20", "30"], "符合条件的是 18 和 20，合计 38。"),
 ("def total(values):\n    result = 0\n    for n in values:\n        if n > 0:\n            result += n\n    return result\nprint(total([0, -2, 7, 3]))", "10", ["8", "7", "0"], "只累加大于 0 的元素，7 + 3 = 10。")]),
]
