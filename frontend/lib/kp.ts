/** 课程知识点 id → 中文名(与 backend/app/data/knowledge_graph.json 对齐)。
 *  全站唯一来源:画像、资料、路线共用,避免各处散装映射。 */
export const KPS: [string, string][] = [
  ["complexity", "复杂度"],
  ["array", "数组"],
  ["linked_list", "链表"],
  ["stack", "栈"],
  ["queue", "队列"],
  ["recursion", "递归"],
  ["sorting_basic", "基础排序"],
  ["sorting_adv", "高级排序"],
  ["binary_tree", "二叉树"],
  ["bst", "BST"],
  ["heap", "堆"],
  ["hash", "哈希"],
  ["graph_basic", "图基础"],
  ["graph_traverse", "图遍历"],
  ["shortest_path", "最短路"],
  ["dp", "动态规划"],
];

export const KP_NAME: Record<string, string> = Object.fromEntries(KPS);

export function kpName(id: string): string {
  return KP_NAME[id] || "当前主题";
}

export function isKnownKp(id: string): boolean {
  return id in KP_NAME;
}

export function inferKpFromTopic(topic: string): string | null {
  const compact = topic.replace(/\s+/g, "").toLowerCase();
  // “优先队列”在课程图谱中属于堆。若只按中文名长度匹配，
  // “堆与优先队列”会被更长的“队列”误判为 queue。
  if (/堆与优先队列|优先队列|heap|top-?k/.test(compact)) return "heap";
  if (/(?:^|学习|了解|解释|教我|什么是)图(?:是什么|的定义|的概念|的基础|怎么(?:办|学|学习|入门|开始)|如何(?:学|学习|入门|开始)|从哪里开始)?[？?。！!]*$/.test(compact)) return "graph_basic";
  // 泛称“排序”默认从基础排序入门；更具体的高级算法必须先判定，
  // 避免“快速排序”被较短的“排序”截走。
  if (/高级排序|归并排序|快速排序|快排|堆排序|堆排|quicksort|mergesort|heapsort/.test(compact)) return "sorting_adv";
  if (/基础排序|冒泡排序|插入排序|选择排序|排序/.test(compact)) return "sorting_basic";
  const matched = KPS
    .map(([id, name]) => ({ id, name: name.replace(/\s+/g, "").toLowerCase() }))
    .filter(({ name }) => name && compact.includes(name))
    .sort((left, right) => right.name.length - left.name.length)[0];
  return matched?.id || null;
}
