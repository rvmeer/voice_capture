import type { Decision } from '../types';

interface Props { decisions: Decision[] }

function fmtTime(ts: string) {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export default function DecisionsPanel({ decisions }: Props) {
  const sorted = [...decisions].sort((a, b) => new Date(b.decided_at).getTime() - new Date(a.decided_at).getTime());

  return (
    <section className="bg-gray-900 rounded-xl p-5 h-full flex flex-col gap-3">
      <h2 className="text-sm font-bold uppercase tracking-wider text-gray-400">⚖️ Decisions</h2>
      {!sorted.length ? (
        <p className="text-gray-400 text-sm italic">No decisions yet.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {sorted.map((d) => (
            <div key={d.id}
              className={`rounded-lg px-4 py-3 border transition-all ${
                d.status === 'agreed'
                  ? 'border-green-700 bg-green-950/30'
                  : d.status === 'rejected'
                  ? 'border-red-900 bg-red-950/20 opacity-60'
                  : 'border-dashed border-gray-600 bg-gray-800/30'
              }`}
            >
              <div className="flex items-start gap-3">
                <span className="text-xs text-gray-400 font-mono shrink-0 mt-0.5">{fmtTime(d.decided_at)}</span>
                <div className="flex-1">
                  <p className="text-base text-gray-100 leading-snug">{d.description}</p>
                  <div className="flex gap-2 mt-1 flex-wrap">
                    {d.status === 'concept' && (
                      <span className="text-xs border border-gray-500 text-gray-400 px-2 py-0.5 rounded-full">Concept</span>
                    )}
                    {d.status === 'rejected' && (
                      <span className="text-xs bg-red-900 text-red-200 px-2 py-0.5 rounded-full">Rejected</span>
                    )}
                    {d.topic_label && (
                      <span className="text-xs text-gray-500"># {d.topic_label}</span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
