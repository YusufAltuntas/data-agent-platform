export function formatCost(usd: number | null | undefined): string {
  return usd == null ? "–" : `$${usd.toFixed(4)}`;
}

export function formatTime(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : "–";
}
