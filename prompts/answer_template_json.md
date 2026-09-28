【历史对话】
${history}

【检索片段】
${context}

【用户问题】
${question}

请只输出一个 JSON 对象（不要输出任何解释、前后缀或 Markdown 代码块），字段与取值如下：
{
  "answer_type": "answered 或 not_found 或 clarify",
  "answer": "给用户看的简体中文答案，含 [编号] 引用标记，不超过 200 字",
  "citation_ids": [1, 2],
  "confidence": "high 或 medium 或 low"
}

规则：
1. answer_type 为 not_found 时，answer 必须是系统提示词中的固定兜底话术，citation_ids 必须为空数组 []。
2. citation_ids 只能包含【检索片段】中真实存在的编号，且必须与 answer 中的 [编号] 完全一致。
3. answered：所有事实来自片段；clarify：问题宽泛、需要补充信息时，在 answer 中说明需要补充什么。
4. 只输出 JSON，不要输出 JSON 以外的任何字符。
