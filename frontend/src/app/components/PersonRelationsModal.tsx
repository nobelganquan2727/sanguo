'use client';

import { Network, X } from 'lucide-react';

type RelationEvent = {
  id: string;
  title: string;
  year?: number | null;
  type?: string | null;
};

type PersonRelation = {
  person: string;
  count: number;
  events: RelationEvent[];
};

interface PersonRelationsModalProps {
  open: boolean;
  name: string;
  relations: PersonRelation[];
  loading: boolean;
  onClose: () => void;
}

export default function PersonRelationsModal({
  open,
  name,
  relations,
  loading,
  onClose,
}: PersonRelationsModalProps) {
  if (!open) return null;

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm pointer-events-auto">
      <div className="w-[620px] max-h-[78vh] bg-[#0c1821] border border-[#4a5f78] rounded-md shadow-2xl flex flex-col overflow-hidden">
        <div className="bg-gradient-to-r from-[#1a2f4c] to-[#0a1628] py-3 px-4 border-b border-[#4a5f78] flex justify-between items-center">
          <div className="flex items-center gap-2">
            <Network className="w-4 h-4 text-amber-400" />
            <h2 className="text-white font-bold text-sm">人物关系图谱</h2>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-5 border-b border-[#4a5f78]">
          <div className="text-xs text-slate-400 mb-1">中心人物</div>
          <div className="text-2xl text-amber-400 font-bold font-serif">{name}</div>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          {loading ? (
            <div className="text-sm text-slate-400 py-12 text-center">正在梳理人物交集...</div>
          ) : relations.length === 0 ? (
            <div className="text-sm text-slate-400 py-12 text-center">暂无共同事件人物。</div>
          ) : (
            <div className="flex flex-col gap-3">
              {relations.map(relation => (
                <div key={relation.person} className="rounded-md border border-[#4a5f78] bg-[#0a1526]/70 p-3">
                  <div className="flex items-center justify-between gap-3 mb-2">
                    <div className="text-base font-bold text-white">{relation.person}</div>
                    <div className="text-[10px] text-amber-300 border border-amber-500/40 rounded px-2 py-0.5">
                      共 {relation.count} 件
                    </div>
                  </div>

                  <div className="flex flex-col gap-1.5">
                    {relation.events.slice(0, 6).map(event => (
                      <div key={event.id} className="text-xs text-slate-300 leading-relaxed flex gap-2">
                        <span className="text-amber-500 font-mono shrink-0">{event.year != null ? `${event.year}年` : '不详'}</span>
                        <span>{event.title}</span>
                      </div>
                    ))}
                    {relation.events.length > 6 && (
                      <div className="text-xs text-slate-500 pt-1">还有 {relation.events.length - 6} 件共同事件...</div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="bg-[#0a1526] py-3 px-5 border-t border-[#4a5f78] flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded text-sm text-slate-300 hover:text-white hover:bg-slate-800 transition-colors"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}
