export function withoutCodeBlocks(text: string, keepMermaid = false): string {
  const withoutHtmlCode = String(text || "").replace(/<pre\b[^>]*>[\s\S]*?<\/pre>/gi, "");
  const withoutFences = withoutHtmlCode.replace(
    /(```|~~~)([^\n]*)\n([\s\S]*?)\1/g,
    (block, _fence: string, info: string, body: string) => {
      const language = info.trim().split(/\s+/, 1)[0]?.toLowerCase();
      if (keepMermaid && language === "mermaid") return block;
      // Plain-text fences often contain worked steps, not executable code.
      return !language || ["text", "txt", "plaintext"].includes(language) ? body : "";
    },
  );
  const codeLine = /^\s*(?:(?:async\s+def|def|class)\s+[A-Za-z_]\w*\s*(?:\(|:)|(?:import\s+[A-Za-z_]|from\s+[A-Za-z_.]+\s+import\b)|(?:return|yield|raise)\b|(?:if|elif|for|while|with)\s+.+:|(?:else|try)\s*:|[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\([^)]*\))\s*(?:#.*)?$/i;
  const inlineCode = /\b(?:async\s+def|def|class)\s+[A-Za-z_]\w*\s*(?:\(|:)/i;
  const lines = withoutFences.split("\n");
  if (lines.some((line) => codeLine.test(line) || inlineCode.test(line))) {
    let skippingIndented = false;
    const readable: string[] = [];
    for (const line of lines) {
      if (codeLine.test(line) || inlineCode.test(line)) {
        skippingIndented = true;
        continue;
      }
      if (skippingIndented && (!line.trim() || /^[ \t]/.test(line))) continue;
      skippingIndented = false;
      readable.push(line);
    }
    return readable.join("\n").replace(/\n{3,}/g, "\n\n").trim();
  }
  return withoutFences.replace(/\n{3,}/g, "\n\n").trim();
}
