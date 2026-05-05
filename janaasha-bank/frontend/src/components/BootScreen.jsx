import { useEffect, useState } from "react";

export default function BootScreen({ onDone }) {
  const [fading, setFading] = useState(false);

  useEffect(() => {
    const fadeTimer = setTimeout(() => setFading(true), 1400);
    const doneTimer = setTimeout(onDone, 1850);
    return () => {
      clearTimeout(fadeTimer);
      clearTimeout(doneTimer);
    };
  }, [onDone]);

  return (
    <div className={`boot ${fading ? "fade" : ""}`}>
      <div className="boot-inner">
        <div className="boot-logo">JN</div>
        <div className="boot-brand">JANAASHA TN NIDHI</div>
        <div className="boot-sub">Daily Reconciliation Terminal</div>
        <div className="boot-progress">
          <div className="boot-bar" />
        </div>
        <div className="boot-status">INITIALIZING WORKSPACE</div>
      </div>
    </div>
  );
}
