import type { AgendaItem } from '../types';

function fmtDuration(secs: number | null) {
  if (!secs) return '';
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

interface Props { items: AgendaItem[] }

export default function AgendaPanel({ items }: Props) {
  return (
    <section className="bg-gray-900 rounded-xl p-5 h-full flex flex-col gap-3">
      <h2 className="text-sm font-bold uppercase tracking-wider text-gray-400">📋 Agenda</h2>
      {!items.length ? (
        <p className="text-gray-400 text-sm italic">No agenda defined.</p>
      ) : (
        <ol className="flex flex-col gap-2">
          {items.sort((a, b) => a.position - b.position).map((item) => (
            <li key={item.id}
              className={`flex items-center gap-3 rounded-lg px-4 py-3 transition-all ${
                item.status === 'active'
                  ? 'bg-blue-900/50 border border-blue-500'
                  : item.status === 'done'
                  ? 'bg-gray-800/30 opacity-60'
                  : 'bg-gray-800/50'
              }`}
            >
              <span className={`w-3 h-3 shrink-0 rounded-full ${
                item.status === 'done' ? 'bg-green-500' :
                item.status === 'active' ? 'bg-blue-400 animate-pulse' :
                'bg-gray-500'
              }`} />
              <span className="flex-1 text-base font-medium text-gray-100">{item.title}</span>
              {item.status === 'done' && item.duration_seconds && (
                <span className="text-xs text-gray-400 font-mono">{fmtDuration(item.duration_seconds)}</span>
              )}
              {item.status === 'active' && (
                <span className="text-xs bg-blue-600 px-2 py-0.5 rounded text-white">Active</span>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
