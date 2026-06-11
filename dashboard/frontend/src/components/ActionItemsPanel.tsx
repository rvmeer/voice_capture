import type { ActionItem } from '../types';

interface Props { items: ActionItem[] }

function initials(name: string) {
  return name.split(/\s+/).map((w) => w[0]).join('').toUpperCase().slice(0, 2);
}

export default function ActionItemsPanel({ items }: Props) {
  const open = items.filter((i) => i.status !== 'done');
  const done = items.filter((i) => i.status === 'done');
  const sorted = [...open, ...done];

  return (
    <section className="bg-gray-900 rounded-xl p-5 h-full flex flex-col gap-3">
      <h2 className="text-sm font-bold uppercase tracking-wider text-gray-400">✅ Action Items</h2>
      {!sorted.length ? (
        <p className="text-gray-400 text-sm italic">No action items yet.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {sorted.map((item) => (
            <div key={item.id}
              className={`rounded-lg px-4 py-3 border transition-all ${
                item.owner_is_user
                  ? 'border-amber-500 bg-amber-950/30'
                  : item.status === 'overdue'
                  ? 'border-red-700 bg-red-950/20'
                  : item.status === 'done'
                  ? 'border-gray-700 bg-gray-800/20 opacity-60'
                  : 'border-gray-700 bg-gray-800/50'
              }`}
            >
              <div className="flex items-start gap-3">
                {item.owner_name ? (
                  <span
                    title={item.owner_name}
                    className={`shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold ${
                      item.owner_is_user ? 'bg-amber-500 text-gray-900' : 'bg-gray-600 text-white'
                    }`}
                  >
                    {initials(item.owner_name)}
                  </span>
                ) : (
                  <span className="shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-xs bg-gray-700 text-gray-400 border border-dashed border-gray-500">
                    ?
                  </span>
                )}
                <div className="flex-1 min-w-0">
                  <p className="text-base text-gray-100 leading-snug">{item.description}</p>
                  <div className="flex flex-wrap items-center gap-2 mt-1">
                    {item.owner_is_user && (
                      <span className="text-xs bg-amber-500/20 text-amber-300 border border-amber-500/40 px-2 py-0.5 rounded-full font-semibold">You</span>
                    )}
                    {!item.owner_name && (
                      <span className="text-xs bg-gray-700 text-gray-400 border border-dashed border-gray-500 px-2 py-0.5 rounded-full">Unassigned</span>
                    )}
                    {item.status === 'overdue' && (
                      <span className="text-xs bg-red-700 text-white px-2 py-0.5 rounded-full">Overdue</span>
                    )}
                    {item.status === 'done' && (
                      <span className="text-xs bg-green-700 text-white px-2 py-0.5 rounded-full">Done</span>
                    )}
                    {item.due_date && (
                      <span className="text-xs text-gray-400">Due: {item.due_date}</span>
                    )}
                    {item.topic_label && (
                      <span className="text-xs text-gray-500"># {item.topic_label}</span>
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
