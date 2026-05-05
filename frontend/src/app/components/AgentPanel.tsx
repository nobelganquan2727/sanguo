'use client';

import { ReactNode } from 'react';
import { X, ChevronDown } from 'lucide-react';

interface AgentPanelProps {
  show: boolean;
  onToggle: (v: boolean) => void;
  chatHistory: { role: string; content: string }[];
  isLoading: boolean;
  chatInput: string;
  setChatInput: (v: string) => void;
  onSend: (msg: string) => void;
  renderMessage: (text: string) => ReactNode;
}

export default function AgentPanel({
  show, onToggle,
  chatHistory, isLoading,
  chatInput, setChatInput, onSend,
  renderMessage,
}: AgentPanelProps) {
  if (!show) {
    return (
      <button
        onClick={() => onToggle(true)}
        className="absolute right-4 bottom-12 z-20 flex items-center gap-1 rounded-md border border-[#4a5f78] bg-[#0a1526]/90 px-2.5 py-1.5 text-xs text-slate-200 hover:text-white hover:border-slate-400 transition-colors"
        title="展开幕僚"
      >
        <ChevronDown className="w-3.5 h-3.5 rotate-90" />
        幕僚
      </button>
    );
  }

  return (
    <div className="absolute right-4 bottom-12 z-20 w-[340px] bg-[#0a1526]/95 backdrop-blur-sm border border-[#4a5f78] rounded-md shadow-xl flex flex-col max-h-[580px] select-none">
      {/* Header */}
      <div className="bg-gradient-to-r from-[#6b1c23] to-[#8c2a35] py-2 border-b border-[#a4424b] px-4 flex justify-between items-center">
        <h2 className="text-sm font-bold text-white tracking-widest">幕僚</h2>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-green-400 font-mono">Neo4j</span>
          <div className="w-2 h-2 rounded-full bg-green-500 shadow-[0_0_8px_#22c55e]" />
          <button
            onClick={() => onToggle(false)}
            title="隐藏幕僚"
            className="ml-1 p-1 rounded text-slate-300 hover:text-white hover:bg-slate-700/60 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Chat history */}
      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3 pointer-events-auto">
        {chatHistory.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`p-3 rounded-md text-sm max-w-[85%] leading-relaxed ${msg.role === 'user'
              ? 'bg-[#8c2a35] text-white border border-[#a4424b]'
              : 'bg-[#1a2f4c] border border-[#4a5f78] text-slate-300'}`}
            >
              {msg.role === 'ai' ? renderMessage(msg.content) : msg.content}
            </div>
          </div>
        ))}
        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-[#1a2f4c] border border-[#4a5f78] p-3 rounded-md text-sm text-slate-400 flex items-center gap-2">
              {[0, 0.1, 0.2].map((d, i) => (
                <div key={i} className="w-1.5 h-1.5 bg-amber-500 rounded-full animate-bounce" style={{ animationDelay: `${d}s` }} />
              ))}
              <span className="ml-1">臣正在翻阅史料卷宗...</span>
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="p-3 border-t border-[#4a5f78] bg-[#0c1821] pointer-events-auto">
        <input
          type="text"
          value={chatInput}
          onChange={e => setChatInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && onSend(chatInput)}
          placeholder="向幕僚提问..."
          className="w-full bg-[#1a2f4c] border border-[#4a5f78] rounded py-2 px-3 text-sm focus:outline-none focus:border-[#e53e3e] text-white placeholder-slate-500"
        />
      </div>
    </div>
  );
}
