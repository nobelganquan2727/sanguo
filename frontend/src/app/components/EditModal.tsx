'use client';

import { useState } from 'react';
import { Check, CheckCircle, ChevronDown, X } from 'lucide-react';

interface EditModalProps {
  open: boolean;
  target: any;
  editField: 'locations' | 'std_start_year';
  setEditField: (f: 'locations' | 'std_start_year') => void;
  editValue: string;
  setEditValue: (v: string) => void;
  onClose: () => void;
  onSubmit: () => void;
}

export default function EditModal({
  open, target, editField, setEditField, editValue, setEditValue, onClose, onSubmit,
}: EditModalProps) {
  const [fieldMenuOpen, setFieldMenuOpen] = useState(false);

  if (!open || !target) return null;

  const fieldOptions = [
    { value: 'locations' as const, label: '地点（多个地点请用逗号分隔）' },
    { value: 'std_start_year' as const, label: '发生年份（如：190）' },
  ];

  const currentField = fieldOptions.find(option => option.value === editField) ?? fieldOptions[0];

  const selectField = (value: 'locations' | 'std_start_year') => {
    setEditField(value);
    setFieldMenuOpen(false);
    if (value === 'locations') {
      setEditValue(target.locations?.map((l: any) => typeof l === 'object' ? l.name : l).join(',') || '');
    } else {
      setEditValue(target.year != null ? String(target.year) : '');
    }
  };

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm pointer-events-auto">
      <div className="w-[400px] bg-[#0c1821] border border-[#4a5f78] rounded-md shadow-2xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="bg-gradient-to-r from-[#1a2f4c] to-[#0a1628] py-3 px-4 border-b border-[#4a5f78] flex justify-between items-center">
          <h2 className="text-white font-bold text-sm">提交数据修正</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-5 flex flex-col gap-4">
          <div>
            <div className="text-xs text-slate-400 mb-1">正在修正事件：</div>
            <div className="text-sm text-amber-400 font-bold">{target.title}</div>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs text-slate-400">选择要修正的字段</label>
            <div className="relative">
              <button
                type="button"
                onClick={() => setFieldMenuOpen(open => !open)}
                className={`w-full bg-[#1a2f4c] border rounded py-2 px-3 text-sm text-white focus:outline-none transition-colors flex items-center justify-between text-left ${
                  fieldMenuOpen ? 'border-amber-500 shadow-[0_0_0_1px_rgba(245,158,11,0.45)]' : 'border-[#4a5f78] hover:border-[#6d87a5]'
                }`}
              >
                <span>{currentField.label}</span>
                <ChevronDown className={`w-4 h-4 text-slate-400 transition-transform ${fieldMenuOpen ? 'rotate-180 text-amber-400' : ''}`} />
              </button>

              {fieldMenuOpen && (
                <div className="absolute left-0 right-0 top-[calc(100%+6px)] z-10 overflow-hidden rounded-md border border-[#4a5f78] bg-[#0a1526] shadow-[0_12px_30px_rgba(0,0,0,0.45)]">
                  {fieldOptions.map(option => {
                    const selected = option.value === editField;
                    return (
                      <button
                        key={option.value}
                        type="button"
                        onClick={() => selectField(option.value)}
                        className={`w-full px-3 py-2.5 text-left text-sm transition-colors flex items-center gap-2 ${
                          selected
                            ? 'bg-amber-500/15 text-amber-300'
                            : 'text-slate-300 hover:bg-[#1a2f4c] hover:text-white'
                        }`}
                      >
                        <Check className={`w-4 h-4 ${selected ? 'opacity-100' : 'opacity-0'}`} />
                        <span>{option.label}</span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs text-slate-400">新的修正值</label>
            <input
              type="text"
              value={editValue}
              onChange={e => setEditValue(e.target.value)}
              placeholder={editField === 'locations' ? '如: 洛阳,许昌' : '如: 190'}
              className="w-full bg-[#1a2f4c] border border-[#4a5f78] rounded py-2 px-3 text-sm text-white focus:outline-none focus:border-amber-500"
            />
          </div>
        </div>

        {/* Footer */}
        <div className="bg-[#0a1526] py-3 px-5 border-t border-[#4a5f78] flex justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded text-sm text-slate-300 hover:text-white hover:bg-slate-800 transition-colors"
          >
            取消
          </button>
          <button
            onClick={onSubmit}
            className="px-4 py-1.5 rounded text-sm bg-amber-500 text-slate-900 font-bold hover:bg-amber-400 transition-colors flex items-center gap-2"
          >
            <CheckCircle className="w-4 h-4" /> 提交
          </button>
        </div>
      </div>
    </div>
  );
}
