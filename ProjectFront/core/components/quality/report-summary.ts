// SPDX-License-Identifier: AGPL-3.0-only
const evidenceText = /(?:https?:\/\/|--[a-z]|\b[a-f0-9]{32,}\b|\b(?:ROSA|RAI|HolmesGPT|Holmes|argv|sha256)\b)/i;
const qualification = /尚未|未确认|待现场|需现场|无法确认|未验证|未执行|不能确认|仅.*模拟|不代表.*实机/;

/** Keep source lines readable; technical bytes remain unchanged behind disclosure. */
export function reportEvidence(value: string) {
  const technical =
    /(?:\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b|\b[0-9a-f]{32,}\b|\b(?:run_id|command_id|agent_run|repair_locations|expected_sha256|sha256)\b|platform:[a-z_]+|^\s*(?:[[\]{}]|```)|^\s*["'][a-z_]+["']\s*:|^\s*(?:state|status|repaired|verified|validation_state|actual_write|target_revision_stable|exit_code|ok|failed|runtime_failure_present)\s*[:=])/i;
  let fenced = false;
  const readable = value
    .split(/\r?\n/)
    .filter((line) => {
      if (/^\s*```/.test(line)) {
        fenced = !fenced;
        return false;
      }
      return !fenced && !technical.test(line);
    })
    .join("\n")
    .trim();
  return { readable, original: value, hasTechnical: readable !== value.trim() };
}

/** Select source sentences only; detailed evidence stays available unchanged. */
export function compactReportText(value: string, limit = 240): string {
  const professional = new Map<string, string>();
  for (const line of reportEvidence(value).readable.split("\n")) {
    const clean = line
      .replace(/^\s*(?:#{1,6}\s*|[-*]\s+|\d+[.、]\s*)/, "")
      .replace(/\*\*|`/g, "")
      .trim();
    if (/^(?:详细证据与处理过程|详细依据)[:：]/.test(clean)) break;
    const point = /^(故障|已处理|待验证|当前检查|历史处理|问题|原因|处理|验证)[:：]\s*(.+)$/.exec(clean);
    if (point && !professional.has(point[1])) professional.set(point[1], point[2]);
  }
  if (
    [...professional.keys()].some((label) => ["故障", "已处理", "待验证", "当前检查", "历史处理"].includes(label)) ||
    ["问题", "原因", "处理", "验证"].every((label) => professional.has(label))
  )
    return [...professional].map(([label, text]) => `${label}：${text}`).join("\n");
  const sentences = reportEvidence(value)
    .readable.replace(/```[\s\S]*?```/g, "")
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
  for (const location of sentences.filter((line) => /^(?:修改位置|配置位置|文件位置|位置)[:：]/.test(line))) {
    if (!picked.includes(location)) picked.push(location);
  }
  return picked.join(" ") || "请查看详细证据。";
}

export function reportSections(content: string): { label: string; text: string }[] {
  const names: Record<string, string> = {
    故障: "故障",
    已处理: "已处理",
    待验证: "待验证",
    当前检查: "当前检查",
    历史处理: "历史处理",
    问题: "问题",
    原因: "原因",
    处理: "处理",
    验证: "验证",
    结论: "结论",
    原因与证据: "原因",
    已执行操作: "处理",
    修改位置: "位置",
    复测: "复测",
    后续方案: "下一步",
  };
  const sections: { label: string; text: string }[] = [];
  for (const line of content.split("\n").slice(1)) {
    const clean = line
      .replace(/^\s*(?:#{1,6}\s*|[-*]\s+)/, "")
      .replace(/\*\*|`/g, "")
      .trim();
    if (/^(?:详细证据与处理过程|详细依据)[:：]/.test(clean)) break;
    const match =
      /^(故障|已处理|待验证|当前检查|历史处理|问题|原因|处理|验证|结论|原因与证据|已执行操作|修改位置|复测|后续方案)[:：](.*)$/.exec(
        clean
      );
    if (match) sections.push({ label: names[match[1]], text: match[2] });
    else if (sections.length) sections[sections.length - 1].text += `\n${line}`;
  }
  const hasEditorialSummary = content.includes("\n详细证据与处理过程：");
  return sections.map((section) => ({
    label: section.label,
    text:
      hasEditorialSummary || section.label === "位置"
        ? reportEvidence(section.text).readable
        : compactReportText(section.text),
  }));
}
