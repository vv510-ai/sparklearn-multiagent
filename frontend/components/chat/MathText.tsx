/** @jsxImportSource react */
"use client";

import ReactMarkdown from "react-markdown";
import { questionMathRemarkPlugins, mathRehypePlugins } from "@/lib/math";

/** Formula-aware text for headings, answer options and feedback. Inherit the
 * surrounding font and keep phrasing content valid inside buttons/headings. */
export default function MathText({ text }: { text: string }) {
  return <span className="math-content math-text">
    <ReactMarkdown remarkPlugins={questionMathRemarkPlugins} rehypePlugins={mathRehypePlugins}
      components={{ p: ({ children }) => <span>{children}</span>, pre: ({ children }) => <span>{children}</span> }}>
      {text}
    </ReactMarkdown>
  </span>;
}
