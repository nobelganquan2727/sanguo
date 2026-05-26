'use client';

import React, { useState, useMemo, useEffect, useRef } from 'react';
import { 
  Network, 
  X, 
  MapPin, 
  Compass, 
  Heart, 
  Shield, 
  Swords, 
  User, 
  Milestone, 
  Calendar,
  Layers,
  ArrowRight,
  TrendingUp
} from 'lucide-react';

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

interface GraphNode {
  id: string;
  label: string;
  type: 'center' | 'person' | 'hometown' | 'clan';
}

interface GraphLink {
  source: string;
  target: string;
  type: string;
  desc?: string;
}

interface PersonRelationsModalProps {
  open: boolean;
  name: string;
  relations: {
    name: string;
    hometown?: string | null;
    clan?: string | null;
    nodes: GraphNode[];
    links: GraphLink[];
    relations: PersonRelation[];
  } | null;
  loading: boolean;
  onClose: () => void;
  onEventClick?: (eventId: string) => void;
  onPersonClick?: (personName: string) => void;
}

function PersonRelationsModal({
  open,
  name,
  relations,
  loading,
  onClose,
  onEventClick,
  onPersonClick,
}: PersonRelationsModalProps) {
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Clean up timer on unmount
  useEffect(() => {
    return () => {
      if (hoverTimer.current) {
        clearTimeout(hoverTimer.current);
      }
    };
  }, []);

  const handleNodeMouseEnter = (nodeId: string) => {
    if (hoverTimer.current) clearTimeout(hoverTimer.current);
    hoverTimer.current = setTimeout(() => {
      setHoveredNodeId(nodeId);
    }, 70); // 70ms threshold is the sweet spot for avoiding rapid CPU-bound state updates
  };

  const handleNodeMouseLeave = () => {
    if (hoverTimer.current) clearTimeout(hoverTimer.current);
    hoverTimer.current = setTimeout(() => {
      setHoveredNodeId(null);
    }, 45);
  };

  // If name changes, reset selection to the new center name
  useEffect(() => {
    setSelectedNodeId(name);
  }, [name]);

  // Extract graph data safely
  const graphNodes = relations?.nodes || [];
  const graphLinks = relations?.links || [];
  const legacyRelations = relations?.relations || [];
  const hometown = relations?.hometown || null;
  const clan = relations?.clan || null;

  // SVG Size & Coordinates configuration
  const width = 560;
  const height = 430;
  const cx = width / 2;
  const cy = height / 2;

  // 1. Programmatic Deterministic Radial Layout
  const layout = useMemo(() => {
    const result: Record<string, { x: number; y: number; angle: number; color: string; label: string; type: string; desc: string }> = {};
    if (graphNodes.length === 0) return result;

    // Center Node (placed exactly at center)
    result[name] = { 
      x: cx, 
      y: cy, 
      angle: 0, 
      color: '#f59e0b', // Amber 500
      label: name, 
      type: 'center', 
      desc: '当前图谱核心人物' 
    };

    // Filter different categories of nodes
    const hometownNode = graphNodes.find(n => n.type === 'hometown');
    const clanNode = graphNodes.find(n => n.type === 'clan');
    const personNodes = graphNodes.filter(n => n.type === 'person' && n.id !== name);

    // Dynamic co-events vs static relations split
    const kinships: any[] = [];
    const allies: any[] = [];
    const enemies: any[] = [];
    const coEvents: any[] = [];

    personNodes.forEach(n => {
      // Find the link connecting center to this node
      const link = graphLinks.find(l => 
        (l.source === name && l.target === n.id) || 
        (l.source === n.id && l.target === name)
      );
      const type = link ? link.type : 'CO_EVENT';
      const desc = link ? link.desc : '';

      if (type === 'KINSHIP') {
        kinships.push({ ...n, color: '#ec4899', desc: `家族血亲 (${desc})`, category: 'kinship' });
      } else if (type === 'ENEMY') {
        enemies.push({ ...n, color: '#ef4444', desc: `生前对手 (${desc})`, category: 'enemy' });
      } else if (type === 'CO_EVENT') {
        coEvents.push({ ...n, color: '#6366f1', desc: `历史交集 (${desc})`, category: 'co_event' });
      } else {
        // ALLY, RULER_SUBJECT, RECOMMENDED
        let color = '#10b981'; // ALLY -> Emerald
        if (type === 'RULER_SUBJECT') color = '#06b6d4'; // Sky/Cyan
        if (type === 'RECOMMENDED') color = '#8b5cf6'; // Purple
        allies.push({ ...n, color, desc: `${desc}`, category: 'ally' });
      }
    });

    // Roots nodes grouping (Hometown / Clan)
    const roots: any[] = [];
    if (hometownNode) roots.push({ ...hometownNode, color: '#14b8a6', desc: '籍贯出身' }); // Teal
    if (clanNode) roots.push({ ...clanNode, color: '#f59e0b', desc: '士族门阀' }); // Gold

    // Radial Distributing helper
    const distributeNodes = (nodesList: any[], startAngleDeg: number, endAngleDeg: number, radius: number) => {
      if (nodesList.length === 0) return;
      const count = nodesList.length;
      const step = count > 1 ? (endAngleDeg - startAngleDeg) / (count - 1) : 0;
      
      nodesList.forEach((n, idx) => {
        const angleDeg = count > 1 ? startAngleDeg + idx * step : (startAngleDeg + endAngleDeg) / 2;
        const rad = (angleDeg * Math.PI) / 180;
        const x = cx + radius * Math.cos(rad);
        const y = cy + radius * Math.sin(rad);
        
        result[n.id] = {
          x,
          y,
          angle: angleDeg,
          color: n.color,
          label: n.label || n.id,
          type: n.type,
          desc: n.desc
        };
      });
    };

    // Distribute inner ring nodes (r = 110px) - Core bloodline and roots
    const q1_nodes = [...roots, ...kinships]; // Roots & kinship: Top Sector (-140 to -40 deg)
    distributeNodes(q1_nodes, -145, -35, 105);

    // Distribute intermediate ring nodes (r = 125px) - Allies and Enemies
    const q2_nodes = allies; // Allies: Right Sector (-25 to 55 deg)
    distributeNodes(q2_nodes, -20, 50, 115);

    const q3_nodes = enemies; // Enemies: Left Sector (125 to 235 deg)
    distributeNodes(q3_nodes, 130, 230, 115);
    
    // Distribute outer ring nodes (r = 185px) - dynamic co-events
    // Bottom sector (65 to 115 deg) - dynamic co-occurrences
    distributeNodes(coEvents, 60, 120, 185);

    return result;
  }, [graphNodes, graphLinks, name, cx, cy]);

  // Determine active node details to show in the right column - ONLY triggers on click!
  const activeNodeId = selectedNodeId || name;
  const activeLayoutInfo = layout[activeNodeId];
  
  // Find detailed info for the active person
  const activeRelationDetails = useMemo(() => {
    if (!activeNodeId) return null;
    
    // Check if it is a Person
    const relationInfo = legacyRelations.find(r => r.person === activeNodeId);
    
    // Check connection type from center
    const link = graphLinks.find(l => 
      (l.source === name && l.target === activeNodeId) || 
      (l.source === activeNodeId && l.target === name)
    );

    return {
      name: activeNodeId,
      type: activeLayoutInfo?.type || 'person',
      desc: activeLayoutInfo?.desc || '',
      color: activeLayoutInfo?.color || '#94a3b8',
      linkType: link?.type || 'CO_EVENT',
      linkDesc: link?.desc || '',
      events: relationInfo?.events || [],
      count: relationInfo?.count || 0
    };
  }, [activeNodeId, legacyRelations, graphLinks, name, activeLayoutInfo]);

  // Helper to draw smooth bezier connection lines
  const getBezierPath = (x1: number, y1: number, x2: number, y2: number) => {
    // A nice quadratic bezier curving from center (x1, y1) to target (x2, y2)
    const mx = (x1 + x2) / 2;
    const my = (y1 + y2) / 2;
    
    // We bend the line towards the center bottom to give a elegant branching tree aesthetic
    const controlX = mx;
    const controlY = my + 15;
    
    return `M ${x1} ${y1} Q ${controlX} ${controlY} ${x2} ${y2}`;
  };

  // Helper to choose corresponding icons based on node types
  const getNodeIcon = (type: string, relType?: string) => {
    if (type === 'hometown') return <MapPin className="w-3.5 h-3.5" />;
    if (type === 'clan') return <Compass className="w-3.5 h-3.5" />;
    if (type === 'center') return <Layers className="w-5 h-5" />;
    
    switch (relType) {
      case 'KINSHIP': return <Heart className="w-3.5 h-3.5" />;
      case 'ENEMY': return <Swords className="w-3.5 h-3.5" />;
      case 'RULER_SUBJECT': return <User className="w-3.5 h-3.5" />;
      case 'RECOMMENDED': return <Milestone className="w-3.5 h-3.5" />;
      default: return <Network className="w-3.5 h-3.5" />;
    }
  };

  if (!open) return null;

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/85 pointer-events-auto transition-opacity duration-300">
      <div className="w-[1000px] h-[600px] bg-[#070e17] border border-[#23354b] rounded-lg shadow-[0_0_50px_rgba(0,0,0,0.9)] flex flex-col overflow-hidden">
        
        {/* Header Section */}
        <div className="bg-gradient-to-r from-[#0d1b2d] to-[#050a11] py-3.5 px-5 border-b border-[#23354b] flex justify-between items-center shrink-0">
          <div className="flex items-center gap-2.5">
            <div className="p-1 rounded bg-amber-500/10 border border-amber-500/30">
              <Network className="w-4 h-4 text-amber-400 animate-pulse" />
            </div>
            <div>
              <h2 className="text-white font-serif font-bold text-sm tracking-widest">人物关系脑图</h2>
              <p className="text-[10px] text-slate-400 font-sans mt-0.5">静态地缘、世族、血脉连结 与 动态历史共同事迹的多维度图谱沙盘</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-white/5 text-slate-400 hover:text-white transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Core Container */}
        <div className="flex-1 min-h-0 flex">
          
          {/* Left Column: Visual SVG Graph */}
          <div className="w-[60%] border-r border-[#23354b] bg-[#04080e] relative flex items-center justify-center overflow-hidden">
            {loading ? (
              <div className="flex flex-col items-center gap-3">
                <div className="w-8 h-8 border-4 border-amber-500/20 border-t-amber-500 rounded-full animate-spin" />
                <div className="text-xs text-slate-400 font-serif">正在观天象，调取卷宗...</div>
              </div>
            ) : graphNodes.length === 0 ? (
              <div className="text-xs text-slate-500 font-serif">暂无任何关联网。</div>
            ) : (
              <div className="w-full h-full relative flex items-center justify-center select-none">
                
                {/* SVG Visual Canvas */}
                <svg width={width} height={height} className="overflow-visible z-10">
                  
                  {/* Subtle Grid Orbits */}
                  <circle cx={cx} cy={cy} r="110" fill="none" stroke="#1d2838" strokeWidth="1" strokeDasharray="3,6" />
                  <circle cx={cx} cy={cy} r="185" fill="none" stroke="#141c27" strokeWidth="1" strokeDasharray="4,8" />

                  <g className="radial-guides">
                    <line x1={cx} y1={cy - 200} x2={cx} y2={cy + 200} stroke="#1d2838" strokeWidth="0.5" strokeDasharray="2,10" />
                    <line x1={cx - 260} y1={cy} x2={cx + 260} y2={cy} stroke="#1d2838" strokeWidth="0.5" strokeDasharray="2,10" />
                  </g>

                  {/* Draw Bezier Connection Lines */}
                  {graphLinks.map((link, idx) => {
                    const srcNode = layout[link.source];
                    const tgtNode = layout[link.target];
                    if (!srcNode || !tgtNode) return null;

                    const isHovered = hoveredNodeId === link.source || hoveredNodeId === link.target;
                    const isSelected = selectedNodeId === link.source || selectedNodeId === link.target;
                    
                    // Determine stroke color base
                    let strokeColor = '#1e293b';
                    if (isHovered) strokeColor = '#f59e0b'; // Hovered is Amber glow
                    else if (isSelected) strokeColor = '#f59e0b';
                    else {
                      if (link.type === 'ENEMY') strokeColor = 'rgba(239, 68, 68, 0.25)';
                      else if (link.type === 'KINSHIP') strokeColor = 'rgba(236, 72, 153, 0.25)';
                      else if (link.type === 'CO_EVENT') strokeColor = 'rgba(99, 102, 241, 0.15)';
                      else strokeColor = 'rgba(16, 185, 129, 0.25)'; // ALLY / RULER_SUBJECT / RECOMMENDED
                    }

                    return (
                      <g key={`link-${idx}`}>
                        {/* Glow effect on hover */}
                        {(isHovered || isSelected) && (
                          <path
                            d={getBezierPath(srcNode.x, srcNode.y, tgtNode.x, tgtNode.y)}
                            fill="none"
                            stroke="#f59e0b"
                            strokeWidth="3.5"
                            strokeOpacity="0.35"
                            className="transition-all duration-300"
                          />
                        )}
                        <path
                          d={getBezierPath(srcNode.x, srcNode.y, tgtNode.x, tgtNode.y)}
                          fill="none"
                          stroke={strokeColor}
                          strokeWidth={(isHovered || isSelected) ? 1.5 : 1}
                          strokeDasharray={link.type === 'CO_EVENT' ? '2,2' : undefined}
                          className="transition-all duration-300"
                        />
                      </g>
                    );
                  })}

                  {/* Draw Nodes */}
                  {Object.entries(layout).map(([nodeId, n]) => {
                    const isCenter = n.type === 'center';
                    const isHovered = hoveredNodeId === nodeId;
                    const isSelected = selectedNodeId === nodeId;

                    // Compute node sizes
                    let radius = 17;
                    if (isCenter) radius = 33;
                    else if (n.type === 'hometown' || n.type === 'clan') radius = 19;

                    return (
                      <g
                        key={`node-${nodeId}`}
                        transform={`translate(${n.x}, ${n.y})`}
                        className="cursor-pointer group"
                        onMouseEnter={() => handleNodeMouseEnter(nodeId)}
                        onMouseLeave={handleNodeMouseLeave}
                        onClick={() => {
                          setSelectedNodeId(nodeId);
                        }}
                        onDoubleClick={() => {
                          if (!isCenter && n.type === 'person' && onPersonClick) {
                            onPersonClick(nodeId);
                          }
                        }}
                      >
                        {/* Pulse animation for Center node */}
                        {isCenter && (
                          <circle
                            r={radius + 6}
                            fill="none"
                            stroke="#f59e0b"
                            strokeWidth="1.5"
                            strokeOpacity="0.4"
                            className="animate-ping"
                            style={{ animationDuration: '3s' }}
                          />
                        )}

                        {/* Outer thick border on hover / select */}
                        {(isHovered || isSelected) && (
                          <circle
                            r={radius + 4}
                            fill="none"
                            stroke="#f59e0b"
                            strokeWidth="1.5"
                            className="transition-all duration-200"
                          />
                        )}

                        {/* Node Bubble */}
                        <circle
                          r={radius}
                          fill={isCenter ? '#1e1b12' : '#050a11'}
                          stroke={isHovered || isSelected ? '#f59e0b' : n.color}
                          strokeWidth={isCenter ? 2.5 : 1.5}
                          className="transition-all duration-200 shadow-xl"
                        />

                        {/* Centered Node Label */}
                        <text
                          y={isCenter ? 4 : 3.5}
                          textAnchor="middle"
                          fill={isCenter ? '#f59e0b' : (isHovered || isSelected ? '#fff' : '#cbd5e1')}
                          fontSize={isCenter ? '13px' : '9.5px'}
                          fontWeight={isCenter ? 'bold' : 'normal'}
                          className={`${isCenter ? 'font-serif' : 'font-sans'} select-none transition-colors duration-200`}
                        >
                          {n.label}
                        </text>
                      </g>
                    );
                  })}
                </svg>

                {/* Grid Visual Sector Legends */}
                <div className="absolute top-4 left-4 flex flex-col gap-1.5 text-[9px] text-slate-400 bg-[#070e17]/95 border border-[#23354b]/50 rounded p-2 z-0">
                  <div className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-[#f59e0b] shrink-0" />
                    <span>中心人物</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-[#14b8a6] shrink-0" />
                    <span>地缘出身 (HOMETOWN)</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-[#fbbf24] shrink-0" />
                    <span>名氏家族 (CLAN)</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-[#ec4899] shrink-0" />
                    <span>血缘世系 (KINSHIP)</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-[#10b981] shrink-0" />
                    <span>政治盟友 (ALLY / SUBJECT)</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-[#ef4444] shrink-0" />
                    <span>宿敌竞争 (ENEMY)</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-[#6366f1] shrink-0" />
                    <span>事件交集 (CO-EVENTS)</span>
                  </div>
                </div>

                <div className="absolute bottom-4 right-4 text-[9px] text-slate-500 font-sans tracking-wider select-none bg-black/40 px-2 py-0.5 rounded border border-[#23354b]/30">
                  ⚡ 提示：双击人物节点可直接穿梭钻取图谱
                </div>
              </div>
            )}
          </div>

          {/* Right Column: Dynamic Info Sidebar */}
          <div className="w-[40%] bg-[#050b12] flex flex-col min-h-0 overflow-hidden">
            {loading ? (
              <div className="flex-1 flex items-center justify-center text-xs text-slate-500">
                正在理清交际图章...
              </div>
            ) : !activeRelationDetails ? (
              <div className="flex-1 flex flex-col items-center justify-center p-6 text-center text-xs text-slate-500">
                <Network className="w-8 h-8 text-slate-600 mb-2 animate-pulse" />
                请将鼠标悬停在图谱节点上，<br />或点击节点以查看多维度的历史细节
              </div>
            ) : (
              <div className="flex-1 flex flex-col min-h-0">
                
                {/* Upper Section: Node Profile Card */}
                <div className="p-5 border-b border-[#23354b]/70 bg-gradient-to-b from-[#09121e]/40 to-transparent shrink-0">
                  <div className="flex items-center gap-2 mb-1.5">
                    <span 
                      className="px-2 py-0.5 text-[9px] font-bold rounded uppercase tracking-wider flex items-center gap-1"
                      style={{ 
                        backgroundColor: `${activeRelationDetails.color}15`, 
                        color: activeRelationDetails.color,
                        border: `1px solid ${activeRelationDetails.color}30`
                      }}
                    >
                      {getNodeIcon(activeRelationDetails.type, activeRelationDetails.linkType)}
                      {activeRelationDetails.type === 'center' ? '主传核心' : 
                       activeRelationDetails.type === 'hometown' ? '历史地缘' : 
                       activeRelationDetails.type === 'clan' ? '名氏世门' : '关联人物'}
                    </span>
                    {activeRelationDetails.type === 'person' && activeRelationDetails.linkDesc && (
                      <span className="text-[9.5px] text-amber-300 font-sans border border-amber-500/20 px-1.5 py-0.5 rounded bg-amber-500/5">
                        {activeRelationDetails.linkDesc}
                      </span>
                    )}
                  </div>
                  
                  <div className="flex items-end justify-between gap-4">
                    <h3 className="text-2xl text-white font-serif font-bold tracking-wider">{activeRelationDetails.name}</h3>
                    {activeRelationDetails.type === 'person' && onPersonClick && activeRelationDetails.name !== name && (
                      <button
                        onClick={() => onPersonClick(activeRelationDetails.name)}
                        className="px-2.5 py-1 rounded bg-[#10233b] hover:bg-[#1a385f] text-[10px] text-amber-400 hover:text-white border border-[#263e5e] hover:border-amber-400/40 flex items-center gap-1 transition-all duration-200 cursor-pointer"
                        title={`将${activeRelationDetails.name}设为图谱中心`}
                      >
                        <span>进入图谱</span>
                        <ArrowRight className="w-2.5 h-2.5" />
                      </button>
                    )}
                  </div>

                  <p className="text-[11px] text-slate-400 leading-relaxed mt-2.5 bg-black/40 border border-[#23354b]/40 rounded p-2.5">
                    {activeRelationDetails.type === 'center' && (
                      <span>
                        《三国志》核心传主。历史记载其籍贯为 <strong>{hometown || '未详'}</strong>，出身氏族为 <strong>{clan || '普通宗族/不详'}</strong>。该角色与本地图谱中 <strong>{legacyRelations.length}</strong> 人直接共同经历历史大事，关联了 <strong>{graphNodes.length - 1}</strong> 条强类型地缘宗室关系。
                      </span>
                    )}
                    {activeRelationDetails.type === 'hometown' && (
                      <span>
                        <strong>{activeRelationDetails.name}</strong> 是东汉末年至三国时期的著名籍贯地缘。他是中心传主【<strong>{name}</strong>】的出生发迹之地。在历史网络中，同乡籍贯是建立政治联结与提拔的重要隐性资产。
                      </span>
                    )}
                    {activeRelationDetails.type === 'clan' && (
                      <span>
                        <strong>{activeRelationDetails.name}</strong> 为割据中扮演重要政治角色的世家门阀。当时门阀政治极盛，名门望族如荀氏、诸葛氏、陆氏等，通过庞大的婚姻血盟和子嗣仕官，构建起跨越势力的稳固网络。
                      </span>
                    )}
                    {activeRelationDetails.type === 'person' && (
                      <span>
                        与中心人物【<strong>{name}</strong>】的关联类型为：
                        <strong className="mx-1" style={{ color: activeRelationDetails.color }}>
                          {activeRelationDetails.linkType === 'KINSHIP' ? '血缘宗亲' :
                           activeRelationDetails.linkType === 'ENEMY' ? '敌对宿敌' :
                           activeRelationDetails.linkType === 'RULER_SUBJECT' ? '君主臣属' :
                           activeRelationDetails.linkType === 'RECOMMENDED' ? '推荐发掘' : '共同史事交集'}
                        </strong>。
                        {activeRelationDetails.linkDesc ? `具体描述为【${activeRelationDetails.linkDesc}】。` : ''}
                        双方共在 <strong>{activeRelationDetails.count}</strong> 场历史事件中同时登场。
                      </span>
                    )}
                  </p>
                </div>

                {/* Lower Section: Common Events List */}
                <div className="flex-1 min-h-0 flex flex-col p-5 pt-1">
                  <div className="flex items-center justify-between py-2 shrink-0 border-b border-[#23354b]/40 mb-3">
                    <div className="text-[10px] text-slate-400 font-bold uppercase tracking-wider flex items-center gap-1.5">
                      <Calendar className="w-3.5 h-3.5 text-amber-500" />
                      <span>
                        {activeRelationDetails.type === 'center' ? '社交高频人物' : '双方共同经历的史料事件'}
                      </span>
                    </div>
                    {activeRelationDetails.type === 'person' && activeRelationDetails.count > 0 && (
                      <span className="text-[9px] font-mono text-amber-400 bg-amber-500/10 border border-amber-500/20 px-1.5 py-0.5 rounded">
                        共 {activeRelationDetails.count} 场
                      </span>
                    )}
                  </div>

                  <div className="flex-1 overflow-y-auto overscroll-contain pr-1 flex flex-col gap-2">
                    {/* If the active node is center, show a list of overall key relations instead of empty list */}
                    {activeRelationDetails.type === 'center' ? (
                      <div className="flex flex-col gap-2">
                        <div className="text-[10.5px] text-slate-400 mb-1 leading-relaxed">
                          当前与【<strong>{name}</strong>】史事交集频率最高的社交人物：
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                          {legacyRelations.slice(0, 10).map(rel => (
                            <button
                              key={rel.person}
                              onClick={() => setSelectedNodeId(rel.person)}
                              className="p-2 rounded bg-[#0a1526] hover:bg-[#12243d] border border-[#23354b]/50 text-left transition-colors duration-200 cursor-pointer"
                            >
                              <div className="text-xs text-white font-bold">{rel.person}</div>
                              <div className="text-[9px] text-amber-400 font-mono mt-0.5 flex items-center justify-between">
                                <span>交集 {rel.count} 次</span>
                                <TrendingUp className="w-2.5 h-2.5 text-amber-500/70" />
                              </div>
                            </button>
                          ))}
                        </div>
                        {legacyRelations.length === 0 && (
                          <div className="text-xs text-slate-500 py-6 text-center">暂无大事件交集人物数据。</div>
                        )}
                      </div>
                    ) : activeRelationDetails.events.length === 0 ? (
                      <div className="text-xs text-slate-500 py-12 text-center">
                        {activeRelationDetails.type === 'hometown' ? '籍贯人物的同乡行军事件仅在地图打点显示。' :
                         activeRelationDetails.type === 'clan' ? '世系门阀的详细传记可返回主界面左侧查阅。' : 
                         '暂无共同参与的历史事件。'}
                      </div>
                    ) : (
                      activeRelationDetails.events.map(event => (
                        <button
                          key={event.id}
                          type="button"
                          onClick={() => onEventClick?.(event.id)}
                          className="w-full text-left bg-[#0c1825]/60 hover:bg-[#152a41] border border-[#23354b]/50 hover:border-amber-500/30 rounded p-2.5 transition-all duration-200 cursor-pointer flex flex-col gap-1 group"
                        >
                          <div className="flex justify-between items-start gap-2">
                            <span className="text-xs text-white group-hover:text-amber-300 font-serif leading-snug transition-colors">
                              {event.title}
                            </span>
                            <span className="text-[9px] text-amber-500 font-mono border border-amber-500/20 px-1 py-0.25 rounded shrink-0 bg-amber-500/5">
                              {event.year != null ? `${event.year}年` : '不详'}
                            </span>
                          </div>
                          {event.type && (
                            <span className="text-[9px] text-slate-500 mt-0.5">
                              事件类型：{event.type}
                            </span>
                          )}
                        </button>
                      ))
                    )}
                  </div>
                </div>

              </div>
            )}
          </div>

        </div>

        {/* Footer Section */}
        <div className="bg-[#050a11] py-3.5 px-5 border-t border-[#23354b] flex justify-between items-center shrink-0">
          <div className="flex gap-4 text-[9px] text-slate-500">
            <div>中心人物：<span className="text-slate-300">{name}</span></div>
            <div>籍贯地缘：<span className="text-slate-300">{hometown || '未知'}</span></div>
            <div>名氏氏族：<span className="text-slate-300">{clan || '未知'}</span></div>
          </div>
          <button
            onClick={onClose}
            className="px-5 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-xs text-slate-300 hover:text-white border border-slate-700 hover:border-slate-600 transition-all duration-200 cursor-pointer"
          >
            关闭卷宗
          </button>
        </div>

      </div>
    </div>
  );
}

export default React.memo(PersonRelationsModal);
