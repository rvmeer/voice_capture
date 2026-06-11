import { useEffect, useState } from 'react';
import type { Recording } from '../types';

interface Props {
  recording: Recording;
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

export default function HeaderBar({
  recording,
}: Props) {
  const [, setTick] = useState(0);

  useEffect(() => {
    if (recording.status !== 'live') return;
    const t = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [recording.status]);

  // We'll pull stats from the store directly via a prop passed from parent
  return (
    <header className="sticky top-0 z-50 bg-gray-900 text-white px-6 py-3 flex items-center gap-6 shadow-lg">
      <div className="flex items-center gap-3 flex-1 min-w-0">
        {recording.status === 'live' && (
          <span className="w-3 h-3 rounded-full bg-red-500 animate-pulse shrink-0" />
        )}
        <h1 className="text-lg font-bold truncate">{recording.title}</h1>
      </div>
      <div className="font-mono text-xl tabular-nums shrink-0">
        {elapsed(recording.started_at, recording.ended_at)}
      </div>
      {recording.status === 'ended' && (
        <span className="text-xs bg-gray-700 px-2 py-0.5 rounded">Ended</span>
      )}
    </header>
  );
}
