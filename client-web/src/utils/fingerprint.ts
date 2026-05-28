/**
 * Utility to generate and retrieve a stable, persistent browser fingerprint.
 * This is used for return-session authentication in P-O-Q-U-E.
 */
export function getBrowserFingerprint(): string {
  // Check if we already have a stored fingerprint
  const localStorageKey = 'poque_browser_fingerprint';
  let stored = localStorage.getItem(localStorageKey);
  
  if (!stored) {
    // Generate a secure UUID
    try {
      if (typeof crypto !== 'undefined' && crypto.randomUUID) {
        stored = crypto.randomUUID();
      } else {
        // Fallback random generation
        stored = 'pq-' + Math.random().toString(36).substring(2, 15) + '-' + Math.random().toString(36).substring(2, 15);
      }
    } catch (e) {
      stored = 'pq-' + Date.now() + '-' + Math.floor(Math.random() * 1000000);
    }
    localStorage.setItem(localStorageKey, stored);
  }

  // Combine the stored identifier with some stable environmental factors 
  // to form a browser fingerprint hash that is unique, but highly stable.
  const ua = navigator.userAgent || '';
  const lang = navigator.language || '';
  const screenSpec = `${window.screen.width}x${window.screen.height}x${window.screen.colorDepth}`;
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'unknown';
  
  // Create a simple string hash
  const rawFingerprint = `${stored}|${ua}|${lang}|${screenSpec}|${tz}`;
  
  // Let's turn this into a compact hex-like hash representation
  let hashVal = 0;
  for (let i = 0; i < rawFingerprint.length; i++) {
    const char = rawFingerprint.charCodeAt(i);
    hashVal = (hashVal << 5) - hashVal + char;
    hashVal |= 0; // Convert to 32bit integer
  }
  
  const fingerprintHash = Math.abs(hashVal).toString(16).padStart(8, '0');
  
  // We return a combination of the stable client-UUID and the env hash
  // This guarantees uniqueness while binding to physical machine parameters.
  return `PQ-${stored.substring(0, 8)}-${fingerprintHash}`;
}
