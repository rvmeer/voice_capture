import type { KeyMoment } from '../types';

const TYPE_CONFIG = {
  commitment: { emoji: '🟦', label: 'Commitment', cls: 'border-blue-600 bg-blue-950/30' },
  decision:   { emoji: '🟩', label: 'Decision',   cls: 'border-green-700 bg-green-950/30' },
  tension:    { emoji: '🟥', label: 'Tension',    cls: 'border-red-700 bg-red-950/30' },
  insight:    { emoji: '🟨', label: 'Insight',    cls: 'border-yellow-600 bg-yellow-950/30' },
};

interface Props {
  moments: KeyMoment[];
  recordingId: string;
}

function fmtTime(ts: string) {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export default function KeyMomentsPanel({ moments, recordingId }: Props) {
  async function flagNow() {
    const quote = prompt('Enter a quote to flag as key moment:');
    if (!quote) return;
    await fetch(`/recordings/${recordingId}/key_moments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: 'insight', quote, flagged_by: 'user' }),
    });
  }

  return (
    <section className="bg-gray-900 rounded-xl p-5 h-full flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-bold uppercase tracking-wider text-gray-400">⭐ Key Moments</h2>
        <button
          onClick={flagNow}
          className="text-xs bg-gray-700 hover:bg-gray-600 text-gray-200 px-3 py-1 rounded-full transition"
        >
          + Flag moment
        </button>
      </div>
      {!moments.length ? (
        <p className="text-gray-400 text-sm italic">No key moments yet.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {moments.map((km) => {
            const cfg = TYPE_CONFIG[km.type];
            return (
              <div key={km.id} className={`rounded-lg px-4 py-3 border ${cfg.cls}`}>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs">{cfg.emoji}</span>
                  <span className="text-xs font-semibold text-gray-300">{cfg.label}</span>
                  {km.flagged_by === 'user' && (
                    <span className="text-xs text-purple-400 ml-1">Manual</span>
                  )}
                  <span className="text-xs text-gray-500 ml-auto">{fmtTime(km.ts)}</span>
                </div>
                <blockquote className="text-base italic text-gray-100 leading-snug">"{km.quote}"</blockquote>
                {(km.speaker_name || km.speaker_label) && (
                  <p className="text-xs text-gray-400 mt-1">— {km.speaker_name ?? km.speaker_label}</p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
