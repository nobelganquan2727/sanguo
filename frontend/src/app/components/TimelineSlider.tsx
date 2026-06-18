import React from 'react';
import { ChevronLeft, ChevronRight, EyeOff } from 'lucide-react';

interface TimelineSliderProps {
  currentYear: number;
  onYearChange: (year: number) => void;
  onYearCommit: (year: number) => void;
  onClose?: () => void;
}

export default function TimelineSlider({ currentYear, onYearChange, onYearCommit, onClose }: TimelineSliderProps) {
  const handlePrevYear = () => {
    if (currentYear > 184) {
      const nextY = currentYear - 1;
      onYearChange(nextY);
      onYearCommit(nextY);
    }
  };

  const handleNextYear = () => {
    if (currentYear < 280) {
      const nextY = currentYear + 1;
      onYearChange(nextY);
      onYearCommit(nextY);
    }
  };

  return (
    <div 
      className="absolute bottom-3 md:bottom-8 left-1/2 md:left-[32%] landscape:left-[30%] -translate-x-1/2 z-10 w-[88vw] md:w-[55vw] landscape:w-[45vw] min-w-[280px] landscape:min-w-[240px] md:min-w-[320px] max-w-2xl transition-all duration-300"
      onTouchStart={(e) => e.stopPropagation()}
      onTouchMove={(e) => e.stopPropagation()}
      onTouchEnd={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className="relative bg-gradient-to-r from-[#0a1628]/95 via-[#1a2f4c]/98 to-[#0a1628]/95 py-1.5 md:py-2 px-4 md:px-5 rounded-xl shadow-[0_4px_25px_rgba(0,0,0,0.75)] border border-[#4a5f78]/70 backdrop-blur-md flex flex-col items-center gap-1">
        {onClose && (
          <button
            onClick={onClose}
            className="absolute top-2 right-3.5 text-[#8c9bab] hover:text-[#f59e0b] p-0.5 rounded hover:bg-[#1a2f4c]/50 transition-all duration-200 cursor-pointer"
            title="隐藏时间轴"
          >
            <EyeOff size={13} />
          </button>
        )}

        <div className="text-[#e2ddce] font-serif text-base tracking-wider font-bold drop-shadow-md select-none leading-none">
          {currentYear} 年
        </div>
        <div className="flex items-center gap-3 w-full px-2">
          <button
            onClick={handlePrevYear}
            disabled={currentYear <= 184}
            className="p-1 rounded-full bg-[#0a1628]/60 hover:bg-[#1a2f4c] text-[#8c9bab] hover:text-[#f59e0b] border border-[#4a5f78]/30 hover:border-[#f59e0b]/50 disabled:opacity-20 disabled:hover:bg-transparent disabled:hover:border-[#4a5f78]/30 disabled:text-[#8c9bab] disabled:cursor-not-allowed transition-all duration-200 cursor-pointer"
            title="前一年"
          >
            <ChevronLeft size={16} />
          </button>

          <span className="text-[#8c9bab] font-serif text-xs select-none">184年</span>
          <input
            type="range"
            min={184}
            max={280}
            value={currentYear}
            onChange={(e) => onYearChange(parseInt(e.target.value, 10))}
            onMouseUp={(e) => onYearCommit(parseInt((e.target as HTMLInputElement).value, 10))}
            onTouchEnd={(e) => onYearCommit(parseInt((e.target as HTMLInputElement).value, 10))}
            className="flex-1 h-1 bg-[#041527] rounded-lg appearance-none cursor-pointer focus:outline-none focus:ring-1 focus:ring-[#8c9bab]/30"
            style={{
              backgroundImage: `linear-gradient(to right, #8c9bab ${(currentYear - 184) / (280 - 184) * 100}%, transparent ${(currentYear - 184) / (280 - 184) * 100}%)`
            }}
          />
          <style dangerouslySetInnerHTML={{
            __html: `
            input[type=range]::-webkit-slider-thumb {
              appearance: none;
              width: 12px;
              height: 12px;
              border-radius: 50%;
              background: #d2cdbe;
              cursor: pointer;
              box-shadow: 0 0 4px rgba(0,0,0,0.5);
              border: 1.5px solid #1a2f4c;
            }
            input[type=range]::-moz-range-thumb {
              width: 12px;
              height: 12px;
              border-radius: 50%;
              background: #d2cdbe;
              cursor: pointer;
              box-shadow: 0 0 4px rgba(0,0,0,0.5);
              border: 1.5px solid #1a2f4c;
            }
          `}} />
          <span className="text-[#8c9bab] font-serif text-xs select-none">280年</span>

          <button
            onClick={handleNextYear}
            disabled={currentYear >= 280}
            className="p-1 rounded-full bg-[#0a1628]/60 hover:bg-[#1a2f4c] text-[#8c9bab] hover:text-[#f59e0b] border border-[#4a5f78]/30 hover:border-[#f59e0b]/50 disabled:opacity-20 disabled:hover:bg-transparent disabled:hover:border-[#4a5f78]/30 disabled:text-[#8c9bab] disabled:cursor-not-allowed transition-all duration-200 cursor-pointer"
            title="后一年"
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}
