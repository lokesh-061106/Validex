import React, { useEffect, useRef, useState } from 'react';
import { Camera, Upload } from 'lucide-react';
import { errorMessage, infrastructureApi } from '../api/client';
import type { InfraReport } from '../types';
import { Button, Card, Pill } from '../components/ui';

export const InfrastructurePage: React.FC = () => {
  const input = useRef<HTMLInputElement>(null);
  const [norms, setNorms] = useState<{ object: string; min: number; label: string; rule_code: string }[]>([]);
  const [report, setReport] = useState<InfraReport | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => { infrastructureApi.norms().then(setNorms); }, []);

  const analyze = async (file?: File) => {
    if (!file) return;
    setBusy(true);
    setError('');
    setReport(null);
    setPreview(file.type.startsWith('image/') ? URL.createObjectURL(file) : null);
    try {
      setReport(await infrastructureApi.analyze(file));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Infrastructure CV Studio</h1>
        <p className="text-sm text-slate-500 mt-0.5">Try the equipment detector on any lab photo or walkthrough video. Counts are advisory and flag cases for more evidence or inspection.</p>
      </div>

      <div className="grid lg:grid-cols-3 gap-5">
        <Card title="Analyse evidence" className="lg:col-span-2">
          <input ref={input} type="file" accept="image/jpeg,image/png,video/mp4" className="hidden" onChange={(e) => analyze(e.target.files?.[0])} aria-label="Upload lab photo or video" />
          <Button variant="primary" busy={busy} onClick={() => input.current?.click()}><Upload className="w-4 h-4" />Upload photo or MP4</Button>
          {error && <p className="text-xs text-rose-600 mt-3" role="alert">{error}</p>}
          {(report?.annotated_image_base64 || preview) && (
            <img src={report?.annotated_image_base64 || preview!} alt="Analysed evidence" className="w-full rounded-xl border border-slate-200 mt-4" />
          )}
          {!report && !preview && (
            <div className="mt-4 p-10 rounded-xl border border-dashed border-slate-300 text-center text-slate-500 text-xs">
              <Camera className="w-8 h-8 mx-auto mb-2 text-slate-400" />Upload a real computer-lab photo to see detections.
            </div>
          )}
        </Card>

        <div className="space-y-4">
          <Card title="Configured norms (from rules)">
            {norms.length === 0 ? <p className="text-xs text-slate-500">No infrastructure rules active.</p> : (
              <ul className="text-xs space-y-1">{norms.map((n) => <li key={n.rule_code} className="flex justify-between"><span>{n.label}</span><span className="font-mono">≥ {n.min} {n.object}</span></li>)}</ul>
            )}
          </Card>
          {report && (
            <>
              <Card title="Result">
                <p className="text-[11px] text-slate-500 mb-2">{report.model || 'Detector unavailable'} · {report.status} · {report.frames_analyzed} frame(s)</p>
                <ul className="space-y-2 text-xs">
                  {report.compliance_flags.map((f) => (
                    <li key={f.object} className="flex justify-between gap-2"><span>{f.equipment}</span><Pill tone={f.status === 'compliant' ? 'emerald' : f.status === 'deficient' ? 'rose' : 'sky'}>{f.message}</Pill></li>
                  ))}
                </ul>
                {report.evidence_quality.issues.map((i) => <p key={i} className="text-[11px] text-amber-700 mt-2">⚠ {i}</p>)}
              </Card>
              <Card title="Raw detections (COCO classes)">
                <div className="flex flex-wrap gap-1">{Object.entries(report.raw_detections).map(([k, v]) => <span key={k} className="text-[11px] px-1.5 py-0.5 rounded bg-slate-100 font-mono">{k}: {v}</span>)}</div>
                <p className="text-[10px] text-slate-400 mt-2">{report.disclaimer} Monitors are detected as “tv”; workstations = max(monitors + laptops, keyboards).</p>
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
};
