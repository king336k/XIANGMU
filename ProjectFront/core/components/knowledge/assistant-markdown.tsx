// SPDX-License-Identifier: AGPL-3.0-only
import type { ReactNode } from "react";

// Deliberately small Markdown subset: React escapes every text node. No HTML parsing,
// image elements, plugins or conversion to an HTML string is involved.
function safeLink(value: string): string | undefined {
  if (!/^https?:\/\//i.test(value) || Array.from(value).some((character) => character.charCodeAt(0) <= 32))
    return undefined;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : undefined;
  } catch {
    return undefined;
  }
}

function inline(text: string): ReactNode[] {
  const parts: ReactNode[] = [];
  const tokens = /!\[([^\]]*)\]\([^\n)]*\)|\[([^\]]+)\]\(([^\s)]+)\)|`([^`\n]+)`|\*\*([^*\n]+)\*\*/g;
  let offset = 0;
  for (const match of text.matchAll(tokens)) {
    if (match.index > offset) parts.push(text.slice(offset, match.index));
    const key = `${match.index}-${match[0]}`;
    if (match[0].startsWith("!"))
      parts.push(
        <span key={key} className="text-12 text-tertiary">
          [外部图片已隐藏]
        </span>
      );
    else if (match[2]) {
      const href = safeLink(match[3]);
      parts.push(
        href ? (
          <a key={key} href={href} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">
            {match[2]}
          </a>
        ) : (
          match[2]
        )
      );
    } else if (match[4])
      parts.push(
        <code key={key} className="font-mono rounded bg-layer-1 px-1 py-0.5 text-12">
          {match[4]}
        </code>
      );
    else parts.push(<strong key={key}>{match[5]}</strong>);
    offset = match.index + match[0].length;
  }
  if (offset < text.length) parts.push(text.slice(offset));
  return parts;
}

const listLine = /^\s{0,3}([-+*]|\d+\.)\s+(.+)$/;
const headingLine = /^\s{0,3}#{1,6}\s+(.+)$/;
const fenceLine = /^\s{0,3}(`{3,}|~{3,})(.*)$/;
const startsBlock = (line: string) =>
  !line.trim() || fenceLine.test(line) || headingLine.test(line) || listLine.test(line) || /^\s{0,3}>\s?/.test(line);

export function AssistantMarkdown({ content }: { content: string }) {
  const lines = content.replace(/\r\n?/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let cursor = 0;
  while (cursor < lines.length) {
    const start = cursor;
    const line = lines[cursor];
    if (!line.trim()) {
      cursor++;
      continue;
    }
    const fence = line.match(fenceLine);
    const heading = line.match(headingLine);
    const list = line.match(listLine);
    if (fence) {
      const code: string[] = [];
      const close = new RegExp(`^\\s{0,3}${fence[1][0]}{${fence[1].length},}\\s*$`);
      cursor++;
      while (cursor < lines.length && !close.test(lines[cursor])) code.push(lines[cursor++]);
      if (cursor < lines.length) cursor++;
      blocks.push(
        <pre
          key={`code-${start}`}
          className="font-mono my-3 max-w-full overflow-x-auto rounded-md border border-subtle bg-layer-1 p-3 text-12 leading-6 [overflow-wrap:normal] whitespace-pre"
        >
          <code>{code.join("\n")}</code>
        </pre>
      );
    } else if (heading) {
      blocks.push(
        <h3 key={`heading-${start}`} className="mt-3 font-semibold">
          {inline(heading[1])}
        </h3>
      );
      cursor++;
    } else if (list) {
      const ordered = /\d/.test(list[1]);
      const items: ReactNode[] = [];
      let item: RegExpMatchArray | null;
      while (cursor < lines.length && (item = lines[cursor].match(listLine)) && /\d/.test(item[1]) === ordered) {
        items.push(<li key={`item-${cursor}`}>{inline(item[2])}</li>);
        cursor++;
      }
      blocks.push(
        ordered ? (
          <ol key={`list-${start}`} start={Number.parseInt(list[1], 10)}>
            {items}
          </ol>
        ) : (
          <ul key={`list-${start}`}>{items}</ul>
        )
      );
    } else if (/^\s{0,3}>\s?/.test(line)) {
      const quote: string[] = [];
      while (cursor < lines.length && /^\s{0,3}>\s?/.test(lines[cursor]))
        quote.push(lines[cursor++].replace(/^\s{0,3}>\s?/, ""));
      blocks.push(<blockquote key={`quote-${start}`}>{inline(quote.join("\n"))}</blockquote>);
    } else {
      const paragraph = [line];
      cursor++;
      while (cursor < lines.length && !startsBlock(lines[cursor])) paragraph.push(lines[cursor++]);
      blocks.push(
        <p key={`paragraph-${start}`} className="whitespace-pre-wrap">
          {inline(paragraph.join("\n"))}
        </p>
      );
    }
  }
  return <>{blocks}</>;
}
