import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import type { Root, RootContent, Parent } from "mdast";
import type { PluggableList } from "unified";

/** Keep paired prices as prose; support the unambiguous Unicode integral
 * notation used by older saved starter assessments without changing records. */
function remarkLearnerMath() {
  return (tree: Root, file: { value: unknown }) => {
    const source = String(file.value);
    function walk(parent: Parent) {
      parent.children = parent.children.flatMap((node): RootContent[] => {
        if (node.type === "inlineMath") {
          const start = node.position?.start.offset;
          const end = node.position?.end.offset;
          if (start !== undefined && end !== undefined && /^\d/.test(node.value)
            && /^\d/.test(source.slice(end)) && !/[\\^_={}]/.test(node.value)) {
            return [{ type: "text", value: source.slice(start, end) }];
          }
        }
        if (node.type === "text") {
          const pattern = /∫([₀₁₂₃₄₅₆₇₈₉ₐ]+)([⁰¹²³⁴⁵⁶⁷⁸⁹ᵃ]+)\s*((?:\d*[a-z](?:\([a-z]\))?))\s*d([a-z])/g;
          const digits = (value: string, alphabet: string) => [...value].map(c => "0123456789a"[alphabet.indexOf(c)]).join("");
          const parts: RootContent[] = [];
          let offset = 0;
          for (const match of node.value.matchAll(pattern)) {
            const index = match.index!;
            if (index > offset) parts.push({ type: "text", value: node.value.slice(offset, index) });
            const value = `\\int_{${digits(match[1], "₀₁₂₃₄₅₆₇₈₉ₐ")}}^{${digits(match[2], "⁰¹²³⁴⁵⁶⁷⁸⁹ᵃ")}} ${match[3]}\\,\\mathrm{d}${match[4]}`;
            parts.push({ type: "inlineMath", value, data: { hName: "code", hProperties: { className: ["language-math", "math-inline"] }, hChildren: [{ type: "text", value }] } });
            offset = index + match[0].length;
          }
          if (parts.length) {
            if (offset < node.value.length) parts.push({ type: "text", value: node.value.slice(offset) });
            return parts;
          }
        }
        if ("children" in node) walk(node as Parent);
        return [node];
      }) as Parent["children"];
    }
    walk(tree);
  };
}

export const mathRemarkPlugins: PluggableList = [remarkMath, remarkLearnerMath];

/** Assessment fields were plain text. Preserve their punctuation and line
 * breaks (including Python multiplication and array syntax), replacing only
 * math nodes that the Markdown parser actually recognized outside code. */
function remarkQuestionText() {
  return (tree: Root, file: { value: unknown }) => {
    const source = String(file.value);
    const parts: RootContent[] = [];
    let offset = 0;
    function collect(parent: Parent) {
      for (const node of parent.children) {
        if (node.type === "inlineMath" || node.type === "math") {
          const start = node.position!.start.offset!;
          const end = node.position!.end.offset!;
          if (start > offset) parts.push({ type: "text", value: source.slice(offset, start) });
          parts.push({ ...node, type: "inlineMath", data: {
            hName: "code", hProperties: { className: ["language-math", node.type === "math" ? "math-display" : "math-inline"] },
            hChildren: [{ type: "text", value: node.value }],
          } });
          offset = end;
        } else if ("children" in node) collect(node as Parent);
      }
    }
    collect(tree);
    if (offset < source.length) parts.push({ type: "text", value: source.slice(offset) });
    tree.children = [{ type: "paragraph", children: parts as Parent["children"] } as RootContent];
  };
}

export const questionMathRemarkPlugins: PluggableList = [remarkMath, remarkQuestionText, remarkLearnerMath];
export const mathRehypePlugins: PluggableList = [[rehypeKatex, {
  trust: false,
  maxSize: 10,
  maxExpand: 1000,
  output: "htmlAndMathml",
}]];
