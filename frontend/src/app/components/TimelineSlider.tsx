import React from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';

interface TimelineSliderProps {
  currentYear: number;
  onYearChange: (year: number) => void;
  onYearCommit: (year: number) => void;
}

export default function TimelineSlider({ currentYear, onYearChange, onYearCommit }: TimelineSliderProps) {
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
    <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-10 w-[60%] max-w-3xl">
      <div className="bg-gradient-to-r from-[#0a1628]/90 via-[#1a2f4c]/95 to-[#0a1628]/90 p-4 rounded-xl shadow-[0_4px_20px_rgba(0,0,0,0.6)] border border-[#4a5f78]/60 backdrop-blur-sm flex flex-col items-center gap-3">
        <div className="text-[#e2ddce] font-serif text-xl tracking-wider font-bold drop-shadow-md">
          {currentYear} 年
        </div>
        <div className="flex items-center gap-4 w-full px-4">
          <button
            onClick={handlePrevYear}
            disabled={currentYear <= 184}
            className="p-1.5 rounded-full bg-[#0a1628]/60 hover:bg-[#1a2f4c] text-[#8c9bab] hover:text-[#f59e0b] border border-[#4a5f78]/30 hover:border-[#f59e0b]/50 disabled:opacity-20 disabled:hover:bg-transparent disabled:hover:border-[#4a5f78]/30 disabled:text-[#8c9bab] disabled:cursor-not-allowed transition-all duration-200 cursor-pointer"
            title="前一年"
          >
            <ChevronLeft size={18} />
          </button>

          <span className="text-[#8c9bab] font-serif text-sm select-none">184年</span>
          <input
            type="range"
            min={184}
            max={280}
            value={currentYear}
            onChange={(e) => onYearChange(parseInt(e.target.value, 10))}
            onMouseUp={(e) => onYearCommit(parseInt((e.target as HTMLInputElement).value, 10))}
            onTouchEnd={(e) => onYearCommit(parseInt((e.target as HTMLInputElement).value, 10))}
            className="flex-1 h-1.5 bg-[#041527] rounded-lg appearance-none cursor-pointer focus:outline-none focus:ring-2 focus:ring-[#8c9bab]/50"
            style={{
              backgroundImage: `linear-gradient(to right, #8c9bab ${(currentYear - 184) / (280 - 184) * 100}%, transparent ${(currentYear - 184) / (280 - 184) * 100}%)`
            }}
          />
          <style dangerouslySetInnerHTML={{
            __html: `
            input[type=range]::-webkit-slider-thumb {
              appearance: none;
              width: 16px;
              height: 16px;
              border-radius: 50%;
              background: #d2cdbe;
              cursor: pointer;
              box-shadow: 0 0 5px rgba(0,0,0,0.5);
              border: 2px solid #1a2f4c;
            }
            input[type=range]::-moz-range-thumb {
              width: 16px;
              height: 16px;
              border-radius: 50%;
              background: #d2cdbe;
              cursor: pointer;
              box-shadow: 0 0 5px rgba(0,0,0,0.5);
              border: 2px solid #1a2f4c;
            }
          `}} />
          <span className="text-[#8c9bab] font-serif text-sm select-none">280年</span>

          <button
            onClick={handleNextYear}
            disabled={currentYear >= 280}
            className="p-1.5 rounded-full bg-[#0a1628]/60 hover:bg-[#1a2f4c] text-[#8c9bab] hover:text-[#f59e0b] border border-[#4a5f78]/30 hover:border-[#f59e0b]/50 disabled:opacity-20 disabled:hover:bg-transparent disabled:hover:border-[#4a5f78]/30 disabled:text-[#8c9bab] disabled:cursor-not-allowed transition-all duration-200 cursor-pointer"
            title="后一年"
          >
            <ChevronRight size={18} />
          </button>
        </div>
      </div>
    </div>
  );
}
