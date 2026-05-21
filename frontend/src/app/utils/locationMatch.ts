const ADMIN_SUFFIXES = ['县', '郡', '国', '州', '尹', '属国'];

export function normalizeLocationName(name: string) {
  return name
    .trim()
    .replace(/[（）()【】\[\]\s]/g, '')
    .replace(/，/g, ',');
}

export function stripAdminSuffix(name: string) {
  const normalized = normalizeLocationName(name);
  const suffix = ADMIN_SUFFIXES.find(s => normalized.endsWith(s));
  return suffix ? normalized.slice(0, -suffix.length) : normalized;
}

export function locationNameMatches(a: string, b: string) {
  const left = normalizeLocationName(a);
  const right = normalizeLocationName(b);
  if (!left || !right) return false;
  if (left === right) return true;

  const leftBase = stripAdminSuffix(left);
  const rightBase = stripAdminSuffix(right);
  if (leftBase.length < 2 || rightBase.length < 2) return false;
  return leftBase === rightBase;
}

export function locationMatchesGeoName(locationName: string, geo: { std_name?: string; aliases?: string[] }) {
  if (geo.std_name && locationNameMatches(locationName, geo.std_name)) return true;
  return (geo.aliases ?? []).some(alias => locationNameMatches(locationName, alias));
}
