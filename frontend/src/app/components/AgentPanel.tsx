'use client';

import { ReactNode, useState, useEffect, useRef } from 'react';
import { X, ChevronDown } from 'lucide-react';

interface AgentPanelProps {
  show: boolean;
  onToggle: (v: boolean) => void;
  chatHistory: { role: string; content: string; thinkingLogs?: string[] }[];
  isLoading: boolean;
  onSend: (msg: string) => void;
  onStop?: () => void;
  renderMessage: (text: string) => ReactNode;
}

export default function AgentPanel({
  show, onToggle,
  chatHistory, isLoading,
  onSend,
  onStop,
  renderMessage,
}: AgentPanelProps) {
  const [isConnected, setIsConnected] = useState<boolean>(true);
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const isAtBottomRef = useRef<boolean>(true);

  const handleScroll = () => {
    if (!chatContainerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = chatContainerRef.current;
    // If user is within 60px of the bottom, we consider them at the bottom
    const atBottom = scrollHeight - scrollTop - clientHeight < 60;
    isAtBottomRef.current = atBottom;
  };

  const scrollToBottom = (force = false) => {
    setTimeout(() => {
      if (chatContainerRef.current) {
        if (force || isAtBottomRef.current) {
          chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
        }
      }
    }, 50);
  };

  const handleSend = () => {
    const val = inputRef.current?.value || '';
    if (val.trim()) {
      onSend(val);
      if (inputRef.current) {
        inputRef.current.value = '';
      }
      isAtBottomRef.current = true;
      scrollToBottom(true);
    }
  };

  useEffect(() => {
    scrollToBottom();
  }, [chatHistory, isLoading]);

  useEffect(() => {
    if (show) {
      isAtBottomRef.current = true;
      scrollToBottom(true);
    }
  }, [show]);

  useEffect(() => {
    const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://127.0.0.1:8000';
    const checkStatus = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/status`);
        const data = await res.json();
        setIsConnected(data.status === 'connected');
      } catch (err) {
        setIsConnected(false);
      }
    };

    checkStatus();
  }, []);

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
    <div
      className="absolute right-2 bottom-3 md:right-4 md:bottom-12 z-20 w-[88vw] min-w-[280px] max-w-[340px] md:w-[32vw] md:min-w-[360px] md:max-w-[500px] h-[65vh] max-h-[360px] md:h-[72vh] md:max-h-[620px] bg-[#0a1526]/95 backdrop-blur-sm border border-[#4a5f78] rounded-md shadow-xl flex flex-col pointer-events-auto text-xs md:text-sm"
      onTouchStart={(e) => e.stopPropagation()}
      onTouchMove={(e) => e.stopPropagation()}
      onTouchEnd={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
      onWheel={(e) => e.stopPropagation()}
    >
      {/* Header */}
      <div className="bg-gradient-to-r from-[#6b1c23] to-[#8c2a35] py-1.5 md:py-2 border-b border-[#a4424b] px-3 md:px-4 flex justify-between items-center select-none">
        <h2 className="text-xs md:text-sm font-bold text-white tracking-widest">幕僚</h2>
        <div className="flex items-center gap-2">
          <div
            className={`w-2 h-2 rounded-full transition-all duration-300 ${
              isConnected
                ? 'bg-green-500 shadow-[0_0_8px_#22c55e]'
                : 'bg-red-500 shadow-[0_0_8px_#ef4444]'
            }`}
            title={isConnected ? '史料卷宗库已就绪' : '史料卷宗库连接断开'}
          />
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
      <div
        ref={chatContainerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto p-2.5 md:p-4 flex flex-col gap-2.5 md:gap-3 pointer-events-auto select-text"
      >
        {chatHistory.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`p-2 md:p-3 rounded-md text-xs md:text-sm max-w-[85%] leading-relaxed flex flex-col gap-1.5 md:gap-2 ${msg.role === 'user'
              ? 'bg-[#8c2a35] text-white border border-[#a4424b]'
              : 'bg-[#1a2f4c] border border-[#4a5f78] text-slate-300'}`}
            >
              {msg.role === 'ai' && msg.thinkingLogs && msg.thinkingLogs.length > 0 && (
                <details 
                  className="group text-[10px] md:text-xs bg-[#0c1821]/85 border border-[#4a5f78]/50 p-1.5 md:p-2 rounded text-slate-400 font-mono select-none"
                  open={msg.content === ''}
                >
                  <summary className="cursor-pointer font-bold text-slate-300 flex items-center gap-1.5 hover:text-white transition-colors list-none [&::-webkit-details-marker]:hidden">
                    <ChevronDown className="w-3.5 h-3.5 transition-transform group-open:rotate-180" />
                    <span>幕僚思索轨迹 ({msg.thinkingLogs.length} 步)</span>
                  </summary>
                  <div className="mt-1.5 md:mt-2 pl-1.5 md:pl-2 border-l border-[#a4424b] flex flex-col gap-0.5 md:gap-1 max-h-[100px] md:max-h-[140px] overflow-y-auto select-text text-[10px] md:text-[11px] leading-relaxed text-slate-400">
                    {msg.thinkingLogs.map((log, idx) => (
                      <div key={idx} className="opacity-90">{log}</div>
                    ))}
                  </div>
                </details>
              )}
              <div>
                {msg.role === 'ai' 
                  ? (msg.content ? renderMessage(msg.content) : (
                      <span className="text-slate-400 italic text-xs md:text-sm">正在编纂史册答卷...</span>
                    ))
                  : msg.content
                }
              </div>
            </div>
          </div>
        ))}
        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-[#1a2f4c] border border-[#4a5f78] p-2 md:p-3 rounded-md text-xs md:text-sm text-slate-400 flex items-center gap-1.5 md:gap-2">
              {[0, 0.1, 0.2].map((d, i) => (
                <div key={i} className="w-1.5 h-1.5 bg-amber-500 rounded-full animate-bounce" style={{ animationDelay: `${d}s` }} />
              ))}
              <span className="ml-1">臣正在翻阅史料卷宗...</span>
            </div>
          </div>
        )}
        <div className="h-6 flex-shrink-0" />
      </div>

      {/* Input */}
      <div className="p-2 md:p-3 border-t border-[#4a5f78] bg-[#0c1821] pointer-events-auto select-none">
        <div className="flex gap-1.5 md:gap-2 items-center">
          <input
            type="text"
            ref={inputRef}
            onKeyDown={e => {
              if (e.key === 'Enter') {
                handleSend();
              }
            }}
            placeholder="向幕僚提问..."
            className="flex-1 bg-[#1a2f4c] border border-[#4a5f78] rounded py-1 md:py-1.5 px-2 md:px-3 text-xs md:text-sm focus:outline-none focus:border-[#e53e3e] text-white placeholder-slate-500"
          />
          {isLoading ? (
            <button
              onClick={onStop}
              title="停止思索"
              className="px-2 md:px-3 py-1 md:py-1.5 rounded bg-orange-600 hover:bg-orange-500 text-[10px] md:text-xs text-white font-bold transition-colors flex-shrink-0"
            >
              停止
            </button>
          ) : (
            <button
              onClick={handleSend}
              className="px-2 md:px-3 py-1 md:py-1.5 rounded bg-[#8c2a35] hover:bg-[#a4424b] border border-[#a4424b] text-[10px] md:text-xs text-white font-bold transition-colors flex-shrink-0"
            >
              发送
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
