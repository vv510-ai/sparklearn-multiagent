"""Original unseen-question pool. Code fixtures have executable answer oracles.

No user-supplied code is executed. These trusted snippets are run by tests only.
The first three questions per topic are used after learning; later questions
remain private until spaced reviews. The entry assessment uses a separate bank.
"""
LESSONS = {
    "py_values": """### 把一次赋值看成一次计算
先算等号右侧，再把结果交给左侧变量。之后修改其他变量，不会重新计算已经完成的赋值。

```python
unit = 6
cost = unit * 3
unit = 9
print(cost)  # 18
```

第一步 `unit` 是 6；第二步 `cost` 得到 18；第三步只改变 `unit`。不要把赋值当作永远保持相等的数学方程。

### 先看类型，再看运算
`'6' + '3'` 是文字拼接得到 `'63'`，`int('6') + 3` 才是整数相加。`//` 给出整除结果，`%` 给出余数。

合上资料，逐行记录变量的值，并说明每次运算处理的是数字还是文字。""",
    "py_branches": """### 顺着条件判断一次
一个 `if / elif / else` 结构只执行第一个条件成立的分支。

```python
temperature = 18
if temperature >= 30:
    label = '热'
elif temperature >= 15:
    label = '适中'
else:
    label = '冷'
print(label)  # 适中
```

先检查 18≥30，不成立；再检查 18≥15，成立；执行后离开整组分支。多个独立的 `if` 会各自判断，不能与 `elif` 混为一谈。

画出“条件 → 是否成立 → 执行哪一步”，再检查边界值，例如恰好等于 15。""",
    "py_loops": """### 把循环展开成一张小表
`range(4)` 产生 0、1、2、3，不包括停止值 4。每轮都会更新累加器。

```python
total = 0
for price in [2, 5, 8]:
    total += price
print(total)  # 15
```

三轮结束时，`total` 依次是 2、7、15。初始化放在循环前；若每轮都置零，就丢掉了之前的累计。

列表索引从 0 开始，负索引从末尾开始。`items[-1]` 是最后一项，`items[:2]` 是前两项。

做题时先写出实际遍历的元素，再逐轮计算；不要凭循环次数猜结果。""",
    "py_functions": """### 区分传入、返回和屏幕输出
参数接收这次调用的输入；`return` 把结果交还给调用处，随即结束本次函数执行。

```python
def ticket_price(count, unit=6):
    return count * unit

bill = ticket_price(3)
print(bill)  # 18
```

实参 3 传给 `count`，未传 `unit` 时使用默认值 6，计算后返回 18。调用时显式传入 `unit` 会替换本次默认值。

`print` 只向屏幕输出；一个函数没有执行带值的 `return` 时返回 `None`。先找调用、再代入参数、最后沿着实际执行的 `return` 追踪结果。""",
}

# stem, code, expected stdout, distractors, explanation
EXERCISES = {
    "py_values": [
        ("采购记录先计算预算，再修改单价。最后输出什么？", "price = 7\nbudget = price * 4\nprice = 10\nprint(budget)", "28", ["40", "7", "10"], "budget 在赋值时已得到 7×4=28，后来修改 price 不会重算 budget。"),
        ("下面把文本转换后计算。输出什么？", "text = '12'\nprint(int(text) + 5)", "17", ["125", "12", "报错"], "int 把字符串 '12' 转成整数 12，再与 5 相加。"),
        ("分组后还剩多少物品？输出什么？", "items = 23\nprint(items // 5, items % 5)", "4 3", ["4.6 3", "5 3", "4 5"], "23 除以 5 的整数商是 4，余数是 3；print 用空格分隔两个值。"),
        ("变量交换后输出什么？", "left = 4\nright = 9\nleft, right = right, left\nprint(left - right)", "5", ["-5", "0", "13"], "右侧先得到 9、4，再赋给 left、right，所以差为 5。"),
        ("字符串重复后再拼接，输出什么？", "tag = 'go'\nprint(tag * 2 + '!')", "gogo!", ["go2!", "go!go!", "报错"], "字符串乘整数会重复，拼接叹号得到 gogo!。"),
        ("计算平均值后转换，输出什么？", "average = (8 + 5) / 2\nprint(int(average))", "6", ["6.5", "7", "13"], "先得 6.5，int 将小数部分截去得到 6。"),
        ("更新计数器后输出什么？", "count = 2\ncount = count + 3\ncount *= 2\nprint(count)", "10", ["8", "7", "5"], "先更新为 5，再乘 2 得到 10。"),
        ("运算顺序下输出什么？", "print(2 + 3 * 4)", "14", ["20", "24", "9"], "乘法先于加法，先得 12 再加 2。"),
        ("两个变量引用数字，更新后输出什么？", "a = 11\nb = a\na += 2\nprint(b, a)", "11 13", ["13 13", "11 11", "13 11"], "b 保留原数字 11，a 更新为 13。"),
    ],
    "py_branches": [
        ("优惠规则按顺序匹配，输出什么？", "amount = 120\nif amount >= 100:\n    discount = 10\nelif amount >= 50:\n    discount = 5\nelse:\n    discount = 0\nprint(discount)", "10", ["5", "15", "0"], "首个条件已经成立，elif 不再判断，折扣为 10。"),
        ("两个独立 if 判断后输出什么？", "x = 6\nlabel = ''\nif x > 3:\n    label += 'A'\nif x > 5:\n    label += 'B'\nprint(label)", "AB", ["A", "B", "空字符串"], "两个 if 各自执行判断，都成立，因此得到 AB。"),
        ("边界值恰好为 18，输出什么？", "age = 18\nif age < 18:\n    print('少年')\nelse:\n    print('成人')", "成人", ["少年", "两行都输出", "没有输出"], "18 < 18 不成立，进入 else 分支。"),
        ("复合条件的结果是什么？", "score = 72\nlate = True\nif score >= 60 and not late:\n    print('通过')\nelse:\n    print('待核对')", "待核对", ["通过", "True", "False"], "not late 为假，and 的整个条件为假。"),
        ("先匹配负数，再匹配零，输出什么？", "n = 0\nif n < 0:\n    print('负')\nelif n == 0:\n    print('零')\nelse:\n    print('正')", "零", ["负", "正", "没有输出"], "第一个条件为假，第二个条件为真，因此输出零。"),
        ("满足一个条件即可时，输出什么？", "member = False\npoints = 90\nif member or points >= 80:\n    print('可兑换')\nelse:\n    print('不可兑换')", "可兑换", ["不可兑换", "False", "没有输出"], "or 两侧有一侧成立即可，90≥80 成立。"),
        ("嵌套条件输出什么？", "x = 5\nif x > 0:\n    if x % 2 == 0:\n        print('正偶数')\n    else:\n        print('正奇数')\nelse:\n    print('非正数')", "正奇数", ["正偶数", "非正数", "没有输出"], "5 大于 0 且除以 2 余 1，因此走内层 else。"),
        ("相等与不相等判断，输出什么？", "a = 3\nb = 3\nif a != b:\n    print('不同')\nelse:\n    print('相同')", "相同", ["不同", "3", "报错"], "a != b 为假，执行 else。"),
        ("区间边界输出什么？", "n = 10\nif 0 <= n < 10:\n    print('区间内')\nelse:\n    print('区间外')", "区间外", ["区间内", "10", "没有输出"], "右侧边界不包含 10，因此条件不成立。"),
    ],
    "py_loops": [
        ("记录三个订单金额，循环结束输出什么？", "total = 0\nfor amount in [4, 7, 2]:\n    total += amount\nprint(total)", "13", ["2", "9", "11"], "依次累加 4、7、2，得到 13。"),
        ("带起止值的 range，输出什么？", "total = 0\nfor n in range(2, 6):\n    total += n\nprint(total)", "14", ["20", "12", "6"], "遍历 2、3、4、5，不包含 6，和为 14。"),
        ("列表切片与末尾访问，输出什么？", "scores = [12, 18, 25, 31]\nprint(scores[-1] - scores[:2][0])", "19", ["13", "6", "报错"], "最后一项为 31，前两项组成的列表第 0 项为 12，差为 19。"),
        ("循环中只累加满足条件的数，输出什么？", "total = 0\nfor n in [1, 4, 6, 7]:\n    if n % 2 == 0:\n        total += n\nprint(total)", "10", ["18", "8", "6"], "只有 4 和 6 是偶数，合计 10。"),
        ("每轮都重置累加器，输出什么？", "total = 0\nfor n in [2, 3, 9]:\n    total = 0\n    total += n\nprint(total)", "9", ["14", "5", "0"], "每轮先置零，最后只保留最后一项 9。"),
        ("步长为 2 的 range，输出什么？", "print(list(range(1, 8, 2)))", "[1, 3, 5, 7]", ["[1, 3, 5, 7, 8]", "[2, 4, 6, 8]", "[1, 2, 3, 4, 5, 6, 7]"], "从 1 开始每次加 2，保持小于 8。"),
        ("逐个拼接标签，输出什么？", "text = ''\nfor letter in ['a', 'c', 'b']:\n    text += letter\nprint(text)", "acb", ["abc", "b", "报错"], "for 按列表已有顺序遍历，不会自动排序。"),
        ("倒数第二个元素是什么？", "values = [5, 8, 13, 21]\nprint(values[-2])", "13", ["8", "21", "5"], "-1 是最后一项，-2 是倒数第二项 13。"),
        ("只执行三轮更新，输出什么？", "product = 1\nfor n in [2, 3, 4]:\n    product *= n\nprint(product)", "24", ["9", "12", "0"], "依次乘 2、3、4，结果为 24。"),
    ],
    "py_functions": [
        ("运费函数的返回值是什么？", "def delivery(weight, rate=4):\n    return weight * rate + 2\nprint(delivery(3))", "14", ["12", "6", "None"], "weight 为 3，rate 默认 4，返回 3×4+2=14。"),
        ("函数没有 return，最后输出什么？", "def record(value):\n    total = value + 5\nresult = record(6)\nprint(result)", "None", ["11", "6", "报错"], "局部变量 total 不会自动返回；没有 return，调用结果是 None。"),
        ("提前 return 后，输出什么？", "def fee(member):\n    if member:\n        return 8\n    return 15\nprint(fee(True))", "8", ["15", "23", "True"], "条件成立后 return 8，函数立即结束，不执行后面的 return。"),
        ("显式指定参数后输出什么？", "def area(width, height=3):\n    return width * height\nprint(area(4, height=5))", "20", ["12", "15", "9"], "这次传入 height=5，使用 4×5。"),
        ("两个函数调用组合，输出什么？", "def twice(n):\n    return n * 2\nprint(twice(3) + twice(5))", "16", ["8", "30", "10"], "两个调用分别返回 6 和 10，相加得到 16。"),
        ("传入表达式时，输出什么？", "def add_one(n):\n    return n + 1\nprint(add_one(2 * 4))", "9", ["12", "8", "7"], "先算实参 2×4=8，再调用函数返回 9。"),
        ("函数局部赋值后，外部变量是什么？", "x = 10\ndef change(x):\n    x = x + 2\n    return x\nchange(x)\nprint(x)", "10", ["12", "2", "None"], "函数内的参数 x 是局部名称；返回值未赋给外部 x，外部仍为 10。"),
        ("嵌套函数调用的结果是什么？", "def shift(n):\n    return n + 3\nprint(shift(shift(1)))", "7", ["4", "6", "9"], "内层返回 4，外层再加 3 得到 7。"),
        ("函数按分支返回，输出什么？", "def absolute(n):\n    if n < 0:\n        return -n\n    return n\nprint(absolute(-6))", "6", ["-6", "0", "None"], "参数为负数，返回其相反数 6。"),
    ],
}


def practice_bank() -> list[dict]:
    result = []
    for kp, rows in EXERCISES.items():
        for i, (stem, code, expected, distractors, explanation) in enumerate(rows):
            options = [*distractors]
            answer_index = (i + 1) % 4
            options.insert(answer_index, expected)
            result.append({"id": f"{kp}-fresh-{i+1}", "kp": kp, "type": "single", "stem": stem,
                           "code": code, "options": options, "answer": chr(65 + answer_index),
                           "explain": explanation, "difficulty": 2, "round": i // 3})
    return result
