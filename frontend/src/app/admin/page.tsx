'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import {
  Lock,
  Unlock,
  Settings,
  Check,
  Trash2,
  Edit3,
  RefreshCw,
  ArrowLeft,
  Database,
  AlertCircle,
  CheckCircle2,
  MapPin,
  Calendar,
  FileText
} from 'lucide-react';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://127.0.0.1:8000';

interface Feedback {
  id: number;
  event_id: string;
  event_title: string;
  field_name: string;
  proposed_value: string;
  status: string;
  created_at: string;
}

interface Toast {
  type: 'success' | 'error';
  message: string;
}

export default function AdminPage() {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [password, setPassword] = useState<string>('');
  const [authError, setAuthError] = useState<string>('');
  const [feedbacks, setFeedbacks] = useState<Feedback[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [editedValues, setEditedValues] = useState<{ [key: number]: string }>({});
  const [toast, setToast] = useState<Toast | null>(null);
  const [bulkActionLoading, setBulkActionLoading] = useState<boolean>(false);

  // Load password from sessionStorage if exists
  useEffect(() => {
    const savedPass = sessionStorage.getItem('admin_password');
    if (savedPass) {
      verifyPassword(savedPass);
    }
  }, []);

  const showToast = (message: string, type: 'success' | 'error' = 'success') => {
    setToast({ message, type });
    setTimeout(() => {
      setToast(null);
    }, 4000);
  };

  const verifyPassword = async (pwdToVerify: string) => {
    setLoading(true);
    setAuthError('');
    try {
      const res = await fetch(`${API_BASE}/api/admin/feedback`, {
        headers: {
          'X-Admin-Password': pwdToVerify,
        },
      });

      if (res.ok) {
        const data = await res.json();
        setFeedbacks(data.feedbacks || []);
        setIsAuthenticated(true);
        sessionStorage.setItem('admin_password', pwdToVerify);
      } else {
        const err = await res.json();
        setAuthError(err.detail || '密码校验失败，请重试');
        sessionStorage.removeItem('admin_password');
      }
    } catch (err) {
      setAuthError('连接服务器失败，请确保后端已启动');
    } finally {
      setLoading(false);
    }
  };

  const handleLoginSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!password.trim()) {
      setAuthError('密码不能为空');
      return;
    }
    verifyPassword(password.trim());
  };

  const handleSignOut = () => {
    sessionStorage.removeItem('admin_password');
    setIsAuthenticated(false);
    setPassword('');
    setFeedbacks([]);
    setSelectedIds(new Set());
  };

  const fetchPendingFeedbacks = async () => {
    const savedPass = sessionStorage.getItem('admin_password');
    if (!savedPass) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/admin/feedback`, {
        headers: {
          'X-Admin-Password': savedPass,
        },
      });
      if (res.ok) {
        const data = await res.json();
        setFeedbacks(data.feedbacks || []);
        setSelectedIds(new Set());
      } else {
        showToast('获取反馈列表失败', 'error');
      }
    } catch (err) {
      showToast('获取反馈列表失败，请重试', 'error');
    } finally {
      setLoading(false);
    }
  };

  const toggleSelect = (id: number) => {
    const next = new Set(selectedIds);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    setSelectedIds(next);
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === feedbacks.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(feedbacks.map(f => f.id)));
    }
  };

  const handleInlineValChange = (id: number, val: string) => {
    setEditedValues(prev => ({
      ...prev,
      [id]: val
    }));
  };

  const handleSingleApply = async (fb: Feedback) => {
    const savedPass = sessionStorage.getItem('admin_password');
    if (!savedPass) return;

    const finalVal = editedValues[fb.id] !== undefined ? editedValues[fb.id] : fb.proposed_value;

    setBulkActionLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/admin/feedback/apply`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Password': savedPass,
        },
        body: JSON.stringify({
          items: [{
            id: fb.id,
            event_id: fb.event_id,
            field_name: fb.field_name,
            proposed_value: finalVal
          }]
        }),
      });

      const data = await res.json();
      if (res.ok && data.success) {
        showToast(`已成功应用事件 [${fb.event_title}] 的修正`);
        fetchPendingFeedbacks();
      } else {
        showToast(data.message || '应用修改失败', 'error');
      }
    } catch (err) {
      showToast('网络请求异常，请检查后端', 'error');
    } finally {
      setBulkActionLoading(false);
    }
  };

  const handleSingleDelete = async (id: number, title: string) => {
    const savedPass = sessionStorage.getItem('admin_password');
    if (!savedPass) return;

    if (!confirm(`确定要忽略/删除该条对于事件 [${title}] 的修正吗？`)) {
      return;
    }

    setBulkActionLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/admin/feedback/delete`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Password': savedPass,
        },
        body: JSON.stringify({ ids: [id] }),
      });

      if (res.ok) {
        showToast('修正已删除/忽略');
        fetchPendingFeedbacks();
      } else {
        showToast('删除失败', 'error');
      }
    } catch (err) {
      showToast('网络请求异常，请重试', 'error');
    } finally {
      setBulkActionLoading(false);
    }
  };

  const handleBulkApply = async () => {
    const savedPass = sessionStorage.getItem('admin_password');
    if (!savedPass || selectedIds.size === 0) return;

    if (!confirm(`确定要批量将这 ${selectedIds.size} 项修改直接应用到 Neo4j 图数据库吗？`)) {
      return;
    }

    const itemsToApply = feedbacks
      .filter(f => selectedIds.has(f.id))
      .map(f => ({
        id: f.id,
        event_id: f.event_id,
        field_name: f.field_name,
        proposed_value: editedValues[f.id] !== undefined ? editedValues[f.id] : f.proposed_value
      }));

    setBulkActionLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/admin/feedback/apply`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Password': savedPass,
        },
        body: JSON.stringify({ items: itemsToApply }),
      });

      const data = await res.json();
      if (res.ok && data.success) {
        showToast(`成功应用了 ${data.applied_count} 条修正到 Neo4j 数据库`);
        fetchPendingFeedbacks();
      } else {
        showToast(data.message || '批量应用过程中出现错误', 'error');
      }
    } catch (err) {
      showToast('网络异常，请重试', 'error');
    } finally {
      setBulkActionLoading(false);
    }
  };

  const handleBulkDelete = async () => {
    const savedPass = sessionStorage.getItem('admin_password');
    if (!savedPass || selectedIds.size === 0) return;

    if (!confirm(`确定要批量忽略/删除这 ${selectedIds.size} 项修正吗？`)) {
      return;
    }

    setBulkActionLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/admin/feedback/delete`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Password': savedPass,
        },
        body: JSON.stringify({ ids: Array.from(selectedIds) }),
      });

      if (res.ok) {
        showToast(`成功删除了 ${selectedIds.size} 条修正申请`);
        fetchPendingFeedbacks();
      } else {
        showToast('批量删除失败', 'error');
      }
    } catch (err) {
      showToast('网络错误，批量删除失败', 'error');
    } finally {
      setBulkActionLoading(false);
    }
  };

  const getFieldIcon = (fieldName: string) => {
    switch (fieldName) {
      case 'locations':
        return <MapPin className="w-4 h-4 text-emerald-400" />;
      case 'std_start_year':
      case 'year':
        return <Calendar className="w-4 h-4 text-amber-400" />;
      default:
        return <FileText className="w-4 h-4 text-blue-400" />;
    }
  };

  const getFieldLabel = (fieldName: string) => {
    switch (fieldName) {
      case 'locations':
        return '事件地点';
      case 'std_start_year':
      case 'year':
        return '事件年份';
      default:
        return fieldName;
    }
  };

  if (!isAuthenticated) {
    return (
      <main className="relative flex min-h-screen flex-col items-center justify-center bg-radial from-zinc-900 to-black p-4 text-amber-100 overflow-hidden">
        {/* Ancient Han Decorative Background Elements */}
        <div className="absolute inset-0 pointer-events-none opacity-5 bg-[url('/scroll-pattern.png')] bg-repeat" />
        <div className="absolute inset-0 bg-gradient-to-b from-transparent via-amber-950/10 to-transparent pointer-events-none" />

        <div className="relative w-full max-w-md overflow-hidden rounded-2xl border border-amber-600/30 bg-zinc-950/80 px-8 py-10 shadow-[0_0_30px_rgba(217,119,6,0.15)] backdrop-blur-md">
          {/* Top Gold Border Accent */}
          <div className="absolute top-0 inset-x-0 h-1 bg-gradient-to-r from-transparent via-amber-500 to-transparent" />

          <div className="flex flex-col items-center text-center">
            <div className="mb-4 rounded-full border border-amber-500/30 bg-amber-500/5 p-4 shadow-[0_0_15px_rgba(217,119,6,0.05)]">
              <Lock className="h-8 w-8 text-amber-500 animate-pulse" />
            </div>

            <h1 className="font-serif text-2xl font-bold tracking-widest text-amber-400 mb-2">
              三国志·军师校验阁
            </h1>
            <p className="text-sm text-zinc-400 mb-8 font-light">
              请封赏主公玉玺印信，入内阁批阅修正案
            </p>
          </div>

          <form onSubmit={handleLoginSubmit} className="space-y-6">
            <div>
              <label className="block text-xs uppercase tracking-wider text-amber-500/70 font-semibold mb-2">
                军师密令密码 (X-Admin-Password)
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="在此输入校验内阁密令"
                className="w-full rounded-lg border border-amber-600/20 bg-zinc-900/60 px-4 py-3 text-center text-amber-100 shadow-inner placeholder-zinc-600 outline-none transition-all duration-300 focus:border-amber-500/80 focus:shadow-[0_0_10px_rgba(217,119,6,0.15)] focus:bg-zinc-900"
                disabled={loading}
              />
            </div>

            {authError && (
              <div className="flex items-center gap-2 rounded-lg bg-red-950/30 border border-red-900/30 px-4 py-3 text-sm text-red-400">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{authError}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="relative w-full overflow-hidden rounded-lg bg-gradient-to-r from-amber-600 to-amber-700 hover:from-amber-500 hover:to-amber-600 px-6 py-3 font-serif font-bold text-black tracking-widest shadow-lg shadow-amber-950/20 transition-all duration-300 active:scale-98 disabled:opacity-50 disabled:pointer-events-none"
            >
              {loading ? (
                <div className="flex items-center justify-center gap-2">
                  <RefreshCw className="h-4 w-4 animate-spin text-black" />
                  <span>批阅校验中...</span>
                </div>
              ) : (
                '叩印入阁'
              )}
            </button>
          </form>

          <div className="mt-8 text-center">
            <Link
              href="/"
              className="inline-flex items-center gap-2 text-xs text-zinc-500 hover:text-amber-400/80 transition-colors duration-300"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>返回三国历史数字地图</span>
            </Link>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="relative min-h-screen bg-zinc-950 text-zinc-100 font-sans p-6 overflow-x-hidden">
      {/* Decorative lines & noise */}
      <div className="absolute inset-0 pointer-events-none opacity-[0.02] bg-[url('/scroll-pattern.png')] bg-repeat" />

      {/* Toast Notification Banner */}
      {toast && (
        <div className={`fixed top-6 right-6 z-50 flex items-center gap-3 rounded-xl border px-5 py-4 shadow-xl backdrop-blur-md transition-all duration-300 animate-slide-in ${toast.type === 'success'
            ? 'bg-emerald-950/80 border-emerald-500/40 text-emerald-100 shadow-emerald-950/10'
            : 'bg-red-950/80 border-red-500/40 text-red-100 shadow-red-950/10'
          }`}>
          {toast.type === 'success' ? (
            <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
          ) : (
            <AlertCircle className="w-5 h-5 text-red-400 shrink-0" />
          )}
          <span className="text-sm font-medium tracking-wide">{toast.message}</span>
        </div>
      )}

      {/* Top Header Section */}
      <header className="relative flex flex-col md:flex-row items-center justify-between gap-4 border-b border-amber-500/10 pb-6 mb-8">
        <div className="flex items-center gap-4">
          <Link
            href="/"
            className="flex items-center justify-center w-10 h-10 rounded-lg border border-amber-600/20 bg-zinc-900/50 hover:bg-zinc-900 text-amber-500 hover:text-amber-400 transition-all duration-300"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div>
            <h1 className="font-serif text-2xl font-bold tracking-widest text-amber-400 flex items-center gap-3">
              <span>三国志 · 军师校验阁</span>
              <span className="hidden sm:inline-block rounded-full border border-amber-500/30 bg-amber-500/5 px-2.5 py-0.5 text-xs font-sans tracking-normal text-amber-400">
                在线数据校验系统
              </span>
            </h1>
            <p className="text-xs text-zinc-400 mt-1 font-light">
              直接批阅审核主公提交的地图事件修正，批量发布更新到 Neo4j 核心图数据库
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={fetchPendingFeedbacks}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-900/60 px-4 py-2 text-sm text-zinc-300 hover:bg-zinc-900 hover:text-white transition-all duration-300 disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            <span>刷新草案</span>
          </button>

          <button
            onClick={handleSignOut}
            className="inline-flex items-center gap-2 rounded-lg border border-red-950/20 bg-red-950/5 px-4 py-2 text-sm text-red-400 hover:bg-red-950/15 transition-all duration-300"
          >
            <span>出阁</span>
          </button>
        </div>
      </header>

      {/* Main Container */}
      <section className="max-w-7xl mx-auto space-y-6">

        {/* Statistics Widgets */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
          <div className="relative overflow-hidden rounded-xl border border-amber-600/10 bg-zinc-900/40 p-5 backdrop-blur-sm">
            <div className="absolute right-4 top-4 opacity-10 text-amber-500">
              <Database className="w-12 h-12" />
            </div>
            <p className="text-xs uppercase tracking-wider text-zinc-500 font-medium">待审核草案总数</p>
            <h3 className="text-3xl font-serif font-bold text-amber-400 mt-2">{feedbacks.length}</h3>
            <p className="text-xs text-zinc-500 mt-1">等候军师定夺批阅</p>
          </div>

          <div className="relative overflow-hidden rounded-xl border border-emerald-600/10 bg-zinc-900/40 p-5 backdrop-blur-sm">
            <div className="absolute right-4 top-4 opacity-10 text-emerald-400">
              <MapPin className="w-12 h-12" />
            </div>
            <p className="text-xs uppercase tracking-wider text-zinc-500 font-medium">地理坐标修正</p>
            <h3 className="text-3xl font-serif font-bold text-emerald-400 mt-2">
              {feedbacks.filter(f => f.field_name === 'locations').length}
            </h3>
            <p className="text-xs text-zinc-500 mt-1">军事城池与地名变迁</p>
          </div>

          <div className="relative overflow-hidden rounded-xl border border-amber-600/10 bg-zinc-900/40 p-5 backdrop-blur-sm">
            <div className="absolute right-4 top-4 opacity-10 text-amber-400">
              <Calendar className="w-12 h-12" />
            </div>
            <p className="text-xs uppercase tracking-wider text-zinc-500 font-medium">编年史时间修正</p>
            <h3 className="text-3xl font-serif font-bold text-amber-500 mt-2">
              {feedbacks.filter(f => f.field_name === 'std_start_year' || f.field_name === 'year').length}
            </h3>
            <p className="text-xs text-zinc-500 mt-1">纠正出兵与盟誓年份</p>
          </div>
        </div>

        {/* Action Bar */}
        {feedbacks.length > 0 && (
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4 rounded-xl border border-zinc-800 bg-zinc-900/40 px-5 py-4 backdrop-blur-sm">
            <div className="flex items-center gap-3">
              <input
                type="checkbox"
                checked={selectedIds.size === feedbacks.length && feedbacks.length > 0}
                onChange={toggleSelectAll}
                className="w-4.5 h-4.5 rounded border-zinc-700 bg-zinc-800 text-amber-500 focus:ring-0 focus:ring-offset-0 cursor-pointer accent-amber-500"
              />
              <span className="text-sm font-medium tracking-wide text-zinc-300">
                已选中 <strong className="text-amber-400 font-bold px-1">{selectedIds.size}</strong> 项
              </span>
            </div>

            <div className="flex items-center gap-3 w-full sm:w-auto">
              <button
                onClick={handleBulkDelete}
                disabled={selectedIds.size === 0 || bulkActionLoading}
                className="flex-1 sm:flex-initial inline-flex items-center justify-center gap-2 rounded-lg border border-red-950/20 bg-red-950/10 hover:bg-red-950/20 px-5 py-2.5 text-sm text-red-400 font-medium transition-all duration-300 active:scale-98 disabled:opacity-30 disabled:pointer-events-none"
              >
                <Trash2 className="w-4 h-4" />
                <span>批量忽略</span>
              </button>

              <button
                onClick={handleBulkApply}
                disabled={selectedIds.size === 0 || bulkActionLoading}
                className="flex-1 sm:flex-initial inline-flex items-center justify-center gap-2 rounded-lg bg-amber-500 hover:bg-amber-400 px-5 py-2.5 text-sm text-zinc-950 font-bold transition-all duration-300 active:scale-98 disabled:opacity-30 disabled:pointer-events-none shadow-[0_0_15px_rgba(245,158,11,0.1)]"
              >
                <Database className="w-4 h-4 text-zinc-950" />
                <span>批量写入 Neo4j</span>
              </button>
            </div>
          </div>
        )}

        {/* Feedback List Table */}
        <div className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900/20 backdrop-blur-sm">
          {loading && feedbacks.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-zinc-500">
              <RefreshCw className="w-8 h-8 animate-spin text-amber-500 mb-4" />
              <p className="text-sm tracking-widest font-serif text-amber-500/80">内阁翻阅竹简中...</p>
            </div>
          ) : feedbacks.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-24 text-center">
              <div className="rounded-full border border-amber-500/20 bg-amber-500/5 p-4 mb-4 text-amber-500/60">
                <Check className="w-8 h-8" />
              </div>
              <h4 className="font-serif text-lg font-bold text-amber-400/90 tracking-widest">
                海内升平，无有修正
              </h4>
              <p className="text-xs text-zinc-500 mt-1 max-w-sm px-6 leading-relaxed">
                当前尚无待审批的事件修正。当有军师在地图事件卡片提交“修正”时，草案将即刻传送至本内阁。
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-zinc-800 bg-zinc-900/60 text-xs font-bold tracking-wider text-zinc-400 uppercase">
                    <th className="w-12 px-6 py-4"></th>
                    <th className="px-6 py-4 w-52">事件目标</th>
                    <th className="px-6 py-4 w-32">修正维度</th>
                    <th className="px-6 py-4">批注修正值 (可直接在此双击/修改)</th>
                    <th className="px-6 py-4 w-40 text-center">定夺决策</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800/60">
                  {feedbacks.map((fb) => {
                    const isSelected = selectedIds.has(fb.id);
                    const currentVal = editedValues[fb.id] !== undefined ? editedValues[fb.id] : fb.proposed_value;

                    return (
                      <tr
                        key={fb.id}
                        className={`group transition-all duration-200 ${isSelected ? 'bg-amber-500/[0.02]' : 'hover:bg-zinc-900/40'
                          }`}
                      >
                        {/* Checkbox cell */}
                        <td className="px-6 py-5">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleSelect(fb.id)}
                            className="w-4.5 h-4.5 rounded border-zinc-700 bg-zinc-800 text-amber-500 focus:ring-0 cursor-pointer accent-amber-500"
                          />
                        </td>

                        {/* Event Title cell */}
                        <td className="px-6 py-5">
                          <span className="block font-serif text-sm font-bold text-amber-100 group-hover:text-amber-400 transition-colors duration-200">
                            {fb.event_title}
                          </span>
                          <span className="block text-[10px] text-zinc-500 font-mono mt-1 uppercase">
                            ID: {fb.event_id}
                          </span>
                        </td>

                        {/* Field Badge cell */}
                        <td className="px-6 py-5">
                          <div className="inline-flex items-center gap-1.5 rounded-full border border-zinc-800 bg-zinc-900 px-3 py-1 text-xs font-medium text-zinc-300">
                            {getFieldIcon(fb.field_name)}
                            <span>{getFieldLabel(fb.field_name)}</span>
                          </div>
                        </td>

                        {/* Proposed Value cell (Inline Editable!) */}
                        <td className="px-6 py-5">
                          <div className="relative max-w-lg">
                            <input
                              type="text"
                              value={currentVal}
                              onChange={(e) => handleInlineValChange(fb.id, e.target.value)}
                              className="w-full rounded-lg border border-zinc-800 bg-zinc-950/80 px-3 py-2 text-sm text-amber-200 outline-none transition-all duration-200 focus:border-amber-500/50 focus:bg-zinc-900 font-mono"
                              placeholder="输入修正值..."
                            />
                            {/* Edit indicator */}
                            {editedValues[fb.id] !== undefined && editedValues[fb.id] !== fb.proposed_value && (
                              <span className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-bold text-amber-500 uppercase tracking-wider">
                                已修改
                              </span>
                            )}
                          </div>
                        </td>

                        {/* Single Actions cell */}
                        <td className="px-6 py-5 text-center">
                          <div className="flex items-center justify-center gap-2">
                            <button
                              onClick={() => handleSingleApply(fb)}
                              title="应用更新至 Neo4j"
                              disabled={bulkActionLoading}
                              className="flex items-center justify-center w-8 h-8 rounded-lg border border-emerald-950/40 bg-emerald-950/10 text-emerald-400 hover:bg-emerald-500 hover:text-zinc-950 transition-all duration-200 disabled:opacity-30"
                            >
                              <Check className="w-4 h-4" />
                            </button>

                            <button
                              onClick={() => handleSingleDelete(fb.id, fb.event_title)}
                              title="删除/忽略"
                              disabled={bulkActionLoading}
                              className="flex items-center justify-center w-8 h-8 rounded-lg border border-red-950/40 bg-red-950/10 text-red-400 hover:bg-red-500 hover:text-white transition-all duration-200 disabled:opacity-30"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}
