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
  ["sql_basic", "SQL 基础"],
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
  if (/sql|select|where|orderby|groupby|join|多表连接|数据库查询/.test(compact)) return "sql_basic";
  // “优先队列”在课程图谱中属于堆。若只按中文名长度匹配，
  // “堆与优先队列”会被更长的“队列”误判为 queue。
  if (/堆与优先队列|优先队列|heap|top-?k/.test(compact)) return "heap";
  if (/^(?:什么是)?图(?:是什么|的定义|的概念|的基础)?[？?。！!]*$/.test(compact)) return "graph_basic";
  const matched = KPS
    .map(([id, name]) => ({ id, name: name.replace(/\s+/g, "").toLowerCase() }))
    .filter(({ name }) => name && compact.includes(name))
    .sort((left, right) => right.name.length - left.name.length)[0];
  return matched?.id || null;
}
