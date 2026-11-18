// SPDX-License-Identifier: AGPL-3.0-only
const evidenceText =
  /(?:https?:\/\/|(?:\/[\w.-]+){2,}|--[a-z]|\b[a-f0-9]{32,}\b|\b(?:ROSA|RAI|HolmesGPT|Holmes|argv|sha256)\b)/i;
const qualification = /尚未|未确认|待现场|需现场|无法确认|未验证|未执行|不能确认|仅.*模拟|不代表.*实机/;

/** Select source sentences only; detailed evidence stays available unchanged. */
export function compactReportText(value: string, limit = 240): string {
  const sentences = value
    .replace(/```[\s\S]*?```/g, "")
    .split(/(?<=[。！？；])\s*|\n+/)
    .map((line) =>
      line
        .replace(/^\s*(?:#{1,6}\s*|[-*]\s+|\d+[.、]\s*)/, "")
        .replace(/\*\*|`/g, "")
        .trim()
    )
    .filter((line) => line && !/^[。；，、！？\s]+$/.test(line) && !evidenceText.test(line));
  const picked: string[] = [];
  for (const sentence of sentences) {
    if (picked.length >= 2) break;
    if (sentence.length > limit || picked.join("").length + sentence.length > limit) continue;
    picked.push(sentence);
  }
  const caution = sentences.find((line) => qualification.test(line));
  if (caution && !picked.includes(caution)) picked.push(caution);
  return picked.join(" ") || "请查看详细证据。";
}

export function reportSections(content: string): { label: string; text: string }[] {
  const names: Record<string, string> = {
    结论: "结论",
    原因与证据: "原因",
    已执行操作: "处理",
    修改位置: "位置",
    复测: "复测",
    后续方案: "下一步",
  };
  const sections: { label: string; text: string }[] = [];
  for (const line of content.split("\n").slice(1)) {
    if (line.trim() === "详细证据与处理过程：") break;
    const match = /^(结论|原因与证据|已执行操作|修改位置|复测|后续方案)：(.*)$/.exec(line);
    if (match) sections.push({ label: names[match[1]], text: match[2] });
    else if (sections.length) sections[sections.length - 1].text += `\n${line}`;
  }
  const hasEditorialSummary = content.includes("\n详细证据与处理过程：");
  return sections.map((section) => ({
    label: section.label,
    text: hasEditorialSummary || section.label === "位置" ? section.text.trim() : compactReportText(section.text),
  }));
}
