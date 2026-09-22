/** Optional, goal-led orientation shared by intake and the learning studio. */
export default function FeatureGuide() {
  return <details className="feature-guide">
    <summary>先了解这些按钮怎么帮我（可选）</summary>
    <p>先从中间的学习对话提一个问题，暂时不用记住所有按钮。</p>
    <ol>
      <li><strong>准备学习：</strong>在「学习来源」选择书本、上传资料；不知道从哪开始，可以做「起点测评与计划」。</li>
      <li><strong>解决卡点：</strong>直接提问或点「互动讲解」；想看视频课用「推荐网课」，需要查证更多材料用「深度研究」。</li>
      <li><strong>聊过一段再整理：</strong>「一图看懂」收拢当前主题，「框架导图」串联本次对话，「学习笔记」保留详细解释。</li>
      <li><strong>检验与复习：</strong>用「巩固测验」独立尝试，再用「记忆闪卡」回忆；生成的内容可在「资料归档」继续查看。</li>
    </ol>
    <p>其余功能在「展开全部工具」里，随时可用。提醒可以跳过，学习节奏由你决定。</p>
  </details>;
}
