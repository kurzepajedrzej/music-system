import { useEffect, useState } from 'react';

export function useIsMobile(breakpointPx = 768): boolean {
  const [isMobile, setIsMobile] = useState(() => window.innerWidth < breakpointPx);

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < breakpointPx);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [breakpointPx]);

  return isMobile;
}
