import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { SalesDataPoint } from '../types/sales'
import { formatMonth } from '../utils/format'
import { Card, CardContent, CardHeader, CardTitle } from './ui/card'

interface Props {
  sales: SalesDataPoint[]
  displayName?: string
}

function rollingAvg(data: SalesDataPoint[], window = 3): (number | null)[] {
  return data.map((_, i) => {
    if (i < window - 1) return null
    const slice = data.slice(i - window + 1, i + 1)
    return Math.round(slice.reduce((s, d) => s + d.units_sold, 0) / window)
  })
}

export function SalesChart({ sales, displayName }: Props) {
  if (!sales.length) {
    return (
      <Card className="h-64 flex items-center justify-center">
        <p className="text-muted-foreground">No data yet — click Refresh Data to fetch sales figures.</p>
      </Card>
    )
  }

  const avgValues = rollingAvg(sales)
  const chartData = sales.map((s, i) => ({
    month: formatMonth(s.month),
    units: s.units_sold,
    avg: avgValues[i],
  }))

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">
          Monthly Sales — {displayName ?? 'Selected bike'} (India)
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis dataKey="month" tick={{ fill: '#94a3b8', fontSize: 12 }} />
          <YAxis
            tickFormatter={v => `${(v / 1000).toFixed(0)}k`}
            tick={{ fill: '#94a3b8', fontSize: 12 }}
          />
          <Tooltip
            contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8 }}
            labelStyle={{ color: '#e2e8f0' }}
            formatter={(value, name) => [
              typeof value === 'number' ? value.toLocaleString() : value,
              name === 'units' ? 'Units Sold' : '3-Month Avg',
            ]}
          />
          <Legend
            formatter={v => (v === 'units' ? 'Units Sold' : '3-Month Rolling Avg')}
            wrapperStyle={{ color: '#94a3b8', fontSize: 12 }}
          />
          <Bar dataKey="units" fill="#3b82f6" radius={[4, 4, 0, 0]} />
          <Line
            type="monotone"
            dataKey="avg"
            stroke="#f59e0b"
            strokeWidth={2}
            dot={false}
            connectNulls={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
