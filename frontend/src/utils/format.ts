const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export function formatMonth(yyyyMm: string): string {
  const [year, month] = yyyyMm.split('-')
  const mon = MONTHS[parseInt(month, 10) - 1] ?? month
  return `${mon} '${year.slice(2)}`
}
