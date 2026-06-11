import type { Participant, ToneInfo } from '../types';

interface Props {
  participants: Participant[];
  tone: ToneInfo;
}

const TONE_CONFIG = {
  constructive: { label: 'Constructive', cls: 'bg-green-600', bar: 'bg-green-500' },
  neutral:      { label: 'Neutral',      cls: 'bg-gray-500',  bar: 'bg-gray-400' },
  tense:        { label: 'Tense',        cls: 'bg-red-600',   bar: 'bg-red-500' },
};

const COLORS = [
  'bg-blue-500', 'bg-purple-500', 'bg-pink-500', 'bg-teal-500',
  'bg-orange-500', 'bg-cyan-500', 'bg-lime-500', 'bg-indigo-500',
];

export default function SpeakingTonePanel({ participants, tone }: Props) {
  const toneCfg = TONE_CONFIG[tone.label] ?? TONE_CONFIG.neutral;
  const gaugePct = Math.round(((tone.window_avg + 1) / 2) * 100);

  return (
    <section className="bg-gray-900 rounded-xl p-5 h-full flex flex-col gap-4">
      <h2 className="text-sm font-bold uppercase tracking-wider text-gray-400">🎙 Speaking &amp; Tone</h2>

      {/* Speaking bars */}
      <div className="flex flex-col gap-2">
        {participants
          .filter((p) => p.speaking_seconds > 0)
          .sort((a, b) => b.speaking_time_ratio - a.speaking_time_ratio)
          .map((p, i) => (
            <div key={p.id} className="flex items-center gap-3">
              <span className="text-sm text-gray-200 w-32 shrink-0 truncate" title={p.name}>
                {p.name.split(' ')[0]}
                {p.is_user && <span className="ml-1 text-xs text-amber-400">★</span>}
              </span>
              <div className="flex-1 bg-gray-700 rounded-full h-3 overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-700 ${COLORS[i % COLORS.length]}`}
                  style={{ width: `${Math.round(p.speaking_time_ratio * 100)}%` }}
                />
              </div>
              <span className="text-xs text-gray-400 w-10 text-right font-mono">
                {Math.round(p.speaking_time_ratio * 100)}%
              </span>
            </div>
          ))}
        {!participants.some((p) => p.speaking_seconds > 0) && (
          <p className="text-gray-400 text-sm italic">No speaking data yet.</p>
        )}
      </div>

      {/* Tone gauge */}
      <div className="mt-auto">
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs text-gray-400">Tone (3-min window)</span>
          <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${toneCfg.cls} text-white`}>
            {toneCfg.label}
          </span>
        </div>
        <div className="bg-gray-700 rounded-full h-3 overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-700 ${toneCfg.bar}`}
            style={{ width: `${gaugePct}%` }}
          />
        </div>
        <div className="flex justify-between text-xs text-gray-500 mt-1">
          <span>Tense</span>
          <span>Constructive</span>
        </div>
      </div>
    </section>
  );
}
