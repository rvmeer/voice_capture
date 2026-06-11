import { useState } from 'react';
import type { PastReference } from '../types';

interface Props {
  refs: PastReference[];
  recordingId: string;
}

const SIGNAL_CONFIG = {
  repeated: { label: 'Komt terug', cls: 'bg-red-700 text-white' },
  resolved: { label: 'Opgelost', cls: 'bg-green-700 text-white' },
  new_context: { label: 'Context', cls: 'bg-gray-600 text-gray-100' },
};

function groupByTopic(refs: PastReference[]) {
  const map = new Map<number, { label: string; items: PastReference[] }>();
  refs.forEach((r) => {
    if (!map.has(r.topic_id)) map.set(r.topic_id, { label: r.topic_label, items: [] });
    map.get(r.topic_id)!.items.push(r);
  });
  return Array.from(map.values());
}

export default function PastRecordingsPanel({ refs, recordingId }: Props) {
  const groups = groupByTopic(refs);
  const [loadingTopics, setLoadingTopics] = useState<Set<number>>(new Set());

  async function digDeeper(topicId: number) {
    setLoadingTopics((s) => new Set([...s, topicId]));
    try {
      await fetch(`/recordings/${recordingId}/topics/${topicId}/dig_deeper`, { method: 'POST' });
    } finally {
      setLoadingTopics((s) => { const n = new Set(s); n.delete(topicId); return n; });
    }
  }

  return (
    <section className="bg-gray-900 rounded-xl p-5 h-full flex flex-col gap-3">
      <h2 className="text-sm font-bold uppercase tracking-wider text-gray-400">🗂 Past Recordings</h2>
      {!groups.length ? (
        <p className="text-gray-400 text-sm italic">No cross-recording context yet.</p>
      ) : (
        <div className="flex flex-col gap-5">
          {groups.map((g) => (
            <div key={g.label}>
              <div className="flex items-center gap-3 mb-2">
                <span className="text-xs font-semibold text-purple-300 uppercase"># {g.label}</span>
                <button
                  onClick={() => digDeeper(g.items[0].topic_id)}
                  disabled={loadingTopics.has(g.items[0].topic_id)}
                  className="text-xs bg-purple-800 hover:bg-purple-700 disabled:opacity-50 text-white px-3 py-0.5 rounded-full transition"
                >
                  {loadingTopics.has(g.items[0].topic_id) ? '⟳ Loading…' : 'Dig deeper'}
                </button>
              </div>
              <div className="flex flex-col gap-2">
                {g.items.map((r) => {
                  const sig = SIGNAL_CONFIG[r.signal];
                  return (
                    <div key={r.id} className="bg-gray-800/60 rounded-lg px-4 py-3 border border-gray-700">
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${sig.cls}`}>{sig.label}</span>
                        <span className="text-xs text-gray-400">
                          {new Date(r.source_recording_started_at).toLocaleDateString()} · {r.source_recording_title}
                        </span>
                        {r.source === 'dig_deeper' && (
                          <span className="text-xs text-purple-400 ml-auto">Dig deeper</span>
                        )}
                      </div>
                      <p className="text-sm text-gray-200 leading-relaxed">{r.summary}</p>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
