import { Badge } from '../ui/badge'
import { METHODS, type Method } from './methods'

function MethodCard({
  method,
  selected,
  onClick,
}: {
  method: (typeof METHODS)[number]
  selected: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`relative text-left p-4 rounded-xl border transition-all ${
        selected
          ? 'bg-primary/15 border-primary/70 ring-1 ring-primary/50'
          : 'bg-card border-border hover:border-input'
      }`}
    >
      {method.badge && (
        <Badge variant="secondary" className="absolute top-3 right-3 rounded-full">
          {method.badge}
        </Badge>
      )}
      <div className="text-2xl mb-2">{method.icon}</div>
      <p className="font-semibold text-foreground text-sm mb-1">{method.label}</p>
      <p className="text-xs text-muted-foreground leading-relaxed">{method.description}</p>
    </button>
  )
}

export function MethodPicker({
  method,
  onChange,
}: {
  method: Method
  onChange: (method: Method) => void
}) {
  return (
    <div>
      <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
        Analysis Method
      </h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-3">
        {METHODS.map(m => (
          <MethodCard
            key={m.id}
            method={m}
            selected={method === m.id}
            onClick={() => onChange(m.id)}
          />
        ))}
      </div>
    </div>
  )
}
