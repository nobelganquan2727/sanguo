'use client';

import React from 'react';

export function useLinkify(
  allPersons: string[],
  allLocationNames: string[],
  onPersonClick: (name: string) => void,
  onLocationClick: (name: string) => void,
) {
  /** 在纯文本中高亮人名（可点击，用于 tooltip desc） */
  const linkifyText = (text: string) => {
    if (!text || allPersons.length === 0) return <>{text}</>;
    const escaped = allPersons.map(p => p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    const regex = new RegExp(`(${escaped.join('|')})`, 'g');
    const parts = text.split(regex);
    return (
      <>
        {parts.map((part, i) =>
          allPersons.includes(part)
            ? (
              <span
                key={i}
                onClick={() => onPersonClick(part)}
                className="text-amber-400 underline cursor-pointer hover:text-amber-200 font-semibold transition-colors"
                title={`查看${part}的人物关系`}
              >
                {part}
              </span>
            )
            : <React.Fragment key={i}>{part}</React.Fragment>
        )}
      </>
    );
  };

  /** 仅对普通字符串应用人名和地名的匹配跳转 */
  const linkifyString = (text: string) => {
    if (!text) return <>{text}</>;
    const allTerms = [
      ...allPersons.map(w => ({ w, t: 'person' as const })),
      ...allLocationNames.map(w => ({ w, t: 'location' as const })),
    ].sort((a, b) => b.w.length - a.w.length);
    if (allTerms.length === 0) return <>{text}</>;
    const escaped = allTerms.map(({ w }) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    const regex = new RegExp(`(${escaped.join('|')})`, 'g');
    const parts = text.split(regex);
    return (
      <>
        {parts.map((part, i) => {
          const match = allTerms.find(({ w }) => w === part);
          if (!match) return <React.Fragment key={i}>{part}</React.Fragment>;
          if (match.t === 'person') {
            return (
              <span
                key={i}
                onClick={() => onPersonClick(part)}
                className="text-amber-400 underline cursor-pointer hover:text-amber-200 font-semibold transition-colors"
                title={`查看${part}的人物关系`}
              >
                {part}
              </span>
            );
          }
          return (
            <span
              key={i}
              onClick={() => onLocationClick(part)}
              className="text-cyan-400 underline cursor-pointer hover:text-cyan-200 font-semibold transition-colors"
              title={`跳转到${part}`}
            >
              {part}
            </span>
          );
        })}
      </>
    );
  };

  /** 处理内联 Markdown，如加粗 **text** */
  const renderInline = (text: string) => {
    const parts = text.split(/(\*\*.*?\*\*)/g);
    return (
      <>
        {parts.map((part, i) => {
          if (part.startsWith('**') && part.endsWith('**')) {
            return <strong key={i} className="font-bold text-white">{linkifyString(part.slice(2, -2))}</strong>;
          }
          return <React.Fragment key={i}>{linkifyString(part)}</React.Fragment>;
        })}
      </>
    );
  };

  /** 在 agent 回复中处理段落、加粗、标题、列表等简单 markdown，并高亮人名地名 */
  const linkifyChatText = (text: string) => {
    if (!text) return <>{text}</>;
    const lines = text.split('\n');
    
    return (
      <div className="flex flex-col gap-2">
        {lines.map((line, index) => {
          if (!line.trim()) return null;
          if (line.startsWith('### ')) {
            return <h3 key={index} className="text-[15px] font-bold mt-2 mb-1 text-amber-500">{renderInline(line.substring(4))}</h3>;
          }
          if (line.startsWith('## ')) {
            return <h2 key={index} className="text-base font-bold mt-3 mb-1 text-amber-500">{renderInline(line.substring(3))}</h2>;
          }
          if (line.startsWith('# ')) {
            return <h1 key={index} className="text-lg font-bold mt-4 mb-2 text-amber-500">{renderInline(line.substring(2))}</h1>;
          }
          if (line.match(/^[\*\-]\s/)) {
            return <div key={index} className="ml-3 flex gap-2"><span className="text-amber-500">•</span><div>{renderInline(line.substring(2))}</div></div>;
          }
          const listMatch = line.match(/^(\d+\.)\s(.*)/);
          if (listMatch) {
            return <div key={index} className="ml-1 flex gap-2"><span className="text-amber-500 font-mono shrink-0">{listMatch[1]}</span><div>{renderInline(listMatch[2])}</div></div>;
          }
          return <div key={index} className="leading-relaxed">{renderInline(line)}</div>;
        })}
      </div>
    );
  };

  return { linkifyText, linkifyChatText };
}
