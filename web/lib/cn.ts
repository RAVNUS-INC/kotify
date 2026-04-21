export type ClassValue = string | number | null | false | undefined | ClassValue[];

export function cn(...args: ClassValue[]): string {
  const out: string[] = [];
  for (const a of args) {
    if (!a) continue;
    if (typeof a === 'string' || typeof a === 'number') {
      out.push(String(a));
    } else if (Array.isArray(a)) {
      const nested = cn(...a);
      if (nested) out.push(nested);
    }
  }
  return out.join(' ');
}
