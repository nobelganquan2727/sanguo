'use client';

import React from 'react';

export function useLinkify(
  allPersons: string[],
  allLocationNames: string[],
  onPersonClick: (name: string) => void,
  onLocationClick: (name: string) => void,
) {
  /** 在纯文本中高亮人名（无点击，用于 tooltip desc） */
  const linkifyText = (text: string) => {
    if (!text || allPersons.length === 0) return <>{text}</>;
    const escaped = allPersons.map(p => p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    const regex = new RegExp(`(${escaped.join('|')})`, 'g');
    const parts = text.split(regex);
    return (
      <>
        {parts.map((part, i) =>
          allPersons.includes(part)
            ? <span key={i} className="text-amber-400 font-semibold">{part}</span>
            : <React.Fragment key={i}>{part}</React.Fragment>
        )}
      </>
    );
  };

  /** 在 agent 回复中高亮人名（可点击）+ 地名（可点击跳转） */
  const linkifyChatText = (text: string) => {
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
                title={`查看${part}的事件`}
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

  return { linkifyText, linkifyChatText };
}
