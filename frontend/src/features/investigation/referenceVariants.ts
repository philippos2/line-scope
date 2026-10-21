// Same conservative ordinal grammar as agent/equipment_reference.py.
// Candidates are actual searches; matching spellings never establish identity.
const digits = "零一二三四五六七八九";
function number(text: string): number | null {
  if (/^[0-9]+$/.test(text)) return text.length <= 4 ? Number(text) : null;
  if (/^[零〇一二三四五六七八九]+$/.test(text)) {
    return text.length <= 4
      ? Number(
          [...text].map((c) => (c === "〇" ? 0 : digits.indexOf(c))).join(""),
        )
      : null;
  }
  let total = 0;
  let digit: number | null = null;
  let previousUnit = 10000;
  for (const char of text) {
    if (digits.includes(char)) {
      if (digit !== null) return null;
      digit = digits.indexOf(char);
    } else {
      const unit = ({ 十: 10, 百: 100, 千: 1000 } as Record<string, number>)[
        char
      ];
      if (!unit || unit >= previousUnit || digit === 0) return null;
      total += (digit ?? 1) * unit;
      digit = null;
      previousUnit = unit;
    }
  }
  return total + (digit ?? 0);
}
function kanji(value: number): string {
  if (value === 0) return "零";
  let output = "";
  for (const [unit, suffix] of [
    [1000, "千"],
    [100, "百"],
    [10, "十"],
    [1, ""],
  ] as const) {
    const digit = Math.floor(value / unit);
    value %= unit;
    if (digit)
      output += (digit !== 1 || unit === 1 ? digits[digit] : "") + suffix;
  }
  return output;
}
export function referenceVariants(text: string): string[] {
  const normalized = text.normalize("NFKC");
  const render = (kind: "ascii" | "kanji" | "wide") =>
    normalized.replace(
      /第([0-9零〇一二三四五六七八九十百千]+)(?![0-9零〇一二三四五六七八九十百千万億兆.,，])/g,
      (match: string, original: string) => {
        const value = number(original);
        if (value === null || value > 9999) return match;
        let result = kind === "kanji" ? kanji(value) : String(value);
        if (kind === "wide")
          result = result.replace(/[0-9]/g, (d) =>
            String.fromCharCode(d.charCodeAt(0) + 0xfee0),
          );
        return "第" + result;
      },
    );
  return [
    ...new Set([
      text,
      normalized,
      render("ascii"),
      render("kanji"),
      render("wide"),
    ]),
  ];
}
