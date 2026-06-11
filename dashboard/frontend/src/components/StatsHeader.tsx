import type { HeaderStats, Recording, Participant } from '../types';

interface Props {
  recording: Recording;
  stats: HeaderStats;
  participants: Participant[];
  wsConnected: boolean;
}

function elapsed(started_at: string, ended_at: string | null) {
  const start = new Date(started_at).getTime();
  const end = ended_at ? new Date(ended_at).getTime() : Date.now();
  const secs = Math.floor((end - start) / 1000);
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  return [h, m, s].map((v) => String(v).padStart(2, '0')).join(':');
}

import { useEffect, useState } from 'react';

export default function StatsHeader({ recording, stats, wsConnected }: Props) {
  const [, setTick] = useState(0);

  useEffect(() => {
    if (recording.status !== 'live') return;
    const t = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [recording.status]);

  return (
    <header className="sticky top-0 z-50 bg-gray-950 border-b border-gray-800 text-white px-6 py-3 flex items-center gap-5 shadow-xl">
      {/* Live indicator + title */}
      <div className="flex items-center gap-3 flex-1 min-w-0">
        {recording.status === 'live' && (
          <span className="w-2.5 h-2.5 rounded-full bg-red-500 animate-pulse shrink-0" />
        )}
        <h1 className="text-base font-bold truncate">{recording.title}</h1>
        {!wsConnected && (
          <span className="text-xs text-yellow-400 bg-yellow-950/40 border border-yellow-700 px-2 py-0.5 rounded-full ml-2 shrink-0">
            Reconnecting…
          </span>
        )}
      </div>

      {/* Timer */}
      <div className="font-mono text-xl tabular-nums shrink-0">
        {elapsed(recording.started_at, recording.ended_at)}
      </div>

      {/* Stats chips */}
      <div className="hidden sm:flex items-center gap-4 text-sm shrink-0">
        <StatChip icon="👥" value={stats.participants} label="participants" />
        <StatChip
          icon="🎯"
          value={`${stats.goals_achieved}/${stats.goals_total}`}
          label="goals"
          highlight={stats.goals_achieved === stats.goals_total && stats.goals_total > 0}
        />
        <StatChip icon="✅" value={stats.action_items} label="actions" />
        <StatChip icon="⚖️" value={stats.decisions} label="decisions" />
      </div>

      {/* Status badge */}
      {recording.status === 'ended' && (
        <span className="text-xs bg-gray-700 text-gray-300 px-2 py-0.5 rounded shrink-0">Ended</span>
      )}
    </header>
  );
}

function StatChip({ icon, value, label, highlight }: { icon: string; value: string | number; label: string; highlight?: boolean }) {
  return (
    <div className={`flex items-center gap-1 ${highlight ? 'text-green-400' : 'text-gray-300'}`}>
      <span>{icon}</span>
      <span className="font-semibold tabular-nums">{value}</span>
      <span className="text-gray-500 text-xs hidden lg:inline">{label}</span>
    </div>
  );
}
